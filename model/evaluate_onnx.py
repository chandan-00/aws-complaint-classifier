"""Section 21: score an exported ONNX model on the held-out test split."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, f1_score
from tokenizers import Tokenizer


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="model/model_int8.onnx")
    p.add_argument("--split", default="data/test.parquet")
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--report", action="store_true", help="print the full per-class report")
    args = p.parse_args()

    meta = json.loads(Path("model/metadata.json").read_text())
    labels, max_len = meta["labels"], meta["max_length"]

    tok = Tokenizer.from_file("model/tokenizer.json")
    tok.enable_truncation(max_length=max_len)
    tok.enable_padding(length=max_len)

    sess = ort.InferenceSession(args.model, providers=["CPUExecutionProvider"])
    df = pd.read_parquet(args.split)

    preds = []
    started = time.perf_counter()
    for i in range(0, len(df), args.batch_size):
        encs = tok.encode_batch(df.text.iloc[i:i + args.batch_size].tolist())
        logits = sess.run(None, {
            "input_ids": np.array([e.ids for e in encs], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encs], dtype=np.int64),
        })[0]
        preds.extend(labels[j] for j in logits.argmax(1))
    elapsed = time.perf_counter() - started

    print(f"{args.model}  {len(df)} rows in {elapsed:.1f}s ({1000 * elapsed / len(df):.1f} ms/row, batched)")
    print(f"accuracy {accuracy_score(df.label, preds):.4f}   "
          f"macro_f1 {f1_score(df.label, preds, average='macro'):.4f}")
    if args.report:
        print(classification_report(df.label, preds, digits=4))


if __name__ == "__main__":
    main()
