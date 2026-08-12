terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source = "hashicorp/aws"
      # v6.21.0+ adds aws_kms_key support for customer_master_key_spec = "ECC_NIST_EDWARDS25519"
      # (Ed25519 entitlement signing). Stack is v6-clean (domain="vpc", strict bools, no OpsWorks).
      version = "~> 6.21"
    }
  }
  # Remote state is HUMAN REQUIRED bootstrap — see REMOTE_STATE.md and scripts/bootstrap-remote-state.sh.
  # Partial config: the bucket/key/region/lock are supplied at `terraform init -backend-config=...`
  # (the plan/bootstrap scripts do this). S3-native locking (use_lockfile=true) — no DynamoDB table.
  backend "s3" {}
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
