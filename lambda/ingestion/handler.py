"""API Lambda: POST /complaints queues work, GET /complaints/{id} returns the result.

One function serves both routes (section 27): two Lambdas would mean two IAM roles, two log
groups and two deploy paths to save a handful of lines. The boundary that matters is between
this API tier (S3 write, SQS send, DynamoDB read) and the inference tier (S3 read, DynamoDB
write), and that is preserved.
"""
import json
import os
import time
import uuid
from decimal import Decimal

import boto3

BUCKET = os.environ["BUCKET"]
QUEUE_URL = os.environ["QUEUE_URL"]
DDB_TABLE = os.environ["DDB_TABLE"]
MODEL_VERSION = os.environ.get("MODEL_VERSION", "distilbert-v2-int8")
MIN_CHARS = 10

_s3 = boto3.client("s3")
_sqs = boto3.client("sqs")
_table = boto3.resource("dynamodb").Table(DDB_TABLE)


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=lambda o: float(o) if isinstance(o, Decimal) else str(o)),
    }


def _post(event: dict) -> dict:
    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "body is not valid JSON"})

    text = (payload.get("text") or "").strip()
    if len(text) < MIN_CHARS:
        return _response(400, {"error": f"field 'text' is required and must be at least {MIN_CHARS} characters"})

    complaint_id = payload.get("complaint_id") or uuid.uuid4().hex[:12]
    key = f"complaints/{complaint_id}.json"

    # S3 is the durable record: SQS messages are consumed and expire, so this is the only
    # place the input still exists if the model changes and everything is re-scored.
    _s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps({
            "complaint_id": complaint_id,
            "text": text,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }).encode(),
        ContentType="application/json",
    )

    # The message carries a pointer, not the text: SQS caps a body at 256 KB and this
    # contract does not change as inputs grow.
    _sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps({
            "complaint_id": complaint_id,
            "s3_key": key,
            "model_version": MODEL_VERSION,
        }),
    )

    print(json.dumps({"event": "message_queued", "complaint_id": complaint_id}))
    # 202, not 200: the work has been accepted, not done. The API never waits for inference.
    return _response(202, {"complaint_id": complaint_id, "status": "queued"})


def _get(event: dict) -> dict:
    complaint_id = (event.get("pathParameters") or {}).get("complaint_id")
    if not complaint_id:
        return _response(400, {"error": "complaint_id is required"})

    item = _table.get_item(Key={"complaint_id": complaint_id}).get("Item")
    if not item:
        # In an async system "still processing" and "never existed" are genuinely
        # indistinguishable without another lookup. Say so rather than implying certainty.
        return _response(404, {"complaint_id": complaint_id, "status": "pending_or_unknown"})
    return _response(200, item)


def handler(event, context):
    method = event.get("httpMethod", "POST")
    if method == "POST":
        return _post(event)
    if method == "GET":
        return _get(event)
    return _response(405, {"error": f"method {method} not allowed"})
