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
#   encryption   = SSE-S3 (AES256) by DEFAULT; SSE-KMS only if STATE_KMS_KEY_ID is set (optional future)
#   ownership    = Bucket Owner Enforced (ACLs disabled)
#   public access= fully blocked
#
# Idempotent: safe to re-run; skips creation if the bucket already exists in this account.
set -euo pipefail

EXPECTED_ACCOUNT_ID="${EXPECTED_ACCOUNT_ID:-391722048303}"
REGION="${AWS_REGION:-us-east-2}"
BUCKET="${TF_STATE_BUCKET:-roofspan-tfstate-${EXPECTED_ACCOUNT_ID}-${REGION}}"
# OPTIONAL future enhancement: set STATE_KMS_KEY_ID to use a customer-managed CMK instead of SSE-S3.
# Not required for the initial RoofSpan deployment — leave empty for SSE-S3 (AES256).
STATE_KMS_KEY_ID="${STATE_KMS_KEY_ID:-}"

echo "== RoofSpan remote-state bootstrap =="
echo "  Bucket : $BUCKET"
echo "  Region : $REGION"
echo "  Locking: S3-native (use_lockfile=true) — no DynamoDB"
echo "  Encrypt: $([ -n "$STATE_KMS_KEY_ID" ] && echo "SSE-KMS ($STATE_KMS_KEY_ID)" || echo "SSE-S3 (AES256, default)")"

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

# --- Ownership: Bucket Owner Enforced (ACLs disabled) ---
aws s3api put-bucket-ownership-controls --bucket "$BUCKET" \
  --ownership-controls 'Rules=[{ObjectOwnership=BucketOwnerEnforced}]'
echo "  Ownership: BucketOwnerEnforced (ACLs disabled)"

# --- Encryption: SSE-S3 (AES256) by default; SSE-KMS only if STATE_KMS_KEY_ID is set ---
if [ -n "$STATE_KMS_KEY_ID" ]; then
  aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration "{
    \"Rules\":[{\"ApplyServerSideEncryptionByDefault\":{\"SSEAlgorithm\":\"aws:kms\",\"KMSMasterKeyID\":\"$STATE_KMS_KEY_ID\"},\"BucketKeyEnabled\":true}]}"
  echo "  Encryption: SSE-KMS (customer-managed)"
else
  aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'
  echo "  Encryption: SSE-S3 (AES256)"
fi

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
