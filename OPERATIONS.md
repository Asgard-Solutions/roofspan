# RoofSpan Office — Operations & Production Readiness

Local single-company app. Architecture: **Office Browser → FastAPI → PostgreSQL** (authoritative). No MongoDB.

## 1. Database & Persistence

| Item | Value |
|------|-------|
| Engine | PostgreSQL 15 (supervisor program `postgresql`) |
| Data directory | `/var/lib/postgresql/15/main` |
| Connection | `DATABASE_URL` in `backend/.env` (`postgresql+asyncpg://roofspan:***@127.0.0.1:5432/roofspan`) |
| Schema management | **Alembic** (authoritative). Applied automatically at backend startup. |

**What survives what:**
- **Backend restart / frontend restart / PostgreSQL restart (same container):** all business data, users, encrypted integration secrets, audit logs, and relationships **persist** — data lives in the PostgreSQL data directory, not in process memory. Verified.
- **In-memory brute-force lockout** (`auth.py _attempts`) is intentionally ephemeral and resets on backend restart — by design for a local single-instance app.
- **Container/pod redeploy:** persistence depends on the deployment mounting `/var/lib/postgresql/15/main` on a persistent volume. In the Emergent **preview** container this path is container-local; a full pod rebuild without a mounted volume would not retain data. **Human action required:** for the intended production deployment, mount the PostgreSQL data directory on a persistent volume and schedule the backups below.

## 2. Schema Migrations (Alembic)

- Config: `backend/alembic.ini`, env: `backend/alembic/env.py`, migrations: `backend/alembic/versions/`.
- Startup calls `migrations_runner.run_migrations()` → `alembic upgrade head`. No `create_all`, no manual SQL.
- Alembic runs synchronously; the async `DATABASE_URL` is converted to the sync `postgresql+psycopg://` driver inside `env.py`.

Revisions:
1. `61f7ea11c757` — baseline schema (Phases 1–4, all tables/indexes).
2. `7a95fb788bfd` — Phase 5 hardening: unique constraint `uq_materials_name` on `materials.name`.

Commands (run from `backend/`, `DATABASE_URL` from `.env`):
```bash
python -m alembic current              # show current revision
python -m alembic upgrade head         # apply pending migrations (fresh DB builds fully; existing DB migrates forward)
python -m alembic revision --autogenerate -m "message"   # create a new migration from model changes
python -m alembic downgrade -1         # roll back one revision
```
Verified: a fresh empty database builds the full schema from history; an existing database migrates forward non-destructively; migrations fail loudly on unsafe assumptions; the model metadata matches the migrated schema (empty autogenerate diff).

Adopting an existing (pre-Alembic) database once: `python -m alembic stamp 61f7ea11c757` then `python -m alembic upgrade head`.

## 3. Backup

Create a compressed logical backup (custom format, supports selective restore):
```bash
PGPASSWORD=<pwd> pg_dump -h 127.0.0.1 -U roofspan -d roofspan -Fc -f /path/roofspan_$(date +%F).dump
```
Store backups **off the app container** (mounted volume, object storage, or an offsite location) — a backup on the same ephemeral disk does not protect against pod loss.

## 4. Restore & Recovery Verification

```bash
PGPASSWORD=<pwd> psql -h 127.0.0.1 -U roofspan -d postgres -c "CREATE DATABASE roofspan_restore;"
PGPASSWORD=<pwd> pg_restore -h 127.0.0.1 -U roofspan -d roofspan_restore /path/roofspan_YYYY-MM-DD.dump
# verify:
PGPASSWORD=<pwd> psql -h 127.0.0.1 -U roofspan -d roofspan_restore -c "select count(*) from users; select version_num from alembic_version;"
```
Verified in an isolated test DB: row counts (users/materials/audit) matched the source exactly and the Alembic version was preserved. To recover for real, restore into `roofspan` (stop the backend first) or repoint `DATABASE_URL`.

## 5. Secrets / Configuration required to run & restore

All from `backend/.env` (never exposed to the browser):
- `DATABASE_URL` — Postgres connection.
- `JWT_SECRET` — token signing (strong non-default value). Rotating it invalidates existing sessions.
- `SECRETS_ENCRYPTION_KEY` — **AES-GCM** key that encrypts integration API keys at rest. **Must be preserved with the backup**; without the identical key, restored RentCast/MapTiler secrets cannot be decrypted (users would simply re-enter keys via Administration → Settings → Integrations).
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — idempotent owner seed on startup.

## 6. Security posture (reviewed Phase 5)
- Passwords: bcrypt (`core.hash_password`).
- JWT: HS256, server-side secret, `type=access`, expiry enforced; disabled users are rejected (`get_current_user` checks `is_active` → 401) even with a still-valid token.
- Brute force: 5 failed attempts / 15 min lockout per IP+email.
- Integration API keys: AES-GCM encrypted at rest; API returns only `has_secret` + masked `••••••••LAST4` — plaintext is never returned. Decryption happens server-side only (Test Connection). MapTiler tiles are proxied server-side so the key never reaches the browser.
- RBAC enforced independently on the backend via `require_roles`.

## 7. RentCast
Ships with clearly-labeled SAMPLE/DEMO import data. The real server-side client + Test Connection are wired and auto-used once an owner saves a real key in **Administration → Settings → Integrations**. No credentials are embedded in code.
