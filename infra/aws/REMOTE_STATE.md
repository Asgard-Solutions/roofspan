# Terraform Remote State — ONE-TIME bootstrap (approved design)

This stack stores its state in S3. The state bucket itself is created **once, outside** the main stack
(Terraform can't keep its own state bucket in its own state) via `scripts/bootstrap-remote-state.sh`
(AWS CLI only — no Terraform). Do **not** reuse the `downloads.roofspan.io` bucket.

## Approved (locked) design
| Setting      | Value                                                        |
|--------------|--------------------------------------------------------------|
| bucket       | `roofspan-tfstate-391722048303-us-east-2`                    |
| key          | `control-plane-relay/terraform.tfstate`                      |
| region       | `us-east-2`                                                  |
| locking      | **S3-native `use_lockfile=true`** (NO DynamoDB table)        |
| versioning   | ON                                                           |
| encryption   | **SSE-S3 (AES256)** by default; SSE-KMS optional (future)    |
| ownership    | **Bucket Owner Enforced** (ACLs disabled)                    |
| public access| fully blocked (all four BPA flags true)                      |

**Encryption:** SSE-S3 (AES256) is the default and is **not** required to use KMS. A customer-managed CMK
is an **optional future enhancement** — set `STATE_KMS_KEY_ID` before running the bootstrap to switch to
SSE-KMS. No dedicated KMS key is created for state.

**Locking mechanism confirmed:** Terraform ≥ 1.10 supports S3-native state locking (`use_lockfile=true`),
so **no DynamoDB lock table is required**. (Only use DynamoDB on Terraform < 1.10.)

## IAM (least privilege for the state backend)
The operator/CI principal running Terraform needs, at minimum, on the state bucket:
- `s3:ListBucket` on `arn:aws:s3:::roofspan-tfstate-391722048303-us-east-2`
- `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on
  `arn:aws:s3:::roofspan-tfstate-391722048303-us-east-2/control-plane-relay/*`
  (DeleteObject + the `.tflock` object handling are what S3-native locking uses)
No `kms:*` is needed while encryption is SSE-S3. Grant the wider RoofSpan-stack permissions (ECS, ECR,
RDS, ElastiCache, ALB, ACM, KMS for the entitlement key, Secrets Manager, Cognito, VPC) separately — keep
state access scoped to just this bucket/prefix.

## One-time bootstrap (human, AWS-authenticated)
```bash
export AWS_REGION=us-east-2
export AWS_PROFILE=<your-sso-profile>
infra/aws/scripts/bootstrap-remote-state.sh          # creates the bucket (idempotent, typed-confirm)
export TF_STATE_BUCKET=roofspan-tfstate-391722048303-us-east-2
```

`versions.tf` already contains a partial `backend "s3" {}` block. The bucket/key/region/lock are supplied
at init time (the ECR-bootstrap and plan scripts do this):
```
terraform init -reconfigure \
  -backend-config="bucket=roofspan-tfstate-391722048303-us-east-2" \
  -backend-config="key=control-plane-relay/terraform.tfstate" \
  -backend-config="region=us-east-2" \
  -backend-config="use_lockfile=true" \
  -backend-config="encrypt=true"
```

**HUMAN REQUIRED**: explicit approval to create the state bucket; optional customer-managed KMS key for
state encryption (`STATE_KMS_KEY_ID`).
