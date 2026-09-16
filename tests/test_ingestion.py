"""Section 32: the API tier's contract — what goes in, what comes out, what is rejected."""
import json


def test_valid_input_produces_id_s3_object_and_sqs_message(ingestion, aws_env):
    resp = ingestion.handler(
        {"httpMethod": "POST",
         "body": json.dumps({"text": "I found an error on my credit report."})}, None)

    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body["status"] == "queued"
    complaint_id = body["complaint_id"]

    stored = json.loads(
        aws_env["s3"].get_object(Bucket=aws_env["bucket"],
                                 Key=f"complaints/{complaint_id}.json")["Body"].read())
    assert stored["text"] == "I found an error on my credit report."

    messages = aws_env["sqs"].receive_message(QueueUrl=aws_env["queue_url"],
                                              MaxNumberOfMessages=10).get("Messages", [])
    assert len(messages) == 1
    # The message is a pointer, not the text (256 KB SQS limit, section 24).
    message = json.loads(messages[0]["Body"])
    assert message == {"complaint_id": complaint_id,
                       "s3_key": f"complaints/{complaint_id}.json",
                       "model_version": "test-model"}


def test_invalid_input_is_rejected(ingestion, aws_env):
    resp = ingestion.handler({"httpMethod": "POST", "body": json.dumps({"text": "hi"})}, None)

    assert resp["statusCode"] == 400
    # Rejected at the door: nothing stored, nothing queued, no inference paid for.
    assert "Contents" not in aws_env["s3"].list_objects_v2(Bucket=aws_env["bucket"])
    assert not aws_env["sqs"].receive_message(QueueUrl=aws_env["queue_url"]).get("Messages")


def test_get_returns_stored_prediction_and_404_before_it_exists(ingestion, aws_env):
    missing = ingestion.handler({"httpMethod": "GET", "pathParameters": {"complaint_id": "nope"}}, None)
    assert missing["statusCode"] == 404
    assert json.loads(missing["body"])["status"] == "pending_or_unknown"

    aws_env["ddb"].put_item(TableName=aws_env["table"], Item={
        "complaint_id": {"S": "abc123"},
        "prediction": {"S": "credit_reporting"},
        "confidence": {"N": "0.91"},
    })
    found = ingestion.handler({"httpMethod": "GET", "pathParameters": {"complaint_id": "abc123"}}, None)
    assert found["statusCode"] == 200
    body = json.loads(found["body"])
    assert body["prediction"] == "credit_reporting"
    assert body["confidence"] == 0.91          # Decimal survives json.dumps as a float
