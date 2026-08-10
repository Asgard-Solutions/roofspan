#!/usr/bin/env bash
# RoofSpan AWS deploy-prep — Stage A ECR bootstrap ONLY (create ECR repos + their KMS dependency).
#
# WHY THIS EXISTS (sequencing):
#   The ECR repositories are defined in the SAME Terraform stack that also defines the ECS services
#   which reference the image digests. Terraform does NOT validate image existence at plan/apply, so
#   there is no hard Terraform chicken-and-egg. But you cannot PUSH images until the repos exist.
#   Clean two-stage flow:
#     Stage A (this script): apply ONLY the ECR repos (+ the KMS 'general' key they encrypt with).
#     -> build + push images (scripts/build-push-images.sh) -> capture digests
#     Stage B: full plan/apply with real digests in terraform.tfvars (scripts/terraform-plan.sh, then human apply).
#
# This is the ONLY script here that can APPLY, and it is narrowly -target'd to ECR + KMS.
# It requires an explicit typed confirmation and a properly configured remote state backend.
# It does NOT touch DNS, ECS, RDS, Valkey, ALB, Cognito, or downloads.roofspan.io.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"   # infra/aws
cd "$STACK_DIR"

region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
[ -n "$region" ] || { echo "ERROR: AWS_REGION not set." >&2; exit 1; }
account_id="$(aws sts get-caller-identity --query Account --output text)"
EXPECTED_ACCOUNT_ID="${EXPECTED_ACCOUNT_ID:-391722048303}"
[ "$account_id" = "$EXPECTED_ACCOUNT_ID" ] || { echo "ERROR: account $account_id != $EXPECTED_ACCOUNT_ID." >&2; exit 1; }

if [ -z "${TF_STATE_BUCKET:-}" ]; then
  echo "ERROR: remote state not configured. Bootstrap state first (see REMOTE_STATE.md) and export:" >&2
  echo "       TF_STATE_BUCKET, and optionally TF_STATE_KEY (default control-plane-relay/terraform.tfstate)." >&2
  exit 1
fi
TF_STATE_KEY="${TF_STATE_KEY:-control-plane-relay/terraform.tfstate}"

echo "== Stage A: ECR bootstrap =="
echo "  Account : $account_id"
echo "  Region  : $region"
echo "  State   : s3://$TF_STATE_BUCKET/$TF_STATE_KEY (use_lockfile)"
echo "  Targets : aws_kms_key.general, aws_ecr_repository.control_plane, aws_ecr_repository.relay"
echo "            (+ their lifecycle policies)"
echo
read -r -p "Type EXACTLY 'apply-ecr' to create ONLY these resources: " confirm
[ "$confirm" = "apply-ecr" ] || { echo "Aborted."; exit 1; }

terraform init -reconfigure \
  -backend-config="bucket=$TF_STATE_BUCKET" \
  -backend-config="key=$TF_STATE_KEY" \
  -backend-config="region=$region" \
  -backend-config="use_lockfile=true" \
  -backend-config="encrypt=true"

terraform apply \
  -target=aws_kms_key.general \
  -target=aws_ecr_repository.control_plane \
  -target=aws_ecr_repository.relay \
  -target=aws_ecr_lifecycle_policy.cp \
  -target=aws_ecr_lifecycle_policy.relay

echo
echo "Stage A complete. Now build + push images:"
echo "  infra/aws/scripts/build-push-images.sh"
