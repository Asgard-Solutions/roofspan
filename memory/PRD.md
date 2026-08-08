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

## Backlog (Not Built — by design)
- **P0 (next): Office Phase 2 — Property Acquisition**: territories (GeoJSON), RentCast import (preview + est. request count + idempotent), property records, owner/renter, Do Not Knock, visits, property/visit → lead.
- **P1: Office Phase 3 — Sales**: leads, customers, inspections, estimates, quotes, acceptance, invoices (records only).
- **P1: Office Phase 4 — Operations**: jobs, scheduling, materials/inventory, low-stock, purchase orders, receiving.
- **P2: Office Phase 5 — Production Readiness**: full regression, backups/recovery, Alembic migrations, hardening.
- **P2: Mobile field app** (after Phase 5): Home/Leads/Map/Jobs/More, offline-safe writes.
- Explicit non-goals (Stripe/payments, accounting, portals, BI, PostGIS, queues, etc.) — do not build.

## Next Tasks
1. Begin Office Phase 2 (Territories + RentCast import) when approved.
2. Add Alembic migrations before Phase 5.
