"""Shared fixtures. Both handlers read env vars and build boto3 clients at import time,
so the environment has to exist before the module is imported — hence the importlib dance."""
import os
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

REPO = Path(__file__).resolve().parents[1]
BUCKET = "test-complaints"
QUEUE = "test-complaints-queue"
TABLE = "ComplaintPredictions"
REGION = "us-east-1"


@pytest.fixture
def aws_env(monkeypatch):
    """Fake credentials and the env vars both Lambdas expect, inside a moto mock."""
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": REGION,
        "AWS_REGION": REGION,
        "BUCKET": BUCKET,
        "DDB_TABLE": TABLE,
        "MODEL_VERSION": "test-model",
    }.items():
        monkeypatch.setenv(k, v)

    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        sqs = boto3.client("sqs", region_name=REGION)
        queue_url = sqs.create_queue(QueueName=QUEUE)["QueueUrl"]
        monkeypatch.setenv("QUEUE_URL", queue_url)

        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "complaint_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "complaint_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield {"s3": s3, "sqs": sqs, "ddb": ddb, "queue_url": queue_url,
               "bucket": BUCKET, "table": TABLE}


@pytest.fixture
def ingestion(aws_env):
    """The API Lambda, imported fresh so it binds to the mocked resources."""
    sys.path.insert(0, str(REPO / "lambda" / "ingestion"))
    sys.modules.pop("handler", None)
    import handler

    return handler


@pytest.fixture(scope="session")
def inference():
    """The inference Lambda. Loads the real INT8 model once for the whole session."""
    if not (REPO / "model" / "model_int8.onnx").exists():
        pytest.skip("model/model_int8.onnx not built; run model/quantize.py")
    os.environ["LAMBDA_TASK_ROOT"] = str(REPO)
    # app.py builds its boto3 clients at import; without fake credentials here they resolve
    # against the real credential chain (and the developer's aws login profile).
    os.environ.pop("AWS_PROFILE", None)
    os.environ.update({
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": REGION,
        "AWS_REGION": REGION,
    })
    sys.path.insert(0, str(REPO / "lambda" / "inference"))
    import app

    return app
