# Log groups are declared, not left to Lambda: an auto-created group is not in state, so
# destroy leaves it behind with never-expire retention (section 38.2). The names must
# match /aws/lambda/<function> exactly, or Lambda creates a second group alongside.
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/complaint-api"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "inference" {
  name              = "/aws/lambda/complaint-inference"
  retention_in_days = var.log_retention_days
}

locals {
  model_version = "distilbert-${var.image_tag}"
}

data "archive_file" "api" {
  type        = "zip"
  source_file = "${path.module}/../lambda/ingestion/handler.py"
  output_path = "${path.module}/.build/api.zip"
}

resource "aws_lambda_function" "api" {
  function_name    = "complaint-api"
  role             = aws_iam_role.api.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  timeout          = 10
  memory_size      = 256

  environment {
    variables = {
      BUCKET        = aws_s3_bucket.complaints.bucket
      QUEUE_URL     = aws_sqs_queue.complaints.url
      DDB_TABLE     = aws_dynamodb_table.predictions.name
      MODEL_VERSION = local.model_version
    }
  }

  depends_on = [aws_cloudwatch_log_group.api, aws_iam_role_policy.api]
}

resource "aws_lambda_function" "inference" {
  function_name = "complaint-inference"
  role          = aws_iam_role.inference.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.inference.repository_url}:${var.image_tag}"
  architectures = ["x86_64"] # the image is built linux/amd64 (section 11.1)
  timeout       = var.inference_timeout_s
  memory_size   = var.inference_memory_mb

  environment {
    variables = {
      BUCKET        = aws_s3_bucket.complaints.bucket
      DDB_TABLE     = aws_dynamodb_table.predictions.name
      MODEL_VERSION = local.model_version
    }
  }

  depends_on = [aws_cloudwatch_log_group.inference, aws_iam_role_policy.inference]
}

resource "aws_lambda_event_source_mapping" "inference" {
  event_source_arn = aws_sqs_queue.complaints.arn
  function_name    = aws_lambda_function.inference.arn

  # One message per invocation: a larger batch fails and redrives every message in it
  # when one is malformed (section 25.1). ReportBatchItemFailures is the production fix.
  batch_size = 1
}
