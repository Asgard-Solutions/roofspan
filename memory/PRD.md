# RoofSpan — Product Requirements & Status

## Product
RoofSpan is a commercially distributed roofing business application:
- **RoofSpan Office**: runs locally on Windows (FastAPI backend + React browser UI + local PostgreSQL).
- **Mobile app**: React Native (Expo) companion that connects back to the local Office install via a cloud Secure Relay.
- Distribution is a deterministic Windows build pipeline: PowerShell scripts, PyInstaller (ONEDIR), WiX 5.0.2 Burn bundles, native Windows SCM services via pywin32.

## Preferred language
English.

## Architecture
- `/app/backend/`: FastAPI endpoints, Alembic migrations (`backend/alembic`, `backend/alembic.ini`, `backend/migrations_runner.py`).
- `/app/frontend/`: React browser UI.
- `/app/mobile/`: React Native Expo app.
- `/app/windows/installer/`: WiX 5.0.2 authoring (`bundle.wxs`, `RoofSpan.wxs`, PowerShell scripts).
- `/app/windows/winbuild/`: PyInstaller specs, pywin32 SCM entrypoints (`backend_entry.py`, `relay_entry.py`, `roofspan_service.py`, `db_bootstrap.py`).
- `/app/windows/tests/`: pytest regression suite (Linux-runnable static/parser guards; real MSI/exec smoke tests via GitHub Actions).
- `/app/.github/workflows/windows-build-scripts.yml`: CI proving clean Windows installs.

## Integrations
- Stripe (payments) — requires user API key.
- MapLibre GL JS / MapTiler (maps, ZIP search).

## DB schema (key tables)
`subscriptions`, `billing_events`, `pairing_tokens`, `device_credentials`.

## Cloud deploy (Railway)
- **roofspan-website** (marketing site): service Root Directory `/roofspan-website`, Nixpacks. Config at `roofspan-website/railway.json` (build `yarn build`, start `yarn serve`). Config-as-code path in Railway must be `/roofspan-website/railway.json` (absolute from repo root — it does NOT follow Root Directory).
- **Control Plane** (`cp.roofspan.io`, serves `backend/cp_asgi.py:app`): Dockerfile build via root `railway.json` → `deploy/railway/Dockerfile`. **Build context = repo root** (Dockerfile `COPY backend/ /app/`), so the Railway service Root Directory MUST be empty/repo-root. Required env vars documented in `deploy/railway/README.md` (CONTROL_PLANE_DATABASE_URL, Stripe, KMS, operator issuer/audience) — startup fails-closed without them.
  - **[2026-06] Recovered lost deploy files**: a Save-to-GitHub conflict merge (PR#2 `conflict_190826_0821`) left `main` without `deploy/railway/*`, root `railway.json`, and `backend/cp_asgi.py`; the Railway build then failed with `COPY backend/ → "/backend": not found`. Restored all 4 files from PR#2 onto current `main`; verified `cp_asgi:app` imports and exposes `/health`.
  - **[2026-06] Fixed CP startup crash `ModuleNotFoundError: psycopg2`**: Railway's `DATABASE_URL` is a plain `postgresql://…`, which made `create_async_engine` pick the sync psycopg2 dialect. Added `_to_async_url()` in `backend/control_plane/config.py` to normalize any `postgres://`/`postgresql://`/`+psycopg2`/`+psycopg` URL to the canonical `postgresql+asyncpg://` (the CP sync paths already convert away from `+asyncpg` to psycopg v3). Verified `cp_asgi` imports with a Railway-style URL.
  - **Healthcheck note**: `/health` returns 200 regardless of DB, but the startup event runs first. `require_production_config()` only enforces when `CP_ENV=production` and then requires: `BILLING_MODE=stripe`+`STRIPE_SECRET_KEY`+`STRIPE_WEBHOOK_SECRET`, `CP_KMS_SIGNING_KEY_ID` (if `ENTITLEMENT_SIGNER=kms`), and `CP_OPERATOR_ISSUER`+`CP_OPERATOR_AUDIENCE`. `init_control_plane()` also needs the DB reachable (bounded retry). For a first smoke test, leave `CP_ENV` unset so only the DB is required.

## Completed (this session)
- **[2026-06] Reconciled 3 stale pytest failures after upstream git pull (110 commits → aab2d95).** All were stale test assertions from legitimate upstream refactors; production behavior intact:
  - `test_spec_datas_reference_real_backend_alembic`: broadened `"migrations" not in spec` → now forbids only the removed `backend/migrations` dir, allows the `migrations_runner` hiddenimport.
  - `test_released_orphaned_revision_is_explicitly_reconciled`: split the contiguous sentinel-string assertion into two fragments (message is now spread across two string literals).
  - `test_backend_surfaces_and_logs_lifespan_startup_failure`: inject a no-op `migrations_runner` module so the test focuses on the uvicorn started=False lifespan path without a real DB call.
  - Result: **97 passed, 4 skipped, 0 failed.**
- Prior: WiX5 bootstrapper ext name; Burn PostgreSQL/PgSuperPassword wiring; SCM virtual-account names; native pywin32 SCM services; first-install DB/role bootstrap via DPAPI; ONEDIR payload validation; Burn duplicate CacheId; uvicorn no-console isatty fix; lifespan startup failure reporting.

## Backlog
- **P1 — Sign & Publish**: wire Authenticode signing + CloudFront release upload into Windows build/release scripts.
- **P2 — Core app workflows**: job/project workflows, field workflows, photos, measurements.

## Testing notes
- Windows build path is tested on Linux via pytest static/parser guards. Real MSI + execution smoke tests run only via GitHub Actions. Do NOT claim a build/installer fix "verified" unless CI or the corresponding suite confirms it.
- Credentials: `/app/memory/test_credentials.md`.

## Git workflow
User develops on remote `Asgard-Solutions/roofspan` and periodically asks to `git fetch` + `git merge --ff-only`. Cannot push back directly — use "Save to GitHub". Preserve `.git`/`.emergent`.
