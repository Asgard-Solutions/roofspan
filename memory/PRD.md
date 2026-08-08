# RoofSpan — Product Requirements (Living Doc)

## Original Problem Statement
RoofSpan is a **local roofing-company operating application** for ONE roofing company. Not SaaS, not multi-company. Architecture: **Office Browser → FastAPI Backend → PostgreSQL** (authoritative source of truth). A separate native Mobile field app comes LATER. Governing principle: **K.I.S.S.** Build order: Office Phases 1→5, then Mobile.

## Key Architecture Decisions
- **Database: PostgreSQL** (user requirement; treated as DECISION REQUIRED). Confirmed Emergent can run a local PostgreSQL 15 in-container under supervisor (program `postgresql`), connected via SQLAlchemy async + asyncpg. `DATABASE_URL` in `backend/.env`. This preserves Office Browser → FastAPI → PostgreSQL exactly. (Note: MongoDB remains the platform-managed DB and is unused; local Postgres persistence is container-local, consistent with the "local application, company owns its data" model.)
- **Auth: JWT** email/password, bcrypt hashing, Bearer token. Roles: owner, administrator (sensitive) / office, sales (standard). Backend independently enforces RBAC via `require_roles`.
- **Secrets: AES-GCM** at rest (`SECRETS_ENCRYPTION_KEY`), plaintext never returned; masked `••••••••XXXX` only.
- **Maps: MapLibre GL + OpenStreetMap** default; **MapTiler BYOK** satellite proxied server-side (`/api/map/tiles/satellite/{z}/{x}/{y}`) so the key never reaches the browser. No Mapbox/Google.
- No Celery/Redis/RabbitMQ/PostGIS. Table creation via SQLAlchemy `create_all` (non-destructive) for Phase 1.

## User Personas
- **Owner/Administrator** — runs the company: users, roles, integrations, settings, audit.
- **Office** — day-to-day office workflows (future phases).
- **Sales** — field-oriented; leads/properties/jobs (future phases).

## Implemented (2026-08-08) — Office Phase 1: Foundation
- PostgreSQL foundation + FastAPI backend, startup table creation, idempotent **owner seed** (pjacobsen@asgardsolution.io).
- **Auth**: POST /api/auth/login, GET /api/auth/me, POST /api/auth/logout; in-memory brute-force lockout.
- **Users**: list/create/update (role, active), reset-password, roles metadata; owner-only owner-role guard; self-deactivation guard; 409 dup-email.
- **Audit log**: every sensitive action recorded; GET /api/audit (owner/admin).
- **Integrations** (RentCast, MapTiler): encrypted secret set/clear, masked display, enable/disable, Test Connection.
- **Map config** + **Company profile** + **Dashboard summary** endpoints.
- **Office shell**: left sidebar nav (Dashboard, Leads, Map, Customers, Jobs, Inventory, Finance, Reports, Administration). Admin section owner/admin-only.
- **Pages**: Login, Dashboard, Map (MapLibre+OSM), Admin → Users/Roles/Audit/Settings(tabs: Integrations, Map, Company). Placeholder pages for other nav areas.
- Verified: backend 19/19 pytest; frontend flows (login, RBAC hide/deny, users CRUD, settings tabs, masked keys, map) via testing agent.

## Implemented (2026-08-08) — Office Phase 2: Property Acquisition
- **Workflow verified end-to-end**: Create Territory → Draw on map → Preview import → Confirm import → Properties as pins → Open property → Owner/Renter → Do Not Knock → Visit → Convert to Lead.
- **Territories**: CRUD (`/api/territories`), simple GeoJSON Polygon geometry (no PostGIS), on-map polygon drawing, per-territory property_count. Delete preserves properties (sets territory_id=NULL).
- **RentCast import** (server-side only): `/api/territories/{id}/import/preview` (est. request count + sample) and `/import` (in-process asyncio tracked job, no queue). Idempotent upsert keyed on external_id (re-import = 0 created / N updated). NO real key configured yet → uses a clearly-labeled **SAMPLE/DEMO data generator**; real RentCast client + Test Connection implemented and auto-used once a key is added in Settings.
- **Properties**: list, `/geojson` for map pins (blue = normal, red = Do Not Knock), detail with owner/renter contacts + visit history. DNK toggle (`PATCH`).
- **Visits**: `/api/properties/{id}/visits` (outcome + notes; `do_not_knock` outcome flips the flag).
- **Leads**: `/api/properties/{id}/convert-to-lead` + `/api/leads` list with status pipeline (new→working→qualified→lost→converted). Leads nav page now functional.
- **Account**: self-service `POST /api/auth/change-password` (foundation completion, not expanded).
- **Branding**: RoofSpan wordmark on login, app-icon in sidebar, favicon + apple-touch-icon applied (assets in `/frontend/public/brand`, unaltered).
- **RBAC**: MANAGE_ROLES (owner/admin/office) for territories+imports; FIELD_ROLES (all) for view/visits/DNK/leads. Backend-enforced; sales blocked from manage endpoints (403).
- Verified: Phase 2 backend 17/17 pytest + Phase 1 19/19; UI flows verified via testing agent (iteration_2).

