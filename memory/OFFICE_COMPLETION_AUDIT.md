# RoofSpan Office — Completion Audit (2026-06)

> SOLE ACTIVE WORKSTREAM. No AWS/Terraform/Relay-prod/Mobile-expansion/website/installer-publish work
> until Office reaches CODE-COMPLETE (see gate at bottom) and is approved.

Environment note: after the fork, PostgreSQL 15 binaries were missing and were reinstalled against the
surviving persistent data dir (`/data/db/roofspan_pgdata`). Data intact (150 users), backend healthy,
owner login OK. Baseline backend regression should be re-run to reconfirm the last-known 212 pass.

## Architecture (as built)
- `frontend/` = RoofSpan Office local browser UI (CRA). Routes in `App.js`; shell nav in `AppShell.jsx`.
- `backend/` = FastAPI. Business routers + licensing client + Control Plane app (`cp_app`/`control_plane/`)
  + Relay (`relay/`) all mounted in one process (`server.py`). Local business DB = PostgreSQL via
  SQLAlchemy async; Control Plane uses its own DB `roofspan_control_plane`.
- `SubscriptionGuardMiddleware` blocks `/api/*` business routes unless effective state ∈ {ACTIVE, GRACE};
  allowlist = health/auth/subscription/license/billing/dev/control-plane/relay.
- Default `LICENSING_MODE=dev` → entitlement auto-issued locally ACTIVE with `LICENSING_DEV_SEATS=1000`.
  ⇒ In the running app the 5-seat product experience is NOT exercised.

## UI pages/routes (App.js + AppShell)
Dashboard `/`, Map `/map`, Leads `/leads` + `/leads/:id`, Customers `/customers`, Jobs `/jobs` + `/jobs/:id`,
Inventory `/inventory`, Finance `/finance`, **Reports `/reports` → `<Placeholder>` (DEAD FEATURE)**,
Admin (RequireSensitive): Users, Roles, Audit, Backups, Subscription, Settings. Entry = `/login`.

## Capability classification

### Foundation — PARTIAL
- Alembic migration-driven schema (fresh + existing), startup/shutdown, `/api/health`, static serve
  (`static_serve.mount_frontend`) — COMPLETE.
- `backend/.env` contains a preview `REACT_APP_BACKEND_URL` / `APP_BASE_URL` (preview host) and dev owner
  seed — must be templated out for packaged production. PARTIAL.

### First-run / company onboarding — MISSING (P0, the headline gap)
- No first-run detection, no `/setup` route, no bootstrap endpoint, no durable "initialized" flag.
- `seed_owner()` runs on EVERY startup from `ADMIN_EMAIL`/`ADMIN_PASSWORD` (dev owner) — this is the only
  way an Owner exists today; it is NOT a customer onboarding path and would ship a dev credential.
- No initial mandatory 5-seat / $245 checkout gating. No payment-pending/retry/restart-safe flow.
- `POST /api/billing/checkout` (owner) exists and, under `BILLING_MODE=stripe`, creates a Stripe Checkout
  session — but it is not wired into any first-run initialization/activation state machine.

### Authentication — PARTIAL
- login / logout / me / change-password (self) / reset-password (admin) — COMPLETE. In-memory brute-force
  lockout, HS256 JWT, disabled-user rejection — COMPLETE.
- Forgotten-Owner password recovery for production: MISSING. No email service in a local install; needs a
  designed secure local recovery path (flag, do not invent an insecure reset). P1.

### RBAC — COMPLETE
- Backend `require_roles`/`SENSITIVE_ROLES`/`MANAGE_ROLES` enforced across every router; frontend hiding is
  not the only protection. Sales strict-visibility on leads/jobs. (Re-verify with the E2E suite.)

### Users / seats — PARTIAL
- CRUD, roles, owner protections, race-safe `ensure_seat_available` (advisory lock) — COMPLETE in code.
- 5-seat initial + "6th user blocked" behavior is NOT reachable in default dev mode (seats=1000). Needs a
  real entitlement of 5 seats from onboarding to be exercised/tested. P0 (tied to onboarding).

