#!/usr/bin/env bash
# RoofSpan AWS deploy-prep — safe local Terraform PLAN runner. NEVER applies.
#   fmt -check -> init (remote state) -> validate -> plan -out=tfplan -> tfplan.txt summary.
# Requires terraform.tfvars filled with real (non-secret) infra values and image digests.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"   # infra/aws
cd "$STACK_DIR"

TFVARS="${TFVARS:-terraform.tfvars}"
[ -f "$TFVARS" ] || { echo "ERROR: $TFVARS not found. Copy terraform.tfvars.example and fill it in." >&2; exit 1; }

# --- Identity + region ---
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
[ -n "$region" ] || { echo "ERROR: AWS_REGION not set." >&2; exit 1; }
account_id="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" \
  || { echo "ERROR: not authenticated." >&2; exit 1; }
EXPECTED_ACCOUNT_ID="${EXPECTED_ACCOUNT_ID:-391722048303}"
[ "$account_id" = "$EXPECTED_ACCOUNT_ID" ] \
  || { echo "ERROR: account $account_id != expected $EXPECTED_ACCOUNT_ID." >&2; exit 1; }

# --- Extract key tfvars values for the confirmation banner (read-only) ---
getvar() { grep -E "^[[:space:]]*$1[[:space:]]*=" "$TFVARS" | head -n1 | cut -d'=' -f2- | tr -d ' "'; }
tf_region="$(getvar aws_region)"
tf_dns="$(getvar dns_provider)"
tf_zone="$(getvar route53_zone_id)"
tf_env="$(getvar environment)"
tf_cp_img="$(getvar control_plane_image)"
tf_relay_img="$(getvar relay_image)"
tf_dns="${tf_dns:-external}"

echo "======================================================================"
echo " RoofSpan Terraform PLAN — review BEFORE continuing (no apply)"
echo "======================================================================"
echo "  AWS account (live)   : $account_id"
echo "  AWS region (shell)   : $region"
echo "  tfvars aws_region    : ${tf_region:-<unset>}"
echo "  tfvars dns_provider  : ${tf_dns}"
echo "  tfvars route53_zone  : ${tf_zone:-<empty — external DNS>}"
echo "  tfvars environment   : ${tf_env:-<unset>}"
echo "  control_plane_image  : ${tf_cp_img:-<unset>}"
echo "  relay_image          : ${tf_relay_img:-<unset>}"
echo "----------------------------------------------------------------------"

# --- Guardrails on inputs ---
[ -n "$tf_region" ] || { echo "ERROR: aws_region not set in $TFVARS." >&2; exit 1; }
if [ "$tf_region" != "$region" ]; then
  echo "ERROR: shell AWS_REGION ($region) != tfvars aws_region ($tf_region). Reconcile before planning." >&2
  exit 1
fi
if [ "$tf_dns" = "route53" ]; then
  case "${tf_zone:-}" in
    ""|REQUIRED*|Z_PENDING*|CHANGE*)
      echo "ERROR: dns_provider=route53 but route53_zone_id is not a real hosted-zone id." >&2
      exit 1 ;;
  esac
else
  echo "  DNS mode = external (GoDaddy): route53_zone_id not required; Terraform creates NO DNS records."
  echo "            After apply, add the records from: terraform output acm_validation_records"
  echo "            and: terraform output external_dns_endpoint_records"
fi
case "${tf_cp_img:-}${tf_relay_img:-}" in
  *REPLACE*|*"@sha256:REPLACE"*|"")
    echo "ERROR: image references still contain placeholders. Run build-push-images.sh and paste digests." >&2
    exit 1 ;;
esac

echo "Security reminders — confirm the plan shows:"
echo "  * RDS + Valkey PRIVATE (no public endpoint); ECS tasks assign_public_ip = false"
echo "  * ONLY the ALB is public; cp/relay host routing correct"
echo "  * KMS entitlement key scoped to the CP signer; Relay has NO kms:Sign on it"
echo "  * secrets referenced via Secrets Manager (no plaintext secrets in the plan)"
echo "  * NO changes to downloads.roofspan.io / roofspan-downloads-prod"
echo "  * no customer business database in AWS"
echo
read -r -p "Type EXACTLY 'plan' to run fmt/init/validate/plan (NO apply): " confirm
[ "$confirm" = "plan" ] || { echo "Aborted."; exit 1; }

# --- Remote state backend (bootstrapped separately; see REMOTE_STATE.md) ---
if [ -n "${TF_STATE_BUCKET:-}" ]; then
  TF_STATE_KEY="${TF_STATE_KEY:-control-plane-relay/terraform.tfstate}"
  echo "== terraform init (S3 backend s3://$TF_STATE_BUCKET/$TF_STATE_KEY) =="
  terraform init -reconfigure \
    -backend-config="bucket=$TF_STATE_BUCKET" \
    -backend-config="key=$TF_STATE_KEY" \
    -backend-config="region=$region" \
    -backend-config="use_lockfile=true" \
    -backend-config="encrypt=true"
elif [ "${PLAN_LOCAL_STATE:-0}" = "1" ]; then
  echo "== terraform init (LOCAL state — dry preview only; NOT for apply) =="
  terraform init -reconfigure
else
  echo "ERROR: remote state not configured. Export TF_STATE_BUCKET (see REMOTE_STATE.md)," >&2
  echo "       or set PLAN_LOCAL_STATE=1 for a throwaway local-state PREVIEW plan." >&2
  exit 1
fi

echo "== terraform fmt -check =="
terraform fmt -check -recursive

echo "== terraform validate =="
terraform validate

echo "== terraform plan (saved to ./tfplan) =="
terraform plan -input=false -var-file="$TFVARS" -out=tfplan

echo "== human-readable summary -> ./tfplan.txt =="
terraform show -no-color tfplan > tfplan.txt
echo
echo "PLAN COMPLETE. Review:"
echo "  - binary plan : $STACK_DIR/tfplan"
echo "  - readable     : $STACK_DIR/tfplan.txt"
echo "Both are git-ignored. NOTHING was applied. To deploy, a human runs 'terraform apply tfplan' after review."
