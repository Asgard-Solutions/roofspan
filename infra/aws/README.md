# RoofSpan AWS — Control Plane + Secure Relay (Terraform, PLAN/IaC only)

Production infrastructure for the **central** RoofSpan services only. **No customer roofing business data
lives here** — that stays in each customer's local RoofSpan Office PostgreSQL. This stack was authored
**plan-only**: nothing was provisioned, no AWS credentials were used, and the live `downloads.roofspan.io`
CloudFront/S3 distribution was **not touched** (it is an external dependency — see below).

## What this provisions (once a human runs it)
- **VPC** (2 AZs): public (ALB) / private-app (ECS) / private-data (RDS, Valkey). RDS + Valkey have **no
  public access**. Cost-conscious egress: VPC interface endpoints (ECR, logs, secrets, KMS, STS,
  elasticache) + S3 gateway endpoint + **one NAT gateway by default** (`single_nat_gateway=true` — see
  NAT tradeoff below).
- **ALB** (HTTPS/WSS, ACM): host routing `cp.roofspan.io` → Control Plane TG, `relay.roofspan.io` → Relay
  TG; long idle timeout for WebSockets; HTTP→HTTPS redirect.
- **ECS/Fargate** cluster with two logically-distinct services: **Control Plane** and **Secure Relay**
  (both scale >1; conservative CPU target autoscaling).
- **RDS PostgreSQL** (CP commercial metadata only): encrypted, private, automated backups, deletion
  protection in prod, master creds in **RDS-managed Secrets Manager** (no plaintext in TF).
- **ElastiCache Valkey** (encrypted, private): Relay node registry + Pub/Sub — ephemeral routing only.
- **ECR** (immutable tags), **KMS** (symmetric general + **asymmetric Ed25519 entitlement-signing** key),
  **Secrets Manager** (empty containers, populated out-of-band), **Cognito** (RoofSpan operator auth),
  **CloudWatch** (log groups + baseline alarms), **Route53/ACM** in the **existing** hosted zone.

## NAT decision (reported, not silent)
Default = **one NAT gateway** for initial production cost control. Tradeoff: single-AZ egress SPOF — if
that AZ degrades, private-subnet outbound (e.g. Stripe API calls) is affected until recovery. AWS API
traffic is largely NAT-independent thanks to the VPC endpoints above. Set `single_nat_gateway=false` for
one NAT per AZ (HA egress, higher cost). **DECISION REQUIRED** if HA egress is desired for launch.

## Files
`versions.tf providers`, `variables.tf`, `locals.tf`, `network.tf`, `endpoints.tf`, `security.tf`,
`ecr.tf`, `iam.tf`, `kms.tf`, `secrets.tf`, `rds.tf`, `valkey.tf`, `alb.tf`, `ecs.tf`, `cognito.tf`,
`dns_acm.tf`, `observability.tf`, `outputs.tf`, `terraform.tfvars.example`.

## Usage (after human inputs — see RUNBOOK.md)
```
cp terraform.tfvars.example terraform.tfvars   # fill REQUIRED values (region, zone id, image digests)
terraform fmt -check && terraform validate
terraform init -backend-config=...             # remote state bootstrap first (REMOTE_STATE.md)
terraform plan
```
`aws_region` and `route53_zone_id` are **REQUIRED** (no defaults). Images are referenced by **digest**.

## External dependency — DO NOT MODIFY
`downloads.roofspan.io` (CloudFront → private S3 for the Windows installer/updates) is managed **outside**
this stack. This Terraform does not read, import, or change its S3 bucket, CloudFront distribution, DNS,
ACM, OAC/OAI, or bucket policy.
