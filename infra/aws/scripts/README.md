# RoofSpan AWS Deployment Prep — Local-Run Scripts

Local-run tooling to build/push the RoofSpan **Control Plane** and **Secure Relay** container images and
produce a **reviewable `terraform plan`** for the AWS Control-Plane + Relay stack (`infra/aws`).

> **These scripts do NOT deploy.** The only script that can `apply` is `bootstrap-ecr.sh` (Stage A), and
> it is narrowly `-target`'d to ECR + its KMS key and requires an explicit typed confirmation. There is
> **no automatic `terraform apply`** of the full stack anywhere. `downloads.roofspan.io` is never touched.

Run everything from an **AWS-authenticated developer/admin machine** (the Emergent container has no
`aws`/`docker`). PowerShell equivalents (`*.ps1`) are provided for Windows admins.

---

## Prerequisites
- **AWS CLI v2** (SSO or short-lived credentials — do **not** commit access keys)
- **Docker** (with `buildx`; daemon running)
- **Terraform ≥ 1.10** (for S3-native state locking) — the provider is pinned to AWS `~> 6.21`
- **Git**
- Set an explicit `AWS_PROFILE` (recommended) and an explicit `AWS_REGION`.

```bash
export AWS_PROFILE=roofspan-prod        # your SSO/named profile
export AWS_REGION=<intended-app-region> # explicit — see "Region" below
```

---

## Workflow (in order)

```bash
# 1. Verify tooling
infra/aws/scripts/check-prereqs.sh

# 2. Verify WHO + WHERE (identity must match account 391722048303; region us-east-2)
export AWS_PROFILE=roofspan-prod
export AWS_REGION=us-east-2
infra/aws/scripts/resolve-aws-context.sh

# 3. ONE-TIME remote-state bootstrap (creates the S3 state bucket; AWS CLI only, no Terraform)
infra/aws/scripts/bootstrap-remote-state.sh
export TF_STATE_BUCKET=roofspan-tfstate-391722048303-us-east-2

# 4. (Stage A) Create the ECR repos so images can be pushed  [applies ECR + KMS only]
infra/aws/scripts/bootstrap-ecr.sh

# 5. Build + push images (linux/amd64); prints immutable @sha256 digests
infra/aws/scripts/build-push-images.sh

# 6. Fill terraform.tfvars (copy from terraform.tfvars.example) with the @sha256 digests,
#    then run the safe PLAN (fmt -> init -> validate -> plan; NO apply)
infra/aws/scripts/terraform-plan.sh

# 7. External DNS (GoDaddy) is a two-stage apply — see "DNS" below. A human runs the applies.
```

Outputs: `infra/aws/tfplan` (binary) + `infra/aws/tfplan.txt` (readable). Both are git-ignored.
A human reviews and, only if approved, runs `terraform apply tfplan` manually.

---

## HUMAN REQUIRED real values (never invented)
Fill these into a local, git-ignored `infra/aws/terraform.tfvars` (copy `terraform.tfvars.example`):

| tfvars key            | Value / source                                                        |
|-----------------------|------------------------------------------------------------------------|
| `aws_region`          | **`us-east-2`** (LOCKED — app stack)                                    |
| `dns_provider`        | **`external`** (GoDaddy; Route53 optional)                             |
| `route53_zone_id`     | **Not required** in external mode (leave empty)                        |
| `control_plane_image` | `@sha256:` digest from `build-push-images.sh`                          |
| `relay_image`         | `@sha256:` digest from `build-push-images.sh`                          |
| `environment`         | `production` (locked)                                                   |
| `single_nat_gateway`  | `true` (locked initial)                                                |
| `rds_multi_az`        | `false` (locked initial)                                               |

Known: **AWS Account ID = `391722048303`** (scripts refuse to run against any other account).
Do **not** put secrets in tfvars — Stripe/RevenueCat/operator secrets go into Secrets Manager
out-of-band (see `RUNBOOK.md` §4).

---

## Region — LOCKED: us-east-2
The RoofSpan app stack region is **`us-east-2`** (`terraform.tfvars.example` sets `aws_region = "us-east-2"`).
The ALB's regional ACM cert is created in this region. **Do NOT infer us-east-1 from CloudFront** — the
`downloads.roofspan.io` certificate is in us-east-1 only because CloudFront requires it there; that is a
separate, untouched piece of infra. Set your shell `export AWS_REGION=us-east-2` to match.

---

## DNS — DECIDED: External (GoDaddy), Route53 optional
`roofspan.io` DNS stays at **GoDaddy**. The IaC now supports `dns_provider`:

