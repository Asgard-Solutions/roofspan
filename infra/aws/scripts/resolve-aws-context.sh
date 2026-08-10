#!/usr/bin/env bash
# RoofSpan AWS deploy-prep — verify WHO and WHERE before anything else. Read-only.
# - Prints the authenticated AWS identity (aws sts get-caller-identity).
# - Requires the account to match the expected RoofSpan production account.
# - Requires an EXPLICIT region (AWS_REGION); never silently defaults to us-east-1.
# - Read-only Route53 helper to look for an existing roofspan.io hosted zone.
# No resources are created or modified.
set -euo pipefail

# Expected RoofSpan production account (supplied by the RoofSpan owner). Override via env if needed.
EXPECTED_ACCOUNT_ID="${EXPECTED_ACCOUNT_ID:-391722048303}"

echo "== RoofSpan deploy-prep: AWS context =="
if [ -n "${AWS_PROFILE:-}" ]; then
  echo "  Using AWS_PROFILE=${AWS_PROFILE}"
else
  echo "  AWS_PROFILE not set — using ambient credentials/SSO session (verify below)."
fi

# --- Identity (fail fast if not authenticated) ---
ident_json="$(aws sts get-caller-identity --output json 2>/dev/null)" || {
  echo "ERROR: not authenticated. Run 'aws sso login' or configure a profile, then retry." >&2
  exit 1
}
account_id="$(echo "$ident_json" | grep -o '"Account": *"[0-9]*"' | grep -o '[0-9]*')"
arn="$(echo "$ident_json" | grep -o '"Arn": *"[^"]*"' | cut -d'"' -f4)"
echo "  Identity ARN : ${arn}"
echo "  Account ID   : ${account_id}"

if [ "$account_id" != "$EXPECTED_ACCOUNT_ID" ]; then
  echo "ERROR: authenticated account (${account_id}) != expected RoofSpan account (${EXPECTED_ACCOUNT_ID})." >&2
  echo "       Refusing to proceed against an unexpected account. Fix credentials/profile and retry." >&2
  exit 1
fi
echo "  Account MATCHES expected RoofSpan account."

# --- Region (must be explicit) ---
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
if [ -z "$region" ]; then
  region="$(aws configure get region 2>/dev/null || true)"
  if [ -n "$region" ]; then
    echo "  NOTE: AWS_REGION not set; AWS CLI is configured for region '${region}'."
    echo "        This is shown for convenience ONLY. Export AWS_REGION to confirm the intended"
    echo "        RoofSpan PRODUCTION region (do NOT infer it from the downloads bucket)."
  fi
fi
if [ -z "$region" ]; then
  echo "ERROR: no region. Set AWS_REGION explicitly (e.g. export AWS_REGION=us-east-2)." >&2
  exit 1
fi
echo "  Region       : ${region}   <-- confirm this is the intended RoofSpan app region"
echo "  Reminder     : downloads.roofspan.io lives in us-east-2 (S3 roofspan-downloads-prod)."
echo "                 The app stack region is a SEPARATE decision — do not assume they match."

# --- Route53 read-only lookup for roofspan.io (informational) ---
echo
echo "== Route53 (read-only): look for an existing roofspan.io hosted zone =="
zones="$(aws route53 list-hosted-zones-by-name --dns-name roofspan.io. --max-items 5 --output json 2>/dev/null || true)"
if [ -z "$zones" ] || ! echo "$zones" | grep -q '"roofspan.io.'; then
  echo "  No Route53 hosted zone found for roofspan.io in this account."
  echo "  (Expected: roofspan.io is currently managed at GoDaddy — see DNS DECISION in scripts/README.md.)"
else
  echo "$zones" | grep -E '"Id"|"Name"' | sed 's/^/    /'
  echo "  If a hosted zone exists, copy its /hostedzone/ID (the trailing ID) into terraform.tfvars"
  echo "  as route53_zone_id — but ONLY after the DNS strategy is approved (see README)."
fi
echo "  This script did NOT create or modify any DNS/zone."

echo
echo "Context OK. Export for downstream scripts if not already:"
echo "  export AWS_REGION=${region}"
