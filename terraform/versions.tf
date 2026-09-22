terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Local backend, gitignored (section 38.5). Back up terraform.tfstate before risky
  # changes: losing it orphans billable resources that destroy can no longer see.
}

provider "aws" {
  region = var.region

  # Every resource carries the tag, so Cost Explorer can filter this project out of
  # shared services (section 42).
  default_tags {
    tags = {
      Project = var.project
    }
  }
}

data "aws_caller_identity" "current" {}
