"""Section 32: the inference tier's contract, against the real INT8 model."""
import json


def test_inference_returns_required_fields(inference):
    result = inference.predict("I found an error on my credit report.")

    assert set(result) >= {"category", "confidence", "model_version"}
    assert result["category"] in inference.LABELS
    # Catches a softmax applied on the wrong axis, or a raw logit returned as confidence.
    assert 0.0 <= result["confidence"] <= 1.0


def test_sqs_record_is_read_from_s3_predicted_and_stored(inference, aws_env, monkeypatch):
    monkeypatch.setattr(inference, "BUCKET", aws_env["bucket"])
    monkeypatch.setattr(inference, "DDB_TABLE", aws_env["table"])
    monkeypatch.setattr(inference, "_s3", aws_env["s3"])
    import boto3
    monkeypatch.setattr(inference, "_ddb", boto3.resource("dynamodb", region_name="us-east-1"))

    aws_env["s3"].put_object(
        Bucket=aws_env["bucket"], Key="complaints/abc123.json",
        Body=json.dumps({"complaint_id": "abc123",
                         "text": "My mortgage servicer misapplied my escrow payment."}).encode())

    event = {"Records": [{"body": json.dumps({"complaint_id": "abc123",
                                              "s3_key": "complaints/abc123.json"})}]}
    out = inference.handler(event, None)

    assert out["processed"] == 1
    item = aws_env["ddb"].get_item(TableName=aws_env["table"],
                                   Key={"complaint_id": {"S": "abc123"}})["Item"]
    assert item["prediction"]["S"] == out["results"][0]["category"]
    # DynamoDB rejects Python floats; the handler must write Decimal(str(x)).
    assert 0.0 <= float(item["confidence"]["N"]) <= 1.0
