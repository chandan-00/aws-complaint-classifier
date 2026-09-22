output "invoke_url" {
  description = "POST here; GET <invoke_url>/<complaint_id>. Send the key as x-api-key."
  value       = "${aws_api_gateway_stage.prod.invoke_url}/complaints"
}

output "api_key_id" {
  description = "aws apigateway get-api-key --api-key <id> --include-value"
  value       = aws_api_gateway_api_key.complaints.id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.inference.repository_url
}

output "bucket" {
  value = aws_s3_bucket.complaints.bucket
}

output "queue_url" {
  value = aws_sqs_queue.complaints.url
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "table_name" {
  value = aws_dynamodb_table.predictions.name
}

output "model_version" {
  value = local.model_version
}
