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

## Backlog (Not Built — by design)
- **P0 (next): Office Phase 3 — Sales**: leads mgmt (expand), customers, inspections, estimates, quotes, acceptance, invoices (records only). Preserve Property → Lead → Customer → Inspection → Estimate → Quote → Acceptance → Invoice.
- **P1: Office Phase 4 — Operations**: jobs, scheduling, materials/inventory, low-stock, purchase orders, receiving.
- **P2: Office Phase 5 — Production Readiness**: full regression, backups/recovery, Alembic migrations, hardening.
- **P2: Mobile field app** (after Phase 5): Home/Leads/Map/Jobs/More, offline-safe writes.
- Explicit non-goals (Stripe/payments, accounting, portals, BI, PostGIS, queues, etc.) — do not build.

## Next Tasks
1. Begin Office Phase 2 (Territories + RentCast import) when approved.
2. Add Alembic migrations before Phase 5.