## Implemented (2026-08-08) — Office Phase 3: Sales
- **Workflow verified end-to-end**: Lead → Create/Link Customer → Inspection → Estimate → Quote → Acceptance → Job handoff → Invoice.
- **Leads**: enriched detail (`GET /api/leads/{id}` returns property_address, owner_name, visits, customer link); Leads list rows open a per-lead Sales workspace (`/leads/:id`) that drives the whole pipeline.
- **Customers**: CRUD + `from-lead` conversion (links property, flips lead to converted). Many properties per customer via association table. Customers nav page (list/search/create).
- **Inspections**: tied to lead/customer/property (date, inspector, condition, findings, recommended work).
- **Estimates & Quotes & Invoices**: line items (desc/qty/unit/price), **server-side totals** (subtotal/tax%/total). Numbers via counter table (EST-/QUO-/INV-/JOB-). Idempotency-Key on estimate & invoice creation; optimistic concurrency (version + If-Match → 409) on estimate/quote edits.
- **Quote → Job handoff**: `POST /quotes/{id}/accept` records acceptance (accepted_by/at/name) and creates a Job **idempotently** (unique quote_id → re-accept returns same job). Accepted quotes are edit-locked.
- **Invoices (records only)**: created from an **accepted** quote (guarded server-side), copies items/totals, links job; status draft/issued/paid/void. NO payment processing/accounting. Finance page (Quotes + Invoices tabs); Jobs page lists handoffs.
- **RBAC**: owner/admin/office = full incl. acceptance/jobs/invoices; sales = leads/customers/inspections/estimates/quotes (403 on invoices, acceptance, territories). Backend-enforced; UI hides unavailable actions.
- **Audit**: estimate/customer/quote.accept/invoice actions logged.
- Verified: backend 50/50 pytest (14 Phase 3 + 17 Phase 2 + 19 Phase 1); full browser Sales workflow + Jobs/Finance/Customers + sales RBAC UI (iteration_3). No blocking defects.

## Implemented (2026-08-08) — Office Phase 4: Operations
- **Workflow verified end-to-end**: Job → Schedule → Add/Review Materials → Check Inventory → Create PO → Receive (partial → remaining) → Inventory updates.
- **Materials catalog** (`/api/materials`): CRUD + `POST /materials/{id}/adjust` (+/- stock, negative-below-zero guarded). `low_stock` flag = quantity_on_hand <= reorder_threshold; list supports `low_stock=true` filter.
- **Suppliers** (`/api/suppliers`): list/create.
- **Job scheduling** (`PATCH /api/jobs/{id}`): status pipeline (created/pending/scheduled/in_progress/completed/cancelled) + scheduled_start/end, schedule_notes, assigned_to. Audit `job.update` writes ISO datetimes via `model_dump(mode="json")` — **datetime-JSONB serialization bug FIXED & verified**.
- **Job materials** (`/api/jobs/{id}/materials`): add/list/delete; JobDetail returns materials[] (planned qty, on-hand, low-stock) + purchase_orders[].
- **Purchase Orders** (`/api/purchase-orders`): create with line items (server-computed total, PO-xxxx number), list/filter by job_id, get, status.
- **Receiving** (`POST /api/purchase-orders/{id}/receive`): partial + full; increments material stock via `inventory_txns`; **Idempotency-Key protects against double-count**; over-receive after full → 400.
- **RBAC**: MANAGE_ROLES (owner/admin/office) for materials-create, job PATCH, PO create/receive; sales = read-only on materials, 403 on manage. Backend-enforced.
- **Frontend**: Inventory page (materials + Purchase Orders tab + ReceiveDialog), JobDetail page (schedule, job materials, PODialog). Nav `nav-inventory`, route `/jobs/:id`.
- Verified: backend 19/19 pytest (phase4_test.py); frontend Playwright full ops flow (iteration_4). No blocking defects. **Paused before Phase 5 per user.**