### Company settings / integrations — COMPLETE (onboarding capture missing)
- `/api/company` GET/PUT (AppConfig singleton), map-config, integrations (RentCast/MapTiler AES-GCM,
  masked, Test Connection), satellite tile proxy. Reuse this Company model for setup step 1 (no 2nd system).

### Leads — COMPLETE  | Customers — COMPLETE  | Properties/Map — COMPLETE
- Full CRUD, assignment, status, conversion, photos, geojson pins, DNK, visits; MapLibre+OSM default with
  server-proxied MapTiler satellite (works without the paid key). Tested phases 2–3.

### Inspections — COMPLETE | Estimates — COMPLETE | Quotes — COMPLETE
- Line items + server totals + tax, numbering counters, idempotency + optimistic concurrency, quote accept
  → idempotent job handoff, duplicate-acceptance protection, edit-lock. Tested phase 3.

### Jobs — COMPLETE
- Create from accepted quote, list/detail, assignment, scheduling, job-materials, POs, photos, links.

### Inventory / purchasing — COMPLETE
- Materials CRUD + adjust, low-stock flag/filter, suppliers, POs, partial/full idempotent receiving.

### Finance / invoices — COMPLETE (verify UI)
- Invoices from accepted quote, status draft/issued/paid/void via `POST /invoices/{id}/status`, totals,
  links, RBAC. (Customer invoices ≠ RoofSpan seat billing.) Re-verify Finance.jsx status controls.

### Reports — MISSING (P0 blocker)
- `/reports` renders generic `Placeholder`. Must build a small K.I.S.S. reports page from existing data
  (e.g. pipeline counts, jobs by status, revenue from invoices, low-stock) OR remove from nav. No dead feature.

### Audit log — COMPLETE
- Sensitive actions recorded; `/api/audit` (sensitive roles); timestamp/user/action/entity.

### Backups — PARTIAL / HUMAN REQUIRED
- Local `pg_dump` backup + status card (`/admin/backups`, `/api/admin/backup-status`) + off-site copy +
  restore/restore-drill scripts (tested). No in-Office restore UI — restore is operator/script only.
  For packaged Windows, confirm a usable documented restore path (P1 / HUMAN REQUIRED for native).

### Subscription / billing — PARTIAL
- Recovery surface + status + seat +1/+5/+10, scheduled reduction, cancel/reactivate, refresh, offline
  cache, seat-compliance banners — COMPLETE (Stripe engine tested against sandbox). ACTIVE/GRACE/SUSPENDED/
  CANCELLED transitions tested at CP level.
- Missing: the INITIAL 5-seat purchase as part of first-run activation (see onboarding). P0.

### Office-side Mobile pairing — PARTIAL
- Backend `POST /api/admin/mobile/pair`, `GET /api/admin/mobile/devices`, `POST .../{id}/revoke` exist
  (sensitive-gated, proxy to CP). **No Office UI page** to generate a pairing code/QR, list devices, or
  revoke. P1.

### Office-side Secure Relay client — SEPARATE CONNECTOR SERVICE (correct architecture)
- `relay/tunnel_client.py::InstallationTunnel` (outbound, reconnect, challenge-response) exists and is
  tested. **Correction (2026-06):** it is intentionally NOT started inside the Office FastAPI backend.
  The desired architecture is a SEPARATE **RoofSpan Relay Connector** Windows service/process with a
  dedicated entrypoint `windows/winbuild/relay_entry.py` (loads the C1 installation identity, opens the
  outbound WSS tunnel, forwards to the local backend at 127.0.0.1:8001, reconnects) + a PyInstaller spec.
  P1 = AUDIT the Windows service/installer wiring: if the connector service is correctly installed and
  auto-started (WiX service `RelayConnector`), preserve it; if incomplete, finish the separate-service
  integration. Do NOT merge the tunnel into FastAPI just to satisfy wording.

### Packaging / runtime readiness — PARTIAL
- Static serve present; but: prod must not run the dev owner seed, must not depend on preview URLs, must use
  local Postgres + persistent ProgramData paths, and needs a complete prod config template. P1.