- **`dns_provider = "external"` (DEFAULT)** — Terraform creates **no Route53 records** and **does not
  require** `route53_zone_id`. It still requests the regional ACM cert and **outputs** the exact records
  you add at GoDaddy.
- `dns_provider = "route53"` — legacy behavior; Terraform manages validation + A-alias records (requires
  `route53_zone_id`).

### External DNS = two-stage apply (because ACM must be ISSUED before the HTTPS listener)
The ALB HTTPS listener depends on an **issued** cert, and issuance needs the validation CNAME added at
GoDaddy. So for external DNS:

1. **Stage 1 — create the cert only:**
   ```bash
   terraform apply -target=aws_acm_certificate.main
   terraform output acm_validation_records          # add these CNAME(s) at GoDaddy
   ```
   Add the CNAME(s) at GoDaddy → wait until ACM reports the cert **ISSUED**.
2. **Stage 2 — full apply:** `terraform apply` (the validation resource confirms ISSUED quickly, then the
   ALB + services come up).
3. **Endpoint records:** after the ALB exists,
   ```bash
   terraform output external_dns_endpoint_records   # add cp/relay CNAMEs -> ALB at GoDaddy
   ```
   Add `cp.roofspan.io` and `relay.roofspan.io` as **CNAME → the ALB DNS name** at GoDaddy.

> All of the above are **HUMAN REQUIRED** DNS actions surfaced by Terraform outputs. Terraform never
> writes to GoDaddy. `terraform-plan.sh` does **not** require `route53_zone_id` in external mode.
> `downloads.roofspan.io` / `roofspan-downloads-prod` are **not** part of this stack and are never touched.

---

## ECR ↔ ECS sequencing (analysis)
The ECS task definitions reference the images as **plain variables** (`var.control_plane_image` /
`var.relay_image`). Terraform does **not** verify image existence at plan or apply, so there is **no hard
Terraform chicken-and-egg** — a full `plan` runs even before any image is pushed.

The only real ordering is: you can't **push** until the ECR repos exist, and the repos are created by this
same stack. Clean two-stage flow (no code change, no fake digests):

1. **Stage A** — `bootstrap-ecr.sh`: `terraform apply -target` the two ECR repos + their KMS key only.
2. Build + push images → capture `@sha256` digests.
3. **Stage B** — full `terraform-plan.sh` with real digests in `terraform.tfvars` → review → human `apply`.

(You *may* run a full preview plan before pushing by putting any digest in tfvars, but the faithful plan
uses the real pushed digests after Stage A.)

---

## Container architecture (decided)
ECS Fargate task definitions now **explicitly** pin `runtime_platform { operating_system_family = "LINUX",
cpu_architecture = "X86_64" }` (this matches Fargate's implicit default — no behavior change, just made
safe against ARM/Apple-Silicon build machines). Build scripts therefore build **`--platform linux/amd64`**.

---

## Terraform remote state — proposed (NOT created yet)
Bootstrapped **separately** — see `../REMOTE_STATE.md`. Nothing is created until you explicitly approve.

**Locking mechanism (verified):** Terraform in use is **v1.10.5**, which supports **S3-native state
locking** (`use_lockfile = true`) — **no DynamoDB table required**. (DynamoDB locking is only needed on
Terraform < 1.10.)

**Proposed names for account `391722048303` / region `us-east-2` (approve before creating):**
- S3 state bucket: **`roofspan-tfstate-391722048303-us-east-2`** (versioning ON, SSE-KMS, Block Public
  Access ON)
- State key: **`control-plane-relay/terraform.tfstate`**
- Lock: **S3 native lockfile** (`use_lockfile=true`) — no DynamoDB
- KMS: a dedicated CMK for state encryption (or SSE-S3 if you prefer) — your call at bootstrap

Do **not** reuse the downloads bucket. Export before Stage A / the plan runner:
```bash
export TF_STATE_BUCKET=roofspan-tfstate-391722048303-us-east-2
# export TF_STATE_KEY=control-plane-relay/terraform.tfstate   # optional; this is the default
```

---

## Security review reminders (verify in `tfplan.txt`)
- RDS **private**, Valkey **private** (no public endpoints)
- ECS tasks `assign_public_ip = false`; **only the ALB** is public
- `cp.roofspan.io` / `relay.roofspan.io` host routing correct
- KMS entitlement-signing key scoped to the **CP signer**; **Relay has no `kms:Sign`** on it
- Secrets referenced via **Secrets Manager** (no plaintext secrets in the plan)
- **No** changes to `downloads.roofspan.io` / `roofspan-downloads-prod`
- **No** customer business database in AWS (CP DB holds commercial metadata only)
