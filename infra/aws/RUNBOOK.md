# RoofSpan Control Plane + Secure Relay — Deployment Runbook (AWS)

**Scope gate:** nothing in this repo has been provisioned. Every step below is HUMAN-executed with real
AWS credentials. Do not run `apply` until the plan is reviewed and approved. Never modify
`downloads.roofspan.io`.

## 0. Prerequisites / inputs (HUMAN REQUIRED — do not invent)
- AWS account ID **391722048303** + operator access; **`aws_region = us-east-2`** (LOCKED).
- **DNS = external (GoDaddy)** by default (`dns_provider = "external"`) — **no Route53 zone required**.
  Only set `route53_zone_id` if you switch to `dns_provider = "route53"`.
- Terraform ≥ 1.10 (S3 native lock; verified v1.10.5), Docker, AWS CLI v2.

## 1. Confirm region + DNS mode
`aws_region` == `us-east-2`. Confirm `dns_provider` (`external` for GoDaddy). For external DNS you will
add records at GoDaddy from the Terraform outputs (`acm_validation_records`, `external_dns_endpoint_records`)
— see §5b. Do NOT touch `downloads.roofspan.io`.

## 2. Terraform remote-state bootstrap
Follow `REMOTE_STATE.md` (create state bucket, `terraform init -backend-config=...`). HUMAN REQUIRED.

## 3. Create/verify the KMS entitlement-signing key
`terraform apply` creates it, OR pre-create. Confirm KeySpec `ECC_NIST_EDWARDS25519`, KeyUsage
`SIGN_VERIFY`. Grant the CP task role `kms:Sign`/`GetPublicKey` (in `iam.tf`). **Confirm the exact KMS
Ed25519 SigningAlgorithm/MessageType** against current AWS docs and adjust `control_plane/signer.py` if
needed (flagged there).

## 4. Populate production secrets (out-of-band — never in TF/Git)
For each empty secret from `secrets.tf` outputs:
`aws secretsmanager put-secret-value --secret-id roofspan-production/stripe_secret_key --secret-string ...`
(stripe_secret_key, stripe_webhook_secret, revenuecat_secret if used, operator_config). RDS master secret
is auto-managed by RDS.

## 5. Build + push images (immutable digests)
```
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <acct>.dkr.ecr.<region>.amazonaws.com
docker build -f infra/docker/control-plane/Dockerfile -t roofspan-control-plane .
docker build -f infra/docker/relay/Dockerfile        -t roofspan-relay .
# tag with the ECR repo URLs (terraform output ecr_*_repo), push, capture the sha256 digests
```
Set `control_plane_image` / `relay_image` in `terraform.tfvars` to the **@sha256:** digests.

## 6. Init / plan / review / apply
`terraform fmt -check && terraform validate && terraform plan` → review → `terraform apply`.
**External DNS (GoDaddy) = two-stage apply** (ACM must be ISSUED before the HTTPS listener):
### 5b. External DNS — HUMAN REQUIRED records at GoDaddy
1. Stage 1 — create the cert only: `terraform apply -target=aws_acm_certificate.main`, then
   `terraform output acm_validation_records` → add the CNAME(s) at GoDaddy → wait until ACM = ISSUED.
2. Stage 2 — full apply. After the ALB exists, `terraform output external_dns_endpoint_records` →
   add `cp.roofspan.io` and `relay.roofspan.io` as **CNAME → ALB DNS name** at GoDaddy.
Terraform never writes to GoDaddy; it only reports the required records.

## 7. Migrations
The CP container entrypoint runs `alembic upgrade head` under a **Postgres advisory lock** (single runner;
concurrent tasks cannot race). CP becomes healthy only after migrations succeed + `/api/control-plane/ready`
passes (DB + active signing key).

## 8. Verify
- `https://cp.roofspan.io/api/control-plane/health` = 200; `/ready` = 200.
- WSS: connect to `wss://relay.roofspan.io` (relay health `https://relay.roofspan.io/api/relay/health`).
- Connect a **RoofSpan Office** installation (outbound tunnel) and a **Mobile-style** client; verify a
  request routes end-to-end.
- **Multi-node Relay**: scale relay to ≥2 tasks; confirm an Office tunnel on node A + Mobile on node B
  still routes (Valkey registry + pub/sub). Restart one relay task → client reconnects, stale registry
  entry expires via TTL.
- **Entitlement**: issue an entitlement (KMS sign) and verify in RoofSpan Office with the published public
  key.
- **Stripe** (TEST creds only, if supplied): send a test webhook; confirm processing + no mock fallback.
- Restart CP/relay tasks → verify recovery. Confirm RDS + Valkey are private (no public endpoint).
  Confirm CloudWatch logs flowing + backups configured.

## 9. Rollback / destroy safeguards
- App rollback: deploy the previous image digest (ECS rolling). CP schema rollback is NOT assumed
  safe-by-downgrade — restore from RDS snapshot if a migration must be reverted.
- `terraform destroy` is blocked for RDS by `deletion_protection` in production (disable deliberately).
- Never destroy the state bucket or the downloads distribution.

## 10. Post-deploy client config
Set RoofSpan Office + Mobile production endpoints (see `infra/config/production.endpoints.env.example`):
`CONTROL_PLANE_BASE_URL=https://cp.roofspan.io`, `RELAY_WSS_URL=wss://relay.roofspan.io` (Relay URL is
independent — not derived from the CP URL). Clients must fail clearly if absent.

## HUMAN REQUIRED checklist
AWS account 391722048303 · region us-east-2 · DNS mode (external/GoDaddy default) · GoDaddy validation +
cp/relay CNAME records (from TF outputs) · state bucket/KMS decision · VPC CIDR approval · CP/Relay ECS
sizing approval · Stripe prod secret + webhook secret · RevenueCat prod creds (if used) · Cognito operator
users · KMS key permissions/confirmation · Docker build+push execution · Terraform credentials · final
`plan` review · explicit approval to `apply`.