## Implemented (2026-08-08) — Office Phase 5: Production Readiness
- **Alembic migrations = authoritative schema path.** `create_all` removed; startup runs `alembic upgrade head` via `migrations_runner.run_migrations()`. Revisions: `61f7ea11c757` baseline (all Phase 1–4 tables), `7a95fb788bfd` hardening (unique `uq_materials_name`). Verified: fresh DB builds full schema from history; existing dev DB migrated forward non-destructively (stamped baseline → hardening); model↔schema parity (empty autogenerate diff). Config in `backend/alembic.ini` + `backend/alembic/env.py` (async URL → sync `psycopg`).
- **Startup robustness (fixes 502-hang found in iteration_5):** `ensure_database()` self-heals a missing DB (auto-CREATE when role can connect) and **fails loudly in ~5s** with an actionable error if the server/role is unreachable (no more silent hang). One-time role bootstrap: `backend/scripts/bootstrap_postgres.sh`. Documented in `/app/OPERATIONS.md`.
- **Approved Operations hardening (+ tests):** PO line `quantity > 0` (422); material `quantity_on_hand`/`reorder_threshold` `>= 0` (422); material name normalized (trim + collapse whitespace) + case/space-insensitive uniqueness (409) backed by DB `uq_materials_name`; **atomic idempotent receiving** — Idempotency-Key row reserved before inventory mutation (flush + IntegrityError guard) so concurrent/repeat requests never double-post; key reuse for a different PO → 409.
- **Security review (pass):** bcrypt passwords; HS256 JWT (strong non-default secret, expiry, `type=access`); disabled users rejected (401) even with a valid token; brute-force lockout (5/15min); integration API keys AES-GCM encrypted at rest, only masked `••••LAST4` ever returned (plaintext never); MapTiler proxied server-side; RBAC backend-enforced; DB creds never sent to browser.
- **Backup/recovery (actually tested):** `pg_dump -Fc` → restore into isolated DB → row counts matched exactly (users/materials/audit) + Alembic version preserved. Data dir `/var/lib/postgresql/15/main`.
- **Restart/persistence (actually tested):** after Postgres + backend restart — users, encrypted secrets (AES key preserved), audit, materials, and the hardening constraint all persisted; auth worked. **Known limitation:** persistence across full container/pod redeploy requires the PG data dir on a persistent volume (documented; human action for production).
- **Accessibility:** added `DialogDescription` to all flagged dialogs (Inventory material/adjust, JobDetail job-material, Customers add, MapView save-territory) — Radix a11y warnings eliminated (verified in console). Benign dev-only ResizeObserver overlay noise documented, not a production issue.
- **Full regression:** **76/76 backend pytest PASS** (19 P1 + 17 P2 + 14 P3 + 19 P4 + 7 P5). One documented command: `cd /app/backend && python -m pytest tests/ -q` (a `tests/conftest.py` auto-loads `REACT_APP_BACKEND_URL` from the frontend .env). Frontend production build (`yarn build`) succeeds. Browser flows for all phases verified (iteration_5).

## Backlog (Not Built — by design)
- **P2 sales polish (backlog)**: idempotency-key TTL sweep; invoice status state-machine; double-submit dedup on quote generation; customer detail drawer with full history.
- **P2 ops polish (backlog)**: SQL-side low_stock filter + `low_stock=false` semantics; job PATCH optimistic concurrency + status state-machine; supplier N+1 (joinedload) & active filter.
- **Product enhancements (explicitly NOT approved for Phase 5)**: Low-Stock dashboard tile; "Jobs This Week" schedule board.
- **P2: Mobile field app** (after approval): Home/Leads/Map/Jobs/More, offline-safe writes.
- Explicit non-goals (Stripe/payments, accounting, portals, BI, PostGIS, queues, SSO/MFA/OAuth) — do not build.

## Deployment Durability (2026-08-08) — production preparation (no product changes)
- **PostgreSQL persistence**: relocated PGDATA from the ephemeral overlay to the **persistent volume** at `/data/db/roofspan_pgdata` (updated `postgresql.conf data_directory` + supervisor `-D`). **Destructive test PASSED**: created a record → deleted the old overlay dir → restarted PG from the persistent path → record survived, app normal.
- **Automated backups**: platform cron `nightly-db-backup` (`.emergent/crons.yml`, 08:00 UTC) → `POST /api/cron/backup` (bearer `WEBHOOK_CRON_SECRET`, constant-time compare, backgrounds the work) → `backend/scripts/backup_db.sh` (`pg_dump -Fc`). Stored on persistent volume `/data/db/roofspan_backups/`, timestamped, atomic `.partial`→`mv`, **14-dump retention**, logged to `backup.log` + `LAST_BACKUP_STATUS`, non-zero exit on failure. Verified: cron auth 401/200, background dump created.
- **Restore drill**: `backend/scripts/restore_drill.sh` restores latest dump into isolated `roofspan_restore_drill`, checks tables/users/alembic/key-tables, prints PASS/FAIL, drops the drill DB, never touches production. **Verified PASS** (tables=29, alembic head; production untouched).
- **Secrets recovery**: `SECRETS_ENCRYPTION_KEY` documented as an off-container recovery requirement kept OUT of the DB backup (needed to decrypt stored provider keys). One-time role bootstrap: `backend/scripts/bootstrap_postgres.sh`.
- **Runbook**: `/app/OPERATIONS.md` rewritten (start/persistence/env-secrets/backup/restore/drill/alembic/restart/PG-unavailable/pre-rebuild-preserve).
- **Verification reruns**: backend regression **76/76**; frontend production build clean; cron+regression sanity **10/10** (iteration_6). No defects.
- **HUMAN ACTION (deploy)**: (1) if a from-scratch container rebuild recreates system config from the base image, re-apply the two PGDATA path settings or restore from backup — backups+key are the guaranteed recovery set; (2) periodically copy `/data/db/roofspan_backups/*.dump` + `SECRETS_ENCRYPTION_KEY` truly off-pod.

## Next Tasks
1. **Deployment prep complete — PAUSED. Awaiting explicit approval before the RoofSpan Mobile Field phase (do NOT auto-start).**
2. Wire real RentCast key when provided (Settings → Integrations); SAMPLE/DEMO until then.
3. Optional off-site backup copy to external storage once the user picks a target.
