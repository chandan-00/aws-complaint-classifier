"""Compare PyTorch, ONNX FP32 and ONNX INT8 prediction by prediction on the test split.

Matching macro-F1 does not show that two backends make the same predictions, only that
they score the same in aggregate. This checks agreement per complaint, the size of logit
differences, and whether wrong predictions carry lower confidence than right ones.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd
import torch
from tokenizers import Tokenizer
from transformers import AutoModelForSequenceClassification


def softmax(logits: np.ndarray) -> np.ndarray:
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


def encode(texts: list[str], tok: Tokenizer) -> tuple[np.ndarray, np.ndarray]:
    encs = tok.encode_batch(texts)
    ids = np.array([e.ids for e in encs], dtype=np.int64)
    mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
    return ids, mask


def onnx_logits(path: str, ids: np.ndarray, mask: np.ndarray, batch: int) -> np.ndarray:
    sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    out = [sess.run(None, {"input_ids": ids[i:i + batch], "attention_mask": mask[i:i + batch]})[0]
           for i in range(0, len(ids), batch)]
    return np.concatenate(out)


def torch_logits(src: str, ids: np.ndarray, mask: np.ndarray, batch: int) -> np.ndarray:
    model = AutoModelForSequenceClassification.from_pretrained(src).eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(ids), batch):
            out.append(model(input_ids=torch.from_numpy(ids[i:i + batch]),
                             attention_mask=torch.from_numpy(mask[i:i + batch])).logits.numpy())
    return np.concatenate(out)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--torch-src", default="distilbert-complaints/distilbert-complaints")
    p.add_argument("--split", default="data/test.parquet")
    p.add_argument("--batch-size", type=int, default=16)
    args = p.parse_args()

    meta = json.loads(Path("model/metadata.json").read_text())
    labels, max_len = meta["labels"], meta["max_length"]
    tok = Tokenizer.from_file("model/tokenizer.json")
    tok.enable_truncation(max_length=max_len)
    tok.enable_padding(length=max_len)

    df = pd.read_parquet(args.split)
    y = np.array([labels.index(label) for label in df.label])
    ids, mask = encode(df.text.tolist(), tok)  # identical inputs for every backend

    logits = {
        "pytorch": torch_logits(args.torch_src, ids, mask, args.batch_size),
        "onnx_fp32": onnx_logits("model/model_fp32.onnx", ids, mask, args.batch_size),
        "onnx_int8": onnx_logits("model/model_int8.onnx", ids, mask, args.batch_size),
    }
    preds = {k: v.argmax(axis=1) for k, v in logits.items()}

    print(f"{len(df)} test complaints\n")
    print("Prediction agreement")
    for a, b in [("pytorch", "onnx_fp32"), ("onnx_fp32", "onnx_int8"), ("pytorch", "onnx_int8")]:
        same = (preds[a] == preds[b]).sum()
        diff = np.abs(logits[a] - logits[b]).max()
        print(f"  {a:9s} vs {b:9s}: {same}/{len(df)} identical ({same / len(df):.2%}), "
              f"max |logit diff| {diff:.2e}")

    probs = softmax(logits["onnx_int8"])
    conf = probs.max(axis=1)
    correct = preds["onnx_int8"] == y
    print("\nConfidence, ONNX INT8 (deployed model)")
    for name, sel in [("correct", correct), ("wrong", ~correct)]:
        c = conf[sel]
        print(f"  {name:7s} n={sel.sum():3d}  median {np.median(c):.3f}  mean {c.mean():.3f}  "
              f"share below 0.6: {(c < 0.6).mean():.1%}")
    print("\n  Accuracy by confidence band")
    for lo, hi in [(0.0, 0.6), (0.6, 0.8), (0.8, 0.9), (0.9, 1.01)]:
        sel = (conf >= lo) & (conf < hi)
        if sel.any():
            print(f"    [{lo:.1f}, {min(hi, 1.0):.1f}): n={sel.sum():3d}  accuracy {correct[sel].mean():.1%}")


if __name__ == "__main__":
    main()