## Confirmed dev/phase artifacts to remove (P0/P1)
- `backend/routers/settings.py:126` dashboard `"phase": "Office Phase 1 — Foundation"` (customer-visible).
- `frontend/src/pages/Dashboard.jsx:40` renders `"Office Phase 1 — Foundation"`.
- `frontend/src/pages/Jobs.jsx:23` "Full scheduling & operations arrive in Phase 4." (stale/false).
- `frontend/src/pages/Placeholder.jsx` "Coming in … / after the Foundation phase" (Reports dead feature).
- `seed_owner()` dev owner from env as the only onboarding path (production must use the wizard).
- Preview URL in `backend/.env` (`APP_BASE_URL`) + `frontend/.env` (`REACT_APP_BACKEND_URL`) — dev-only.

## Completion backlog (ordered)

> **P0 STATUS (2026-06): COMPLETE & VERIFIED.** Items 1–8 implemented and tested — fresh-install E2E
> pytest `tests/test_onboarding.py` PASS (bootstrap, restricted pre-payment session, restart-safety,
> mock 5-seat activation, Owner+4 users / 6th blocked / +1 seat → 6th ok) + frontend testing agent
> iteration_12 100% (Reports + finance RBAC + setup gate + phase-artifact removal). Awaiting review
> before P1.

