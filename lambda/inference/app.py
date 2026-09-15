"""Inference Lambda: SQS event or direct invoke -> ONNX INT8 prediction -> DynamoDB."""
import json
import os
import time
from decimal import Decimal

import boto3
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

# ---------------------------------------------------------------------------
# Module scope. Runs ONCE per container, not once per invocation.
# Moving any of this inside handler() turns every request into a cold start
# and destroys the latency measurements in section 21.
# ---------------------------------------------------------------------------
TASK_ROOT = os.environ.get("LAMBDA_TASK_ROOT", ".")
MODEL_DIR = os.path.join(TASK_ROOT, "model")

with open(os.path.join(MODEL_DIR, "metadata.json")) as f:
    META = json.load(f)

REGION = os.environ.get("AWS_REGION", "us-east-1")

LABELS = META["labels"]
MAX_LEN = META["max_length"]
MODEL_VERSION = os.environ.get("MODEL_VERSION", "distilbert-v2-int8")
DDB_TABLE = os.environ.get("DDB_TABLE")
BUCKET = os.environ.get("BUCKET")

_tokenizer = Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))
_tokenizer.enable_truncation(max_length=MAX_LEN)
_tokenizer.enable_padding(length=MAX_LEN)

_session = ort.InferenceSession(
    os.path.join(MODEL_DIR, "model_int8.onnx"),
    providers=["CPUExecutionProvider"],
)

_s3 = boto3.client("s3", region_name=REGION)
_ddb = boto3.resource("dynamodb", region_name=REGION)


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()


def predict(text: str) -> dict:
    enc = _tokenizer.encode(text)
    ids = np.array([enc.ids], dtype=np.int64)
    mask = np.array([enc.attention_mask], dtype=np.int64)

    started = time.perf_counter()
    logits = _session.run(None, {"input_ids": ids, "attention_mask": mask})[0][0]
    elapsed_ms = (time.perf_counter() - started) * 1000

    probs = _softmax(logits)
    idx = int(np.argmax(probs))
    return {
        "category": LABELS[idx],
        "confidence": float(probs[idx]),
        "model_version": MODEL_VERSION,
        "inference_ms": round(elapsed_ms, 2),
    }


def _load_text(record: dict) -> tuple[str, str]:
    """Return (complaint_id, text) from either a direct payload or an S3 pointer."""
    if "text" in record:
        return record["complaint_id"], record["text"]

    obj = _s3.get_object(Bucket=BUCKET, Key=record["s3_key"])
    body = json.loads(obj["Body"].read())
    return body["complaint_id"], body["text"]


def _store(complaint_id: str, result: dict) -> None:
    if not DDB_TABLE:
        return
    _ddb.Table(DDB_TABLE).put_item(
        Item={
            "complaint_id": complaint_id,
            "prediction": result["category"],
            # DynamoDB rejects Python floats. Decimal(str(x)) is the correct
            # conversion; Decimal(float) introduces binary float noise.
            "confidence": Decimal(str(round(result["confidence"], 4))),
            "model_version": result["model_version"],
            "inference_ms": Decimal(str(result["inference_ms"])),
            "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )

def handler(event, context):
    # Direct invoke (the RIE curl in section 12, and console tests): no SQS envelope.
    if "Records" not in event:
        result = predict(event["text"])
        return {"complaint_id": event.get("complaint_id"), **result}

    # SQS path. batch_size is 1 (section 25.1), so a failure fails one message and that
    # message alone is redriven, then dead-lettered after maxReceiveCount.
    results = []
    for record in event["Records"]:
        message = json.loads(record["body"])
        complaint_id, text = _load_text(message)

        result = predict(text)
        _store(complaint_id, result)

        # One structured line per message: this is what CloudWatch Logs Insights queries.
        print(json.dumps({"event": "prediction_stored", "complaint_id": complaint_id, **result}))
        results.append({"complaint_id": complaint_id, **result})

    return {"processed": len(results), "results": results}