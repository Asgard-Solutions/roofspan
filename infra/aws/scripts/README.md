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

# 2. Verify WHO + WHERE (identity must match account 391722048303; region must be explicit)
infra/aws/scripts/resolve-aws-context.sh

# --- Resolve the DNS DECISION (see below) and remote state (REMOTE_STATE.md) before continuing ---

# 3. (Stage A) Create the ECR repos so images can be pushed  [this one can apply — ECR+KMS only]
export TF_STATE_BUCKET=<your-tfstate-bucket>
infra/aws/scripts/bootstrap-ecr.sh

# 4. Build + push images (linux/amd64); prints immutable @sha256 digests
infra/aws/scripts/build-push-images.sh

# 5. Fill terraform.tfvars (copy from terraform.tfvars.example) with region, zone, digests
#    then run the safe PLAN (fmt -> init -> validate -> plan; NO apply)
infra/aws/scripts/terraform-plan.sh
```

Outputs: `infra/aws/tfplan` (binary) + `infra/aws/tfplan.txt` (readable). Both are git-ignored.
A human reviews and, only if approved, runs `terraform apply tfplan` manually.

---

## HUMAN REQUIRED real values (never invented)
Fill these into a local, git-ignored `infra/aws/terraform.tfvars` (copy `terraform.tfvars.example`):

| tfvars key            | Value / source                                                        |
|-----------------------|------------------------------------------------------------------------|
| `aws_region`          | **Explicit** intended app region (see "Region")                        |
| `route53_zone_id`     | **BLOCKED — DNS DECISION REQUIRED** (roofspan.io is on GoDaddy)         |
| `control_plane_image` | `@sha256:` digest from `build-push-images.sh`                          |
| `relay_image`         | `@sha256:` digest from `build-push-images.sh`                          |
| `environment`         | `production` (locked)                                                   |
| `single_nat_gateway`  | `true` (locked initial)                                                |
| `rds_multi_az`        | `false` (locked initial)                                               |

Known: **AWS Account ID = `391722048303`** (scripts refuse to run against any other account).
Do **not** put secrets in tfvars — Stripe/RevenueCat/operator secrets go into Secrets Manager
out-of-band (see `RUNBOOK.md` §4).

---

## Region — reported for explicit approval
The Terraform source **does not assume any region**. `variables.tf` declares:

```hcl
variable "aws_region" {
  description = "Production AWS region ... HUMAN REQUIRED — do NOT default. ACM certs for the ALB are created in THIS region."
  # NO default; validation fails if empty.
}
```
and `versions.tf` sets `provider "aws" { region = var.aws_region }`.

**Consequence:** the ALB's ACM certificate is created in `aws_region`, so the app stack's region **is**
`aws_region` — pick it deliberately. The downloads bucket lives in **us-east-2**, but that is a *separate*
decision and **must not** be inferred as the app region. **ACTION: confirm the intended RoofSpan app
region and set `aws_region` accordingly.**

---

## ⛔ DNS DECISION REQUIRED (current blocker for a full plan)
`roofspan.io` is managed at **GoDaddy**, but the current IaC (`dns_acm.tf`) **hard-requires a Route53
hosted zone**: `route53_zone_id` is a required variable **and** the stack creates Route53 records for
(a) ACM DNS validation and (b) `cp.roofspan.io` / `relay.roofspan.io` A-aliases to the ALB.

You therefore **cannot** fill `route53_zone_id` or `apply` DNS as-is. This is a material decision — **no
code has been changed for it.** Options (pick one; do not migrate DNS without approval):

- **Option A — Migrate roofspan.io DNS to Route53.** Create a public hosted zone for `roofspan.io`,
  repoint GoDaddy nameservers to Route53. IaC then works unchanged. *Largest blast radius* — every
  roofspan.io record (including the `downloads.roofspan.io` alias) must be recreated in Route53 first.
- **Option B — Delegate a subdomain to Route53.** Create a Route53 zone and delegate `cp`/`relay` via NS
  records at GoDaddy. Awkward (per-host delegation + ACM validation records live in the delegated zone).
- **Option C — Keep DNS at GoDaddy (no Route53).** Refactor the IaC to make Route53 optional: use ACM
  DNS validation via CNAMEs added manually at GoDaddy, and output the ALB DNS name so `cp`/`relay` CNAMEs
  are added at GoDaddy. *Least AWS-invasive*, but requires a Terraform change (gate `dns_acm.tf` behind a
  flag + add outputs). **Recommended if you want to keep GoDaddy as the DNS authority.**

Until a DNS option is approved, `terraform-plan.sh` intentionally refuses to run with a placeholder
`route53_zone_id`.

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

## Terraform remote state
Bootstrapped **separately** — see `../REMOTE_STATE.md`. Do **not** reuse the downloads bucket. Recommended
dedicated bucket `roofspan-tfstate-<account>-<region>` (versioning + SSE-KMS + Block Public Access) with
Terraform **S3-native locking** (`use_lockfile=true`, Terraform ≥ 1.10) — no DynamoDB table required. Export
`TF_STATE_BUCKET` (and optionally `TF_STATE_KEY`) before Stage A / the plan runner.

---

## Security review reminders (verify in `tfplan.txt`)
- RDS **private**, Valkey **private** (no public endpoints)
- ECS tasks `assign_public_ip = false`; **only the ALB** is public
- `cp.roofspan.io` / `relay.roofspan.io` host routing correct
- KMS entitlement-signing key scoped to the **CP signer**; **Relay has no `kms:Sign`** on it
- Secrets referenced via **Secrets Manager** (no plaintext secrets in the plan)
- **No** changes to `downloads.roofspan.io` / `roofspan-downloads-prod`
- **No** customer business database in AWS (CP DB holds commercial metadata only)
