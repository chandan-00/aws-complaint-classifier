# Two near-mirror roles (section 40): the API tier writes S3 and reads DynamoDB, the
# inference tier reads S3 and writes DynamoDB. Neither can do the other's job.
#
# No statement needs Resource "*": log groups are created by Terraform (lambda.tf), so
# neither role needs logs:CreateLogGroup.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api" {
  name               = "complaint-api-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role" "inference" {
  name               = "complaint-inference-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "WriteComplaintPayloads"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.complaints.arn}/complaints/*"]
  }

  statement {
    sid       = "QueueForInference"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.complaints.arn]
  }

  statement {
    sid       = "ReadPredictions"
    actions   = ["dynamodb:GetItem"]
    resources = [aws_dynamodb_table.predictions.arn]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }
}

data "aws_iam_policy_document" "inference" {
  statement {
    sid       = "ReadComplaintPayloads"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.complaints.arn}/complaints/*"]
  }

  statement {
    sid       = "WritePredictions"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.predictions.arn]
  }

  statement {
    sid = "ConsumeQueue"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.complaints.arn]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.inference.arn}:*"]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "complaint-api"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_iam_role_policy" "inference" {
  name   = "complaint-inference"
  role   = aws_iam_role.inference.id
  policy = data.aws_iam_policy_document.inference.json
}
