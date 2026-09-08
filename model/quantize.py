"""Dynamically quantize the FP32 ONNX model to INT8 and record the size delta."""
import argparse
from pathlib import Path

from onnxruntime.quantization import QuantType, quantize_dynamic
from onnxruntime.quantization.shape_inference import quant_pre_process


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="model/model_fp32.onnx")
    p.add_argument("--out", default="model/model_int8.onnx")
    args = p.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    prepped = src.with_name("model_prepped.onnx")

    quant_pre_process(str(src), str(prepped), skip_symbolic_shape=False)

    quantize_dynamic(
        model_input=str(prepped),
        model_output=str(out),
        weight_type=QuantType.QInt8,
    )

    fp32 = src.stat().st_size / 1e6
    int8 = out.stat().st_size / 1e6
    print(f"FP32 : {fp32:7.1f} MB")
    print(f"INT8 : {int8:7.1f} MB")
    print(f"Ratio: {fp32 / int8:7.2f}x smaller ({100 * (1 - int8 / fp32):.1f}% reduction)")


if __name__ == "__main__":
    main()