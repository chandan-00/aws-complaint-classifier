resource "aws_s3_bucket" "complaints" {
  bucket = var.bucket_name

  # destroy otherwise fails on a non-empty bucket (section 38.2).
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "complaints" {
  bucket = aws_s3_bucket.complaints.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_sqs_queue" "dlq" {
  name                      = "complaint-dlq"
  message_retention_seconds = 1209600 # 14 days, the maximum: time to inspect failures
}

resource "aws_sqs_queue" "complaints" {
  name = "complaint-queue"

  # AWS rejects the event source mapping below 6x the function timeout, and a shorter
  # value redelivers messages that are still being processed (section 25.1).
  visibility_timeout_seconds = 6 * var.inference_timeout_s

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_dynamodb_table" "predictions" {
  name         = "ComplaintPredictions"
  hash_key     = "complaint_id"
  billing_mode = "PAY_PER_REQUEST" # provisioned capacity bills while idle

  attribute {
    name = "complaint_id"
    type = "S"
  }
}
