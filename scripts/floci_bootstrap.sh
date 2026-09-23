#!/usr/bin/env bash
# Section 33: build the whole pipeline inside Floci. Idempotent - safe to re-run after a
# container restart, which is why it is a script and not a sequence you remember.
set -euo pipefail

export AWS_PAGER=""
AWS="aws --endpoint-url=http://localhost:4566 --region us-east-1"
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1

BUCKET=complaints-local
QUEUE=complaint-queue
DLQ=complaint-dlq
TABLE=ComplaintPredictions
IMAGE=${IMAGE:-complaint-inference:v3-int8}
MODEL_VERSION="distilbert-${IMAGE#*:}"   # same format as terraform (lambda.tf)
INFERENCE_FN=complaint-inference
API_FN=complaint-api
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== S3"
$AWS s3api create-bucket --bucket "$BUCKET" >/dev/null 2>&1 || true

echo "== SQS (DLQ first: the main queue's redrive policy needs its ARN)"
$AWS sqs create-queue --queue-name "$DLQ" >/dev/null 2>&1 || true
DLQ_URL=$($AWS sqs get-queue-url --queue-name "$DLQ" --query QueueUrl --output text)
DLQ_ARN=$($AWS sqs get-queue-attributes --queue-url "$DLQ_URL" \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

# VisibilityTimeout must be >= 6x the Lambda timeout (60s), or the event source mapping is
# rejected and messages are redelivered while still being processed (section 25.1).
$AWS sqs create-queue --queue-name "$QUEUE" --attributes "{
  \"VisibilityTimeout\": \"360\",
  \"RedrivePolicy\": \"{\\\"deadLetterTargetArn\\\":\\\"$DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"
}" >/dev/null 2>&1 || true
QUEUE_URL=$($AWS sqs get-queue-url --queue-name "$QUEUE" --query QueueUrl --output text)
QUEUE_ARN=$($AWS sqs get-queue-attributes --queue-url "$QUEUE_URL" \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

echo "== DynamoDB"
$AWS dynamodb create-table --table-name "$TABLE" \
  --key-schema AttributeName=complaint_id,KeyType=HASH \
  --attribute-definitions AttributeName=complaint_id,AttributeType=S \
  --billing-mode PAY_PER_REQUEST >/dev/null 2>&1 || true

echo "== IAM role (Floci does not enforce policies; the real split is in Terraform, section 40)"
ROLE_ARN=$($AWS iam create-role --role-name lambda-local \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  --query 'Role.Arn' --output text 2>/dev/null || \
  $AWS iam get-role --role-name lambda-local --query 'Role.Arn' --output text)

# Lambdas run in their own containers: localhost there is the function, not the emulator.
LAMBDA_ENV="{BUCKET=$BUCKET,QUEUE_URL=$QUEUE_URL,DDB_TABLE=$TABLE,MODEL_VERSION=$MODEL_VERSION,AWS_ENDPOINT_URL=http://floci:4566}"

echo "== Inference Lambda (container image, built locally - never pulled)"
$AWS lambda delete-function --function-name "$INFERENCE_FN" >/dev/null 2>&1 || true
$AWS lambda create-function --function-name "$INFERENCE_FN" \
  --package-type Image --code "ImageUri=$IMAGE" --role "$ROLE_ARN" \
  --timeout 60 --memory-size 2048 \
  --environment "Variables=$LAMBDA_ENV" >/dev/null

echo "== API Lambda (zip)"
BUILD=$(mktemp -d)
cp "$ROOT/lambda/ingestion/handler.py" "$BUILD/"
(cd "$BUILD" && zip -q handler.zip handler.py)
$AWS lambda delete-function --function-name "$API_FN" >/dev/null 2>&1 || true
$AWS lambda create-function --function-name "$API_FN" \
  --runtime python3.12 --handler handler.handler --role "$ROLE_ARN" \
  --zip-file "fileb://$BUILD/handler.zip" --timeout 30 \
  --environment "Variables=$LAMBDA_ENV" >/dev/null
rm -rf "$BUILD"

echo "== Event source mapping (batch_size 1: one bad message fails alone, section 25.1)"
# Drop existing mappings first: re-running otherwise stacks up pollers that each deliver
# the same message to a separate container.
for UUID in $($AWS lambda list-event-source-mappings --function-name "$INFERENCE_FN" \
  --query 'EventSourceMappings[].UUID' --output text); do
  $AWS lambda delete-event-source-mapping --uuid "$UUID" >/dev/null 2>&1 || true
done
$AWS lambda create-event-source-mapping --function-name "$INFERENCE_FN" \
  --event-source-arn "$QUEUE_ARN" --batch-size 1 >/dev/null

echo "== API Gateway (REST v1: API keys and usage plans are v1-only, section 30.1)"
API_ID=$($AWS apigateway get-rest-apis --query "items[?name=='complaints-api'].id | [0]" --output text)
if [ "$API_ID" = "None" ] || [ -z "$API_ID" ]; then
  API_ID=$($AWS apigateway create-rest-api --name complaints-api --query id --output text)
fi
ROOT_ID=$($AWS apigateway get-resources --rest-api-id "$API_ID" \
  --query 'items[?path==`/`].id | [0]' --output text)
ACCOUNT_ID=$($AWS sts get-caller-identity --query Account --output text)
URI="arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:$ACCOUNT_ID:function:$API_FN/invocations"

COMPLAINTS_ID=$($AWS apigateway get-resources --rest-api-id "$API_ID" \
  --query 'items[?pathPart==`complaints`].id | [0]' --output text)
if [ "$COMPLAINTS_ID" = "None" ] || [ -z "$COMPLAINTS_ID" ]; then
  COMPLAINTS_ID=$($AWS apigateway create-resource --rest-api-id "$API_ID" \
    --parent-id "$ROOT_ID" --path-part complaints --query id --output text)
fi
ID_RES=$($AWS apigateway get-resources --rest-api-id "$API_ID" \
  --query 'items[?pathPart==`{complaint_id}`].id | [0]' --output text)
if [ "$ID_RES" = "None" ] || [ -z "$ID_RES" ]; then
  ID_RES=$($AWS apigateway create-resource --rest-api-id "$API_ID" \
    --parent-id "$COMPLAINTS_ID" --path-part '{complaint_id}' --query id --output text)
fi

for pair in "POST:$COMPLAINTS_ID" "GET:$ID_RES"; do
  METHOD=${pair%%:*}
  RES=${pair##*:}
  $AWS apigateway put-method --rest-api-id "$API_ID" --resource-id "$RES" \
    --http-method "$METHOD" --authorization-type NONE >/dev/null 2>&1 || true
  # AWS_PROXY passes the raw request through, which is what handler() parses.
  $AWS apigateway put-integration --rest-api-id "$API_ID" --resource-id "$RES" \
    --http-method "$METHOD" --type AWS_PROXY --integration-http-method POST \
    --uri "$URI" >/dev/null 2>&1 || true
done

$AWS apigateway create-deployment --rest-api-id "$API_ID" --stage-name prod >/dev/null

API="http://localhost:4566/restapis/$API_ID/prod/_user_request_"
cat <<EOF

Ready.
  bucket     $BUCKET
  queue      $QUEUE_URL
  dlq        $DLQ_URL
  table      $TABLE
  image      $IMAGE
  API        $API

  export API="$API"
EOF
