# Deploying the RoofSpan Central Control Plane to Railway

This deploys **only** the central Control Plane API (`backend/cp_asgi.py` → `app`) to
`https://cp.roofspan.io`. It does **not** host the marketing site (stays on Vercel at `roofspan.io` /
`www.roofspan.io`), does **not** host the RoofSpan Office local backend, and stores **no** customer
business data — that lives in each customer's local PostgreSQL install.

```
Internet
  ├── roofspan.io / www.roofspan.io   → Vercel        (unchanged)
  └── cp.roofspan.io                  → Railway        (this service)
                                          └── Control Plane FastAPI (cp_asgi:app)
                                                └── Railway PostgreSQL (private *.railway.internal)
```

- **App object:** `cp_asgi:app` (CP router + `/health` only).
- **Build:** `deploy/railway/Dockerfile` (see `railway.json`), context = repo root.
- **Start:** `uvicorn cp_asgi:app --host 0.0.0.0 --port $PORT` (Railway injects `$PORT`).
- **Health check:** `GET /health` (returns 200 + best-effort DB status; never leaks secrets).
- **Schema:** applied automatically at startup by `init_control_plane()` (Control Plane Alembic
  migrations in `backend/control_plane/alembic/`), with a bounded DB-readiness retry. A fresh Railway
  Postgres is brought to head with no manual table creation.

## 1. Create the Railway project + PostgreSQL (HUMAN REQUIRED)
1. Railway → **New Project** → name it **RoofSpan Production**.
2. **Add a service → Database → PostgreSQL** (Railway provisions `DATABASE_URL`, `PGHOST`, `PGPORT`,
   `PGUSER`, `PGPASSWORD`, `PGDATABASE` and private `*.railway.internal` networking automatically).
   Keep Postgres **private** (do not enable a public proxy unless operationally required).

## 2. Add the Control Plane service from GitHub (HUMAN REQUIRED)
3. **Add a service → GitHub Repo → `Asgard-Solutions/roofspan`**.
4. Build settings: Railway auto-detects **`railway.json`** (Dockerfile builder, `deploy/railway/Dockerfile`).
   - Root directory: leave as repo root (the Dockerfile copies `backend/`).
   - Start command: already set in `railway.json` (`uvicorn cp_asgi:app --host 0.0.0.0 --port $PORT`).

## 3. Reference the database + set variables (HUMAN REQUIRED)
On the Control Plane service → **Variables**:

| Variable | Value | Class |
|---|---|---|
| `CONTROL_PLANE_DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (Railway reference) | Required non-secret (reference) |
| `CP_ENV` | `production` | Required non-secret |
| `BILLING_MODE` | `stripe` | Required non-secret |
| `STRIPE_SECRET_KEY` | `sk_live_…` | **Required secret** |
| `STRIPE_WEBHOOK_SECRET` | `whsec_…` (from step 7) | **Required secret** |
| `STRIPE_SEAT_LOOKUP_KEY` | `roofspan_seat_monthly` | Required non-secret |
| `APP_BASE_URL` | `https://roofspan.io` | Required non-secret |
| `ENTITLEMENT_SIGNER` | `kms` | Required non-secret |
| `CP_KMS_SIGNING_KEY_ID` | AWS KMS key id/ARN | **Required secret-ish** (id, not key material) |
| `AWS_REGION` | e.g. `us-east-1` | Required non-secret |
| `AWS_ACCESS_KEY_ID` | scoped IAM user | **Required secret** (KMS access) |
| `AWS_SECRET_ACCESS_KEY` | scoped IAM user | **Required secret** (KMS access) |
| `CP_OPERATOR_ISSUER` | operator JWT issuer (Cognito) | Required non-secret |
| `CP_OPERATOR_AUDIENCE` | operator JWT audience | Required non-secret |

> `require_production_config()` fails startup CLEARLY if any of Stripe, the DB URL (non-localhost), the KMS
> key (when `ENTITLEMENT_SIGNER=kms`), or operator issuer/audience is missing. No silent dev/mock fallback.
> **Do NOT commit any secret value** — set them only in Railway.

## 4. Deploy + generate a temporary domain (HUMAN REQUIRED)
5. Deploy. Watch logs for `Control Plane schema ready (migrations applied).`
6. Networking → **Generate Domain** (`https://<generated>.up.railway.app`). Verify:
   `GET https://<generated>.up.railway.app/health` → `{"status":"ok","database":"ok",...}`.

## 5. Custom domain (HUMAN REQUIRED — DNS)
7. Networking → **Custom Domain** → `cp.roofspan.io`. Railway shows a CNAME target.
   Add **only** that DNS record for `cp.roofspan.io` at your DNS provider. Railway issues SSL after
   verification. **Do NOT touch `roofspan.io` / `www.roofspan.io` (Vercel).**
8. Confirm `https://cp.roofspan.io/health` returns 200.

## 6. Stripe webhook (HUMAN REQUIRED — after cp.roofspan.io is live)
9. Stripe Dashboard → Developers → Webhooks → **Add endpoint**:
   `https://cp.roofspan.io/api/control-plane/billing/stripe/webhook`
   Events: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_succeeded`, `invoice.payment_failed`.
10. Copy the signing secret → set `STRIPE_WEBHOOK_SECRET` in **Railway only**; redeploy.
11. Create the Stripe **Price** under lookup key `roofspan_seat_monthly` ($49/seat/month).

## 7. Point customers at the Control Plane
The Windows installer template already ships (public, non-secret):
`LICENSING_CONTROL_PLANE_URL=https://cp.roofspan.io/api/control-plane`. No client change needed once DNS
is live. Do **not** put Stripe/KMS secrets on any customer machine.

## AWS KMS (HUMAN REQUIRED, not automated here)
Production entitlement signing uses AWS KMS (`ENTITLEMENT_SIGNER=kms`); the private key never leaves KMS.
Provide a **minimum-scoped** IAM principal for Railway with only:
`kms:Sign`, `kms:GetPublicKey`, `kms:DescribeKey` on the specific signing key ARN
(`CP_KMS_SIGNING_KEY_ID`). Do not grant broad KMS/account access. No AWS resources are created by this task.