> **P1 STATUS (2026-06):** in progress (report+pause after each item). **P1-1 COMPLETE & VERIFIED** —
> Office Mobile Devices admin page (iteration_13 = 100%). **P1-2 COMPLETE & VERIFIED** — Windows Relay
> Connector service: found NO existing SCM wrapper (all 3 services were plain console exes → would fail
> SCM start/1053). Added a reusable pywin32 SCM host + wired ONLY the Relay connector; added ProgramData
> service-account ACLs. Backend + Updater have the SAME issue (reported, pending approval). 57/57 windows
> tests pass. Native SCM execution HUMAN REQUIRED. **P1-2b COMPLETE & VERIFIED** — Backend + Updater
> converted to the SAME pywin32 SCM host (graceful uvicorn shutdown for Backend; prompt cancel-based stop
> for Updater); one common service-host for all three; ACLs least-privilege (verified). 68/68 windows
> tests pass. Native SCM HUMAN REQUIRED; Program-Files-patch privilege model = DECISION REQUIRED (future).
> **P1-3 COMPLETE & VERIFIED** — Local Windows-Admin Owner recovery tool (`RoofSpanOwnerRecovery.exe`) +
> per-user `token_version` JWT invalidation (login/change-pw/admin-reset/recovery). Backend
> test_token_recovery.py 4/4 + onboarding still green; windows 75/75. Native UAC/DB HUMAN REQUIRED.
>
> **RECORDED DECISION (updater privilege, for P1-4/native updater):** Do NOT run RoofSpanUpdateService as
> LocalSystem to patch Program Files. Keep it restricted (download/verify/plan); when a verified update
> must modify Program Files, invoke a SMALL separate ELEVATED update-apply helper. Do not build that
> helper yet.
>
> **P1-4a COMPLETE & VERIFIED** — production config/security readiness: Owner seed DOUBLE-gated
> (LICENSING_MODE=dev AND ROOFSPAN_OWNER_SEED=enabled; impossible in production `http` mode); per-install
> generated+persisted JWT_SECRET + SECRETS_ENCRYPTION_KEY (ProgramData `secrets.env`, env wins, survives
> restart, never logged/committed); template finalized (LICENSING_MODE=http, BILLING_MODE=stripe, CP/Relay/
> update URLs, local 127.0.0.1 + local Postgres, no secrets); frontend API base falls back to same-origin
> for the packaged build. windows 81/81, backend affected 9/9, frontend build clean. **P1-4b (production
> Stripe onboarding completion) NOT started — pending approval.**
>
> **P1-4a (revised, blockers fixed) COMPLETE & VERIFIED:** (1) secrets now in a Backend-only ProgramData
> `secrets\` dir (WiX ACL: RoofSpanBackend read/write; Relay/Updater none) and bootstrap is **FAIL-CLOSED**
> — startup raises if generated secrets can't be durably persisted (no ephemeral keys). (2) New
> `RoofSpanBootstrap.exe` (WiX custom action BEFORE StartServices) generates a unique local DB password,
> provisions least-privilege `roofspan` role+db, and renders template → DEPLOYED `ProgramData\config\
> roofspan.env` before Backend starts; upgrade preserves existing creds. windows 87/87, backend 5/5 (+
> onboarding/token regression 5/5); app healthy. Native psql/MSI/ACL HUMAN REQUIRED.

### P0 — prevents a new customer from using RoofSpan
1. First-run detection + server-side "initialized" state (durable, race-safe) + `/setup` routing (uninit →
   wizard; init → login; setup endpoints refuse after init).
2. Setup Step 1 Company (reuse Company/AppConfig) + Step 2 initial Owner (owner role, seat #1; existing
   hashing/validation; block pre-payment multi-user).
3. Setup Step 3 initial mandatory 5-seat / $245-mo checkout via Office → CP → Stripe hosted Checkout;
   payment-pending state (poll/return/retry/error); restart-safe pending onboarding.
4. Payment-confirmed activation: entitlement → ACTIVE, 5 licensed seats, Owner usable, finalize init,
   route to login/authenticated session. Enforce login-before-payment lock (Option A/B).
5. Make the real 5-seat entitlement drive seat enforcement (Owner=1, +4 users, 6th blocked) — not dev 1000.
6. Reports page (real, K.I.S.S., existing data) OR removal — no dead `/reports`.
7. Remove customer-visible phase/dev artifacts (dashboard "phase", Jobs Phase-4 note, Placeholder copy).
8. Ensure env owner seed cannot bypass/conflict with production onboarding.

### P1 — required for initial production release
9. Office Mobile-pairing UI (generate code/QR, device list, revoke) over existing endpoints.
10. Audit/finish the SEPARATE **RoofSpan Relay Connector Windows service** (`windows/winbuild/relay_entry.py`
    + WiX `RelayConnector` service auto-start; outbound-only, reconnect, safe when cloud unavailable). Do
    NOT merge the tunnel into the FastAPI backend.
11. Forgotten-Owner secure recovery path for a local install — **DESIGN REQUIRED: STOP and present secure
    options** (no invented insecure email reset).
12. Production packaging config: no dev seed, no preview URLs, local Postgres + persistent paths, config
    template, auto-start services readiness.
13. Backups: confirm a usable in-Office or clearly-documented restore path (native validation HUMAN REQUIRED).
14. Office E2E/regression suite (fresh-install → bootstrap → mock 5-seat pay → activate → restart → seats
    2–5 ok / 6 blocked → +1 seat → 6 ok → lead→…→invoice → GRACE/SUSPENDED/recover → RBAC → backup).

### P2 — polish/reliability before code-complete
15. Verify Finance invoice status UI; empty states/validation/error handling sweep on every workflow page.
16. Consistent customer-friendly activation error copy (no installation/CP/JWS/relay jargon).

### DEFERRED (explicitly not for this gate)
- AWS/Terraform/ECR/KMS/ElastiCache/ACM/DNS; production Relay/Control Plane deployment; Mobile field
  feature expansion + store work; roofspan.io enhancements; installer publishing; native Windows/MSI build
  & Authenticode (HUMAN REQUIRED after code-complete).

## Definition of Office CODE-COMPLETE
No required customer workflow missing; no placeholder operational pages; first-run setup works; initial
subscription works in mock/dev billing; Owner can activate + log in; exactly 5 licensed seats; Owner + 4
users OK, 6th blocked until a seat is purchased; billing/seat changes work; lead→inspection→estimate→quote→
accepted job→invoice works with persisted relations; RBAC server-enforced; company settings work; backups
usable/documented; Office-side Mobile pairing works; local Relay client works; licensing/offline behavior
works; all Office tests pass; `yarn build` passes; no release-blocking dev/preview artifacts; code on GitHub.
Native Windows validation may remain HUMAN REQUIRED afterward and does NOT unblock other workstreams.
