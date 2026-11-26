# Hosted Control Plane — release-candidate deployment handoff (NOT deployed; awaiting owner approval)

Service: Railway project "RoofSpan Production" → Control Plane service (`backend/cp_asgi.py`, built from
`deploy/railway/Dockerfile` per `railway.json`). It serves BOTH `cp.roofspan.io` and `relay.roofspan.io`.
No customer business data lives here (companies, installations, licences, subscriptions, device pairings only).
Deploy the release-candidate commit (RELEASE_RC_0.5.0.md). No secret values belong in this file, logs or Git.

## 1. SECRETS_ENCRYPTION_KEY
- Format: exactly 32 random bytes encoded as URL-safe Base64 with padding = **44 characters**, ending in `=`
  (alphabet A–Z a–z 0–9 `-` `_`). Used as an AES-256-GCM key (`core._enc_key`) to encrypt company recovery codes.
- Generate locally (prints only to your terminal; don't paste it anywhere except Railway and your password manager):
  - macOS/Linux: `python3 -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`
  - or: `openssl rand -base64 32 | tr '+/' '-_'`
  - Windows PowerShell: `$b=New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b).Replace('+','-').Replace('/','_')`
- Check a value without printing it: `python3 -c "import base64,getpass;k=getpass.getpass('key: ');print(len(k), len(base64.urlsafe_b64decode(k)))"` → `44 32`.
- Never rotate or lose it: recovery codes already issued could no longer be shown (their hashes still validate restores).

## 2. Where to set it
Railway → RoofSpan Production → **Control Plane service** (not the Postgres service) → **Variables** → New Variable
`SECRETS_ENCRYPTION_KEY` (mark it sealed). Railway stages variable changes; applying them redeploys the CURRENTLY
deployed commit (harmless: today's build ignores the variable). Keep it identical in every future environment of this
Control Plane. From the RC onward, `CP_ENV=production` refuses to start without it, so a missing key can't silently break
registration — Railway keeps the previous deployment serving.

**Before pushing the RC to GitHub:** check Railway → service → Settings → Source: if auto-deploy is on for the branch you
push to, pushing deploys immediately. Disable auto-deploy (or push to a branch Railway doesn't watch) until you approve.

## 3. Backup and restore (Railway Postgres)
Run from your computer with PostgreSQL client tools of the same or newer major version as the server
(`SELECT version();`). Use the Postgres service's `DATABASE_PUBLIC_URL` (Postgres service → Variables; copy into an
environment variable, don't type it into commands that are saved to shell history).
1. Railway → Postgres service → **Backups** → create a manual backup (if your plan offers it) and note its time.
2. Logical backup (always):
   `pg_dump --format=custom --no-owner --no-privileges --file roofspan-cp-$(date +%Y%m%d-%H%M).dump "$CP_DB_URL"`
3. Verify the file: `pg_restore --list roofspan-cp-*.dump | grep -c "TABLE DATA"` (non-zero), and record row counts (§5 step 1).
   Store the dump encrypted (it contains customer contact details and hashed credentials).
4. Restore (only for rollback, service stopped/paused first):
   `pg_restore --clean --if-exists --no-owner --no-privileges --dbname "$CP_DB_URL" roofspan-cp-YYYYMMDD-HHMM.dump`
   or Railway → Postgres → Backups → Restore. Anything written after the backup (new registrations, pairings, Stripe events)
   is lost; Stripe events can be re-sent from the Stripe dashboard.

## 4. Database migration
- Only one Control Plane migration in this release: `e1f2a3b4c5d6 → f3a9c1d2b7e4` (C6 company recovery).
  Adds `companies.phone`, `address`, `match_key`, `recovery_code_hash`, `recovery_code_enc`; unique indexes on active
  `match_key` and on one ACTIVE installation per public key (older ACTIVE duplicates with the same key → `REPLACED`).
  Subscriptions, licences, devices and billing are untouched.
- Applied automatically at startup (`init_control_plane()` → `run_cp_migrations()`, advisory-locked). Logs:
  `Control Plane migration inspection: ... revision=e1f2a3b4c5d6 head=f3a9c1d2b7e4` then `Control Plane schema ready (migrations applied).`
- Manual equivalents (Railway → service → shell, or `railway run`, working directory `/app`):
  - status: `alembic -c control_plane/alembic.ini current`
  - upgrade: `python -c "from control_plane.migrations_runner import run_cp_migrations as r; print(r())"`
    (same code path as startup; prefer this over raw `alembic upgrade head`)
  - downgrade (rollback only): `alembic -c control_plane/alembic.ini downgrade e1f2a3b4c5d6`
- Read-only pre-checks (Postgres → Data → Query, or psql):
  - `SELECT version_num FROM alembic_version;` → expect `e1f2a3b4c5d6`
  - duplicates the migration will mark REPLACED (expect 0 rows; stop and review any):
    `SELECT md5(public_key_pem), count(*) FROM installations WHERE status='ACTIVE' GROUP BY 1 HAVING count(*) > 1;`

## 5. Deployment procedure (after you approve)
1. Record: `SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM installations WHERE status='ACTIVE'), (SELECT count(*) FROM subscriptions), (SELECT count(*) FROM mobile_devices WHERE revoked_at IS NULL);`
   and the current Railway deployment ID.
2. Confirm `SECRETS_ENCRYPTION_KEY` is set (§2) and the backup is verified (§3).
3. Push the RC commit (Save to GitHub) to the branch Railway deploys, or Railway → Deployments → deploy that commit.
4. Watch logs for the migration lines (§4) and `/health` passing. Railway only switches traffic after the health check.

## 6. Rollback procedure
- Code-only rollback with the new schema is NOT supported (the previous build doesn't know `f3a9c1d2b7e4`; its Control
  Plane would stay "not ready", Relay would keep working).
- Option A (preferred if little time has passed): pause the service → restore the §3 backup → Railway → Deployments →
  previous deployment → Redeploy.
- Option B (keeps data written since deploy): in the NEW deployment's shell run the §4 downgrade, then redeploy the previous
  deployment. Recovery codes are dropped; installations marked REPLACED stay REPLACED.
- Installed Offices need no change either way; restore/recovery features are simply unavailable again.

## 7. Post-deployment validation
Health and schema
1. `https://cp.roofspan.io/health` and `https://relay.roofspan.io/health` → `status: ok`, `control_plane.ready: true`.
2. `SELECT version_num FROM alembic_version;` → `f3a9c1d2b7e4`; §5 step 1 counts unchanged.
3. `GET /api/control-plane/version-policy` → unchanged (mobile_min_supported stays 1.0.0 — Office 0.5.0 enforces Field 1.1.0).
Licensing and existing subscriptions
4. An existing Office 0.4.8 install: Settings → Subscription still Active with the same seats; licence refresh succeeds
   (no "offline grace" banner after a restart).
5. Stripe dashboard → webhook endpoint: recent deliveries 2xx. No subscription changes appear. (Live Stripe was never
   exercised from preview — TB-3; treat as unverified until checked here.)
Device pairing
6. Existing paired Field devices keep connecting and syncing without re-pairing (Office → Settings → Devices list unchanged).
7. Office 0.5.0 test PC: pair a new Field 1.1.0 device (QR and numeric code); revoke it and pair again.
Recovery codes
8. Office 0.5.0, signed in as the owner → Settings → Company & Integrations → the company recovery code is shown (generated on first view for existing companies); viewing again
   shows the same code.
9. `POST /api/control-plane/installation/precheck` with `{}` → 422 (route exists), not 404.
Company recovery
10. Fresh Office 0.5.0 test install with the SAME company name, phone and address → setup offers "Restore my company".
11. Wrong code → refused (repeated failures are throttled); correct code → the same company, licence, subscription and seats
    are attached to the new installation and the old installation becomes REPLACED. Field devices paired with the old
    installation must be paired again with the new one.
12. A different company name/phone/address → creates a new company (no restore offered).
