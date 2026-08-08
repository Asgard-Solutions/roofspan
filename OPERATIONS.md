# RoofSpan Office — Operations & Recovery Runbook

Local single-company app. Architecture: **Office Browser → FastAPI → PostgreSQL** (authoritative). No MongoDB.
This runbook lets a competent administrator start, back up, and recover RoofSpan without development-session knowledge.

## 1. How RoofSpan starts
- Services are supervisor-managed: `postgresql`, `backend` (FastAPI on :8001), `frontend` (React on :3000).
- On backend startup: `migrations_runner.run_migrations()` runs → `ensure_database()` (self-heals a missing DB / fails loudly if the server is unreachable) → `alembic upgrade head` → idempotent owner seed. No `create_all`, no manual SQL.
- Check status: `sudo supervisorctl status`. Restart one service: `sudo supervisorctl restart backend`.

## 2. PostgreSQL persistence (durable)
| Item | Value |
|------|-------|
| Engine | PostgreSQL 15 (supervisor program `postgresql`) |
| **Data directory (PERSISTENT)** | **`/data/db/roofspan_pgdata`** — on the persistent volume `/dev/nvme0n9` (mounted at `/data/db`). Owned by `postgres`, mode 700. |
| Config | `/etc/postgresql/15/main/postgresql.conf` (`data_directory` points at the persistent path); supervisor `-D` matches. |
| Connection | `DATABASE_URL` in `backend/.env` |

The PostgreSQL data directory was moved off the ephemeral container overlay onto the persistent volume so business data survives a container restart/recreation. **Verified** by a destructive test: created a record → deleted the old overlay dir → restarted PostgreSQL from the persistent path → the record survived and the app operated normally.

**Deployment caveat (HUMAN ACTION for a from-scratch container rebuild):** the pointers that make PostgreSQL use the persistent path live in system config (`/etc/supervisor/conf.d/postgresql.conf` and `/etc/postgresql/15/main/postgresql.conf`), not in the `/app` repo. If a deployment recreates those from the base image, re-apply the two one-line settings (`-D /data/db/roofspan_pgdata` and `data_directory = '/data/db/roofspan_pgdata'`) and restart, OR restore from the latest backup (Section 5). The **backups + encryption key are the guaranteed recovery set** regardless of container topology.

## 3. Required environment / secrets (`backend/.env`, never sent to the browser)
- `DATABASE_URL` — Postgres connection.
- `JWT_SECRET` — token signing (strong, non-default). Rotating it invalidates existing sessions.
- `SECRETS_ENCRYPTION_KEY` — **AES-GCM key that encrypts integration API keys at rest. MUST be preserved off-container together with backups.** A DB backup **without** this key is an incomplete recovery set: stored RentCast/MapTiler keys cannot be decrypted (users would have to re-enter them). **Do NOT put this key inside the database backup.** Store it in the deployment's secret store / `.env` kept outside disposable container state.
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — idempotent owner seed on startup.
- `WEBHOOK_CRON_SECRET` — bearer secret the platform cron uses to call the backup endpoint.

## 4. Automated backups
- **Schedule:** platform cron `nightly-db-backup` in `/app/.emergent/crons.yml` → `POST {{BASE_URL}}/api/cron/backup` at **08:00 UTC daily**. The endpoint authenticates with `WEBHOOK_CRON_SECRET` and runs the backup in the background.
- **Implementation:** `backend/scripts/backup_db.sh` → `pg_dump -Fc` (custom format).
- **Storage (off the disposable overlay):** `/data/db/roofspan_backups/` on the persistent volume. Files are timestamped `roofspan_<UTC>.dump`.
- **Retention:** keeps the newest **14** dumps (override `ROOFSPAN_BACKUP_RETENTION`); older ones pruned.
- **Safety:** writes to `.partial` then atomic `mv` (never corrupts/overwrites the only good backup); failures are logged and never delete good backups.
- **Detectability:** every run logs to `/data/db/roofspan_backups/backup.log`; last outcome in `/data/db/roofspan_backups/LAST_BACKUP_STATUS` (`OK ...` / `FAIL ... rc=N`, non-zero exit on failure).
- **Run manually:** `bash /app/backend/scripts/backup_db.sh`
- **Off-site copy (IMPLEMENTED):** after each successful local backup, `backup_db.sh` copies the completed `.dump` to **Emergent managed object storage** (pod-independent) via `backend/offsite_backup.py` at object path `roofspan/backups/<filename>`. Uses `EMERGENT_LLM_KEY` + `INTEGRATION_PROXY_URL` from `backend/.env` — **no external account/credentials required**. The local backup is always retained even if the off-site copy fails; an off-site failure is logged (`OFFSITE_FAILURE`), recorded in `LAST_OFFSITE_STATUS`, and makes the script exit non-zero (the run is NOT reported healthy). Off-site status is separate from `LAST_BACKUP_STATUS` (local).
- **Retention:** local keeps the newest 14 dumps. Off-site copies are **not auto-pruned** (never delete the only known-good remote backup); prune the remote manually if storage cost requires it.

