variable "region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "aws-complaint-classifier"
}

variable "bucket_name" {
  description = "Globally unique; reserved on Day 0 (section 4.9)."
  type        = string
  default     = "chandan-complaints-project"
}

variable "image_tag" {
  description = "Inference image tag in ECR, e.g. v3-int8. No default: every deploy names its image."
  type        = string
}

variable "inference_memory_mb" {
  description = "CPU scales with memory; below ~2048 ONNX inference crawls (section 28.1)."
  type        = number
  default     = 2048
}

variable "inference_timeout_s" {
  description = "SQS visibility is derived from this at 6x (section 25.1)."
  type        = number
  default     = 60
}

variable "log_retention_days" {
  type    = number
  default = 7
}
