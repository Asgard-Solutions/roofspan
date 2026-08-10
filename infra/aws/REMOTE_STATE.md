# Terraform Remote State — HUMAN REQUIRED bootstrap (not auto-created)

This stack does **not** create its own state backend automatically. Bootstrap it once, separately, before
`terraform init` of the main stack. Do **not** reuse the `downloads.roofspan.io` bucket for state.

## Recommended
- Dedicated **S3 bucket** `roofspan-tfstate-<account>-<region>` (versioning ON, SSE-KMS, Block Public
  Access ON).
- **State locking**: Terraform's native **S3 lockfile** (`use_lockfile = true`, Terraform ≥ 1.10) — no
  DynamoDB table required. (If on older Terraform, use a DynamoDB lock table instead.)

## One-time bootstrap (human, with real credentials)
1. Create the bucket (versioning + SSE-KMS + BPA) in the production account/region.
2. Configure the backend:
   ```
   terraform init -backend-config="bucket=roofspan-tfstate-<acct>-<region>" \
                  -backend-config="key=control-plane-relay/terraform.tfstate" \
                  -backend-config="region=<region>" \
                  -backend-config="use_lockfile=true" \
                  -backend-config="encrypt=true"
   ```
3. Uncomment the `backend "s3" {}` block in `versions.tf`.

**HUMAN REQUIRED**: bucket name/region, KMS key for state encryption, and explicit approval before
creating the state bucket.