## 5. Restore procedure (recover into production)
1. Stop the backend: `sudo supervisorctl stop backend`.
2. Recreate the DB and restore the chosen dump:
   ```bash
   PGPASSWORD=<pwd> psql -h 127.0.0.1 -U roofspan -d postgres -c "DROP DATABASE IF EXISTS roofspan;" -c "CREATE DATABASE roofspan;"
   PGPASSWORD=<pwd> pg_restore -h 127.0.0.1 -U roofspan -d roofspan /data/db/roofspan_backups/roofspan_<UTC>.dump
   ```
3. Ensure `SECRETS_ENCRYPTION_KEY` in `backend/.env` matches the value used when the backup was taken (else stored provider keys won't decrypt).
4. Start the backend: `sudo supervisorctl start backend` (Alembic reconciles to head; owner seed is idempotent).

## 6. Restore-verification drill (operational tool — run periodically)
- Local source: `bash /app/backend/scripts/restore_drill.sh` (or pass a specific dump path).
- **Off-site source: `bash /app/backend/scripts/restore_drill.sh --offsite`** — retrieves the latest backup FROM object storage, restores it into an **isolated** DB `roofspan_restore_drill`, verifies tables/users/`alembic_version`/key tables, prints **PASS/FAIL**, records `LAST_OFFSITE_RESTORE_STATUS`, then drops the isolated DB. It **never** touches production.
- **Verified:** both local and `--offsite` drills PASS (tables=29, users present, alembic at head); production untouched; isolated DB cleaned up.
- **Admin visibility:** owner/administrator can see last-local / last-off-site / last-off-site-restore-drill status (OK/PASS/FAILED + timestamp) at **Administration → Backups** (read-only; served by `GET /api/admin/backup-status`).
- Recommend the administrator run the `--offsite` drill monthly.

## 6b. Secrets recovery strategy (off-container)
- `SECRETS_ENCRYPTION_KEY` is **never** placed in the DB dump. Preserve it in the deployment's secret store / an `.env` kept outside disposable container state. A complete RoofSpan recovery set = **{ off-site DB dump } + { SECRETS_ENCRYPTION_KEY }**. On restore, put the same key in `backend/.env` before starting the backend so stored provider credentials decrypt; otherwise re-enter provider keys via Administration → Settings → Integrations.

## 7. Alembic migrations
- Revisions: `61f7ea11c757` (baseline, all Phase 1–4 tables) → `7a95fb788bfd` (unique `uq_materials_name`).
- Commands (from `backend/`): `python -m alembic current` · `python -m alembic upgrade head` · `python -m alembic revision --autogenerate -m "msg"` · `python -m alembic downgrade -1`.
- Adopting a pre-Alembic DB once: `python -m alembic stamp 61f7ea11c757` then `python -m alembic upgrade head`.

## 8. Expected behavior after restart
Business data persists, login works, encrypted integration settings remain readable (masked `••••LAST4`), audit records intact, relationships intact, `alembic current` = `7a95fb788bfd (head)`. No manual DB repair needed. The in-memory brute-force lockout resets on restart (by design).

## 9. If PostgreSQL is unavailable
The backend fails loudly within ~5s at startup with an actionable error in `backend.err.log` (it does not hang). Checklist:
1. `sudo supervisorctl status postgresql` — start it if stopped.
2. `sudo -u postgres psql -l` — if the `roofspan` DB is missing, the backend auto-creates it on next start (role must exist). If the **role** is missing, run once: `bash /app/backend/scripts/bootstrap_postgres.sh` (needs superuser).
3. Confirm `/data/db/roofspan_pgdata` exists and is owned by `postgres` (mode 700).
4. `sudo supervisorctl restart backend`.

## 10. Before rebuilding/replacing the app container — PRESERVE
- The latest backup(s) from `/data/db/roofspan_backups/` (copied off-pod).
- `SECRETS_ENCRYPTION_KEY` (and the rest of `backend/.env`) — kept **outside** the backup.
- Note the PostgreSQL persistent path settings (Section 2 caveat) if system config is not part of the deployment image.

## 11. Security posture (reviewed)
bcrypt passwords; HS256 JWT (server-side secret, expiry, `type=access`); disabled users rejected (401) even with a valid token; brute-force lockout (5/15min); integration keys AES-GCM at rest, only masked `••••LAST4` returned (plaintext never); MapTiler tiles proxied server-side; RBAC enforced independently on the backend; DB credentials never reach the browser.

## 12. RentCast
Ships with clearly-labeled SAMPLE/DEMO import data. The real server-side client + Test Connection activate automatically once an owner saves a real key in **Administration → Settings → Integrations**. No credentials are embedded in code or config.
