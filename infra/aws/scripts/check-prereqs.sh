#!/usr/bin/env bash
# RoofSpan AWS deploy-prep — verify local tooling. Read-only. No AWS calls, no Docker builds.
set -euo pipefail

echo "== RoofSpan deploy-prep: tooling check =="
fail=0

need() {
  local bin="$1" hint="$2"
  if command -v "$bin" >/dev/null 2>&1; then
    printf "  OK  %-10s %s\n" "$bin" "$($bin --version 2>&1 | head -n1)"
  else
    printf "  MISSING %-8s -> %s\n" "$bin" "$hint"
    fail=1
  fi
}

need aws       "Install AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
need docker    "Install Docker (with buildx) and start the daemon."
need terraform "Install Terraform >= 1.10 (S3 native state lock): https://developer.hashicorp.com/terraform/install"
need git       "Install Git."

# AWS CLI must be v2.
if command -v aws >/dev/null 2>&1; then
  if ! aws --version 2>&1 | grep -q "aws-cli/2"; then
    echo "  WARN aws-cli is not v2 (v2 required for SSO + modern ECR auth)."
    fail=1
  fi
fi

# Terraform >= 1.10 recommended for S3 native lockfile.
if command -v terraform >/dev/null 2>&1; then
  tfv="$(terraform version -json 2>/dev/null | grep -o '"terraform_version":"[0-9.]*"' | cut -d'"' -f4 || true)"
  echo "  Terraform version: ${tfv:-unknown} (>= 1.10 recommended for use_lockfile)"
fi

# Docker daemon reachable + buildx present (needed for --platform).
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    echo "  OK  docker daemon reachable"
  else
    echo "  WARN docker daemon not reachable (start Docker Desktop / dockerd)."
    fail=1
  fi
  if docker buildx version >/dev/null 2>&1; then
    echo "  OK  docker buildx present (required for --platform linux/amd64)"
  else
    echo "  WARN docker buildx missing (needed to force linux/amd64 on ARM machines)."
  fi
fi

echo
if [ "$fail" -ne 0 ]; then
  echo "RESULT: prerequisites INCOMPLETE — install/fix the items above before continuing."
  exit 1
fi
echo "RESULT: all prerequisites present."
