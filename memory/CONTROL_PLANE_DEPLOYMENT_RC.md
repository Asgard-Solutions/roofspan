# Hosted Control Plane — release-candidate deployment (NOT deployed; awaiting owner approval)

Service: Railway "RoofSpan Production" → central service (`backend/cp_asgi.py`), serves BOTH
`cp.roofspan.io` (Control Plane) and `relay.roofspan.io` (Relay) from one node. Customer business data is not here.
Deploy from the same Git commit used for Office 0.5.0 / Field 1.1.0 (see RELEASE_RC_0.5.0.md).

## What changes on the hosted service
| Area | Live today (probed 2026-11-26) | After deploy |
|---|---|---|
| Company recovery (`/installation/precheck`, `/recover`, `/recovery-code`, `/company`) | 404 | available |
| CP database | head unknown (expected `e1f2a3b4c5d6`) | `f3a9c1d2b7e4` (C6 company recovery), applied automatically at start |
| Relay protocol | "1" | "1" (unchanged; relay code unchanged since 0.4.8) |
| Version policy (`mobile_min_supported` / `mobile_latest`) | 1.0.0 / 1.0.0 | unchanged — do NOT raise it (it is global; Office 0.5.0 enforces Field 1.1.0 itself) |

## Migration f3a9c1d2b7e4 (only CP migration in this release)
- Adds to `companies`: `phone`, `address` (default ''), `match_key`, `recovery_code_hash`, `recovery_code_enc` (NULL for existing rows).
- Unique index on active `match_key` (new column, so no existing row can collide).
- Installations sharing one public key: keeps the newest ACTIVE row, marks older ACTIVE duplicates `REPLACED`,
  then adds a unique index so a key can only have one ACTIVE installation. **This is the only change to existing records.**
- Existing companies get a recovery code lazily (first time Office Settings shows it / an operator reveals it).
- Subscriptions, licenses, devices, billing events: untouched.

## Required environment (Railway → Variables) — check BEFORE deploying
Everything already in deploy/railway/README.md §3, plus:
- **`SECRETS_ENCRYPTION_KEY`** (NEW requirement, secret): 32 random bytes, url-safe base64
  (`python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`).
  Encrypts recovery codes. Store it in your password manager; never rotate or lose it (existing codes become unreadable).
  With `CP_ENV=production` the service now refuses to start without it, so Railway keeps the old deployment live.
- `CP_DEV_BOOTSTRAP_SECRET` must stay the value installed Offices send (unchanged).

## Pre-deploy checklist (read-only SQL in the Railway Postgres console)
1. Take a Railway Postgres backup/snapshot and note the current deployment ID (for rollback).
2. `SELECT version_num FROM alembic_version;` → note it (expected `e1f2a3b4c5d6`).
3. Duplicate ACTIVE installations that the migration will mark REPLACED (expect 0 rows; review any):
   `SELECT md5(public_key_pem), count(*), array_agg(id ORDER BY created_at DESC) FROM installations WHERE status='ACTIVE' GROUP BY 1 HAVING count(*) > 1;`
4. Record counts for comparison:
   `SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM installations WHERE status='ACTIVE'), (SELECT count(*) FROM subscriptions), (SELECT count(*) FROM mobile_devices WHERE revoked_at IS NULL);`
5. Confirm `SECRETS_ENCRYPTION_KEY` is set.

## Deploy
1. Push the release-candidate commit to GitHub ("Save to GitHub"); Railway builds `deploy/railway/Dockerfile` on push to the
   connected branch (watch patterns `/backend/**`). Or trigger Deploy on that commit in Railway.
2. Logs must show `Control Plane schema ready (migrations applied).`; the health check `/health` must pass.

## Post-deploy validation
1. `GET https://cp.roofspan.io/health` → `control_plane.ready: true`; same for `https://relay.roofspan.io/health`.
2. `GET https://cp.roofspan.io/api/control-plane/version-policy` → unchanged values.
3. `POST https://cp.roofspan.io/api/control-plane/installation/precheck` with `{}` → 422 (route exists), not 404.
4. Re-run pre-deploy query 4: same counts; query 2 → `f3a9c1d2b7e4`.
5. Existing installed Office (0.4.8): still licensed, Field devices still connect and sync (no re-pairing).
6. Office 0.5.0 (test PC): Settings shows the company recovery code; setup with an existing company name/phone/address
   offers "Restore my company"; restoring with the code works.
7. Pair a new Field 1.1.0 device (QR and numeric code); existing devices remain listed; revoke/re-pair works.
8. Subscription state and seat counts in Office unchanged; Stripe webhook deliveries succeed (Stripe dashboard).
   (Stripe sandbox key in preview is expired — TB-3; live Stripe is configured only on Railway.)

## Rollback
- Code only, keeping the new schema: NOT supported — the previous build doesn't know revision `f3a9c1d2b7e4` and its
  Control Plane would stay "not ready" (Relay keeps working).
- Full rollback: (a) redeploy the previous Railway deployment AND restore the pre-deploy Postgres backup
  (loses any registrations/pairings made after deploy), or (b) with the NEW image run
  `alembic downgrade e1f2a3b4c5d6` against the CP database, then redeploy the previous deployment
  (installations marked REPLACED stay REPLACED; recovery codes are dropped).
- Installed Offices need no change for either path; recovery features are simply unavailable again.
