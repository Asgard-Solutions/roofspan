#!/usr/bin/env bash
# RoofSpan AWS deploy-prep — ONE-TIME Terraform remote-state bootstrap (creates the S3 state bucket).
#
# This is the ONLY resource created OUTSIDE the main Terraform stack (Terraform can't store its own state
# bucket in its own state). It uses the AWS CLI directly (no Terraform). Run ONCE per account/region.
#
# Approved design (locked):
#   bucket       = roofspan-tfstate-391722048303-us-east-2
#   key          = control-plane-relay/terraform.tfstate   (used later by init, not created here)
#   region       = us-east-2
#   locking      = S3-native use_lockfile=true              (NO DynamoDB table)
#   versioning   = ON
#   encryption   = SSE-KMS (aws/s3 managed key by default; override with STATE_KMS_KEY_ID)
#   public access= fully blocked
#
# Idempotent: safe to re-run; skips creation if the bucket already exists in this account.
set -euo pipefail

EXPECTED_ACCOUNT_ID="${EXPECTED_ACCOUNT_ID:-391722048303}"
REGION="${AWS_REGION:-us-east-2}"
BUCKET="${TF_STATE_BUCKET:-roofspan-tfstate-${EXPECTED_ACCOUNT_ID}-${REGION}}"
# Optional customer-managed KMS key for state encryption. Empty = SSE-KMS with the aws/s3 managed key.
STATE_KMS_KEY_ID="${STATE_KMS_KEY_ID:-}"

echo "== RoofSpan remote-state bootstrap =="
echo "  Bucket : $BUCKET"
echo "  Region : $REGION"
echo "  Locking: S3-native (use_lockfile=true) — no DynamoDB"
echo "  Encrypt: $([ -n "$STATE_KMS_KEY_ID" ] && echo "SSE-KMS ($STATE_KMS_KEY_ID)" || echo "SSE-KMS (aws/s3 managed)")"

# --- Identity guard ---
account_id="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" \
  || { echo "ERROR: not authenticated." >&2; exit 1; }
[ "$account_id" = "$EXPECTED_ACCOUNT_ID" ] \
  || { echo "ERROR: account $account_id != expected $EXPECTED_ACCOUNT_ID. Refusing." >&2; exit 1; }

echo
read -r -p "Type EXACTLY 'bootstrap-state' to CREATE the state bucket in $account_id/$REGION: " confirm
[ "$confirm" = "bootstrap-state" ] || { echo "Aborted."; exit 1; }

# --- Create bucket (idempotent) ---
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "  Bucket already exists — skipping create."
else
  # us-east-1 must NOT pass a LocationConstraint; every other region must.
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
  echo "  Bucket created."
fi

# --- Versioning ON ---
aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled
echo "  Versioning: Enabled"

# --- Encryption (SSE-KMS) ---
if [ -n "$STATE_KMS_KEY_ID" ]; then
  aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration "{
    \"Rules\":[{\"ApplyServerSideEncryptionByDefault\":{\"SSEAlgorithm\":\"aws:kms\",\"KMSMasterKeyID\":\"$STATE_KMS_KEY_ID\"},\"BucketKeyEnabled\":true}]}"
else
  aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"},"BucketKeyEnabled":true}]}'
fi
echo "  Encryption: SSE-KMS"

# --- Block all public access ---
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
echo "  Public access: fully blocked"

cat <<EOF

State bucket ready. Export for the plan / ECR-bootstrap scripts:
  export TF_STATE_BUCKET=$BUCKET
  # export TF_STATE_KEY=control-plane-relay/terraform.tfstate   # default

Next: infra/aws/scripts/bootstrap-ecr.sh   (Stage A: create ECR repos)
EOF
