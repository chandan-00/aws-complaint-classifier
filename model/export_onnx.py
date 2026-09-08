import argparse
import json
from pathlib import Path

import torch
import numpy as np
import onnx
from onnx import TensorProto, numpy_helper
import onnxruntime as ort
from transformers import AutoTokenizer, AutoModelForSequenceClassification


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="distilbert-base-uncased")
    p.add_argument("--labels", default=None, help="path to JSON list of label names")
    p.add_argument("--out", default="model")
    p.add_argument("--max-length", type=int, default=256)
    args = p.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.labels:
        labels = json.loads(Path(args.labels).read_text())
    else:
        labels = [f"placeholder_{i}" for i in range(6)]

    tokenizer = AutoTokenizer.from_pretrained(args.src)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.src,
        attn_implementation="eager",
        num_labels=len(labels),
        id2label={i: l for i, l in enumerate(labels)},
        label2id={l: i for i, l in enumerate(labels)},
    )
    model.eval()

    sample = tokenizer(
        "placeholder complaint narrative",
        return_tensors="pt",
        max_length=args.max_length,
        padding="max_length",
        truncation=True,
    )

    torch.onnx.export(
        model,
        (sample["input_ids"], sample["attention_mask"]),
        out / "model_fp32.onnx",
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids":      {0: "batch"},
            "attention_mask": {0: "batch"},
            "logits":         {0: "batch"},
        },
        opset_version=14,
        do_constant_folding=True,
    )

    onnx_path = out / "model_fp32.onnx"

    m = onnx.load(str(onnx_path))
    for init in m.graph.initializer:
        if init.data_type == TensorProto.DOUBLE:
            arr = numpy_helper.to_array(init).astype("float32")
            init.CopyFrom(numpy_helper.from_array(arr, init.name))
    for node in m.graph.node:
        for attr in node.attribute:
            if attr.name == "value" and attr.t.data_type == TensorProto.DOUBLE:
                arr = numpy_helper.to_array(attr.t).astype("float32")
                attr.t.CopyFrom(numpy_helper.from_array(arr, attr.t.name))
    onnx.save(m, str(onnx_path))
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    logits = sess.run(None, {
        "input_ids":      sample["input_ids"].numpy().astype(np.int64),
        "attention_mask": sample["attention_mask"].numpy().astype(np.int64),
    })[0]
    assert logits.shape == (1, len(labels)), logits.shape
    print(f"ORT load OK, logits {logits.shape}")

    tokenizer.save_pretrained(out)
    (out / "metadata.json").write_text(
        json.dumps(
            {"labels": labels, "max_length": args.max_length, "base_model": args.src},
            indent=2,
        )
    )

    mb = (out / "model_fp32.onnx").stat().st_size / 1e6
    print(f"FP32 ONNX written: {mb:.1f} MB, {len(labels)} labels")


if __name__ == "__main__":
    main()
