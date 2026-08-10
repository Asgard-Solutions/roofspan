#!/usr/bin/env bash
# RoofSpan AWS deploy-prep — build, tag, push CP + Relay images to ECR; print immutable digests.
#
# Prerequisites:
#   - Prerequisites verified:      scripts/check-prereqs.sh
#   - AWS identity/region verified: scripts/resolve-aws-context.sh   (export AWS_REGION first)
#   - ECR repositories EXIST. They are created by the Terraform stack (ecr.tf, IMMUTABLE tags).
#     If they do not exist yet, run the ECR bootstrap first: scripts/bootstrap-ecr.sh  (Stage A).
#     This script will NOT create ECR repos — Terraform is the single authority for ECR config.
#
# Architecture: images are built for linux/amd64 (X86_64) to match the ECS task runtime_platform.
# Run from anywhere; the script resolves the repo root itself. Nothing is applied to Terraform here.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"   # infra/aws/scripts -> repo root
PLATFORM="linux/amd64"
TAG="${IMAGE_TAG:-$(cd "$REPO_ROOT" && git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"

CP_DOCKERFILE="$REPO_ROOT/infra/docker/control-plane/Dockerfile"
RELAY_DOCKERFILE="$REPO_ROOT/infra/docker/relay/Dockerfile"

echo "== RoofSpan deploy-prep: build + push images =="
echo "  Repo root  : $REPO_ROOT"
echo "  Platform   : $PLATFORM (must match ECS runtime_platform X86_64)"
echo "  Image tag  : $TAG"

# --- Fail fast if source/Dockerfiles are missing ---
for f in "$CP_DOCKERFILE" "$RELAY_DOCKERFILE" "$REPO_ROOT/backend/requirements.txt"; do
  [ -f "$f" ] || { echo "ERROR: expected file missing: $f" >&2; exit 1; }
done

# --- Identity + region (explicit) ---
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
[ -n "$region" ] || { echo "ERROR: AWS_REGION not set. Export it, e.g. export AWS_REGION=us-east-2." >&2; exit 1; }
account_id="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" || {
  echo "ERROR: not authenticated (aws sts get-caller-identity failed)." >&2; exit 1; }
EXPECTED_ACCOUNT_ID="${EXPECTED_ACCOUNT_ID:-391722048303}"
[ "$account_id" = "$EXPECTED_ACCOUNT_ID" ] || {
  echo "ERROR: account $account_id != expected $EXPECTED_ACCOUNT_ID. Refusing to push." >&2; exit 1; }

registry="${account_id}.dkr.ecr.${region}.amazonaws.com"
echo "  Account    : $account_id"
echo "  Region     : $region"
echo "  Registry   : $registry"

# --- Verify ECR repos EXIST (do NOT create — Terraform owns them) ---
for repo in roofspan-control-plane roofspan-relay; do
  if ! aws ecr describe-repositories --repository-names "$repo" --region "$region" >/dev/null 2>&1; then
    cat >&2 <<EOF
ERROR: ECR repository '$repo' does not exist in $region.
       Terraform (infra/aws/ecr.tf) is the authority for ECR. Create the repos first via Stage A:
         infra/aws/scripts/bootstrap-ecr.sh
       Then re-run this script. This script will NOT create repositories.
EOF
    exit 1
  fi
done
echo "  ECR repos  : both exist."

# --- Docker login to ECR ---
echo "== Docker login to ECR =="
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"

build_push() {
  local name="$1" dockerfile="$2"
  local ref="${registry}/${name}:${TAG}"
  echo
  echo "== Build $name =="
  # Build context is the repo root so 'COPY backend ...' resolves; force amd64 for Fargate.
  docker buildx build --platform "$PLATFORM" --load -f "$dockerfile" -t "$ref" "$REPO_ROOT"
  echo "== Push $name =="
  docker push "$ref"
  # Resolve the immutable digest from the registry (authoritative).
  local digest
  digest="$(aws ecr describe-images --repository-name "$name" --region "$region" \
            --image-ids imageTag="$TAG" --query 'imageDetails[0].imageDigest' --output text)"
  echo "${registry}/${name}@${digest}"
}

CP_REF="$(build_push roofspan-control-plane "$CP_DOCKERFILE")"
RELAY_REF="$(build_push roofspan-relay "$RELAY_DOCKERFILE")"

cat <<EOF

======================================================================
 IMMUTABLE IMAGE REFERENCES — paste these into infra/aws/terraform.tfvars
======================================================================
control_plane_image = "${CP_REF}"
relay_image         = "${RELAY_REF}"
======================================================================
Do NOT use mutable ':${TAG}' or ':latest' as the Terraform deployment reference.
Then run: infra/aws/scripts/terraform-plan.sh
EOF
