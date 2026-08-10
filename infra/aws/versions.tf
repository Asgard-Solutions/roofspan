terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
  # Remote state is HUMAN REQUIRED bootstrap — see REMOTE_STATE.md. Do NOT auto-create the backend.
  # backend "s3" { ... }  # configured via `terraform init -backend-config=...` after bootstrap.
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "RoofSpan"
      Component   = "control-plane-and-relay"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
