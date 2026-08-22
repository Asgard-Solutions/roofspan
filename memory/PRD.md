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
- **ABC Supply** (Desktop only) — Third-Party Aggregator OAuth 2.0 (Auth Code + PKCE). Phased build; see below and `docs/ABC_SUPPLY_INTEGRATION.md`.

## ABC Supply Integration (RoofSpan Office / Desktop only)
Goal: connect each customer's own myABCSupply account for Account/Location/Product/Pricing/Ordering/Notifications. Mobile/website/control-plane untouched. Local PostgreSQL stays authoritative; Relay is webhook transport only (Phase 4). Provider layer: `backend/integrations/abc_supply/`. Router: `backend/routers/abc_supply.py` (`/api/integrations/abc/*`). UI: `frontend/src/pages/admin/AbcSupply.jsx` (`/admin/settings/abc`). Local mock ABC server mounted at `/api/abc-mock` when `ABC_MOCK_ENABLED=true` (must be under /api/* for K8s ingress).

- **[2026-06] Phase 1 COMPLETE & TESTED** — Foundation:
  - Provider abstraction (config/auth/client/exceptions/accounts/locations/schemas), OAuth 2.0 Auth Code + PKCE (S256) connect flow, encrypted (AES-GCM) token storage + auto-refresh + rotation, reconnect_required handling.
  - Account API (search + sold/bill/ship-to + contacts; retired ship-to filtering) and Location API (search branches, get branch).
  - Settings → Integrations → ABC Supply UI: config (env/client id/secret/redirect/webhook), Connect/Reconnect/Disconnect, Test connection, Ship-To + Branch default selection.
  - DB: `abc_integrations`, `abc_account_links` (migration `a7c3f1b9d2e4`). RBAC: config/connect = owner/administrator; read = +office; sales 403. Audit actions `abc.*`.
  - Local mock ABC server (OAuth + Account + Location) for dev/test. Tests: 10 unit + 22 HTTP integration pass; in-browser OAuth round-trip validated (iteration_23). Regression (phase4 + prod_infra) green.
  - **NEEDS ABC DOC/SANDBOX VERIFICATION**: real Sandbox client_id/secret + registered redirect URI; pricing/order/notification service path prefixes (`/api/pricing/v1`,`/api/order/v1`,`/api/notification/v1`) inferred, isolated in `config.py`.
  - Remaining phases: **P3** Ordering + real-time price refresh + idempotency + history/templates; **P4** Notification webhooks via Relay (ORDER_UPDATE/ORDER_INVOICED, idempotent).

- **[2026-06] Phase 2 COMPLETE & TESTED** — Product & Pricing:
  - Product API (`products.py`): `POST /api/product/v1/search/items` (contains/equals filters, embed branches, familyItems), item details, branch availability from embedded branches (Available/Not — never quantity-on-hand). Pricing API (`pricing.py`): `POST /api/pricing/v2/prices` (user token, ≤50 lines, qty/UOM/variation); $0.00 + per-line status normalized to price_status priced|unavailable.
  - PO integration: `PurchaseOrder`/`POLineItem` extended with nullable ABC metadata (migration `b2d5e7c9a1f3`); `POOut.pricing_warning`; `POST /api/purchase-orders/{id}/refresh-price` (explicit, optional apply, recomputes total, never silently overwrites manual). Changing Ship-To/branch clears gathered ABC pricing.
  - RoofSpan API: products/search, products/{item}, products/{item}/image (lazy proxy), pricing. Audit `abc.product.search/view`, `abc.price.lookup/refresh/apply`.
  - UI: `AbcProductSearch.jsx` inside `PODialog.jsx` ABC mode (Ship-To/branch context + unresolved-pricing warning). Generic POs unaffected.
  - Tests: 9 P2 unit + 14 P2 HTTP integration; **55/55 backend + full frontend flow pass** (iteration_24). RBAC (sales 403) + generic-PO regression green.
  - **NEEDS ABC DOC/SANDBOX VERIFICATION**: order/notification path prefixes; product image URLs (future release per docs); recent/frequent/favorite endpoints not implemented (out of P2 need).

- **[2026-06] Phase 3 COMPLETE & TESTED** — Ordering & Order Tracking:
  - Order API (`orders.py`, `/api/order/v2`): `POST /orders` (array body; `requestId`=submission_key), `GET /orders/{n}` & `?confirmationNumber=`; order history/templates (paths NEEDS VERIFICATION, mocked).
  - Submit flow (`purchasing.py`): `abc-submit-review` (validate + MANDATORY fresh price), `abc-submit` (row-lock + re-price + block on change unless accepted + idempotent by submission_key + persist identifiers + PO→ordered), `abc-refresh-status`, `abc-reconcile`. Statuses: confirmed|price_changed|validation_failed|already_submitted|pending|failed|unknown.
  - Duplicate/concurrency: `abc_order_submissions` (submission_key UNIQUE), one confirmed per PO, `SELECT FOR UPDATE` (verified 4-way concurrent → 1 order). Unknown-state (transport/502-504) preserved, never auto-retried; reconcile via history. Receiving/inventory unchanged.
  - PO order fields + migration `c3f6a8b1d2e5`; POOut exposes them (fix in iteration_26). UI: `AbcOrderPanel.jsx` (review→price-change→submit→status/refresh/reconcile) + "ABC Supply Orders" history tab.
  - Tests: 8 P3 unit + 14 P3 HTTP integration; **all pass; frontend flow pass (iteration_26)**. RBAC + generic-PO/receiving regression green. 89 ABC backend tests total.
  - **NEEDS ABC DOC/SANDBOX VERIFICATION**: order-history & template endpoint paths/filters; notification path prefix; real Sandbox credentials.
  - Remaining: **P4** Notification webhooks via Relay (ORDER_UPDATE/ORDER_INVOICED, idempotent, pull-based status already done).

- **[2026-06] Phase 4 COMPLETE & TESTED (MOCK VERIFIED)** — Notifications & Relay Webhook Ingress:
  - Notification API (`notifications.py`, verified `/api/notification/v2/webhooks`): register/list/get/patch/delete; ONE integration webhook (client-credentials), reconciled, max-5 respected, secret AES-GCM encrypted.
  - Public ingress `POST /api/webhooks/abc/orders` (`routers/abc_webhooks.py`): constant-time secret auth (ORDER_UPDATE Authorization; ORDER_INVOICED Authorization OR apiKey — NEEDS SANDBOX VERIFICATION), strong-identifier routing, durable encrypted queue, ACK then deliver.
  - Tables (migration `d4a7b2c8e1f6`): `abc_webhook_registrations`, `abc_order_routes` (registered on Phase-3 submit), `abc_webhook_deliveries` (offline→reconnect deliver-once, bounded retry, dead_letter), `abc_notification_events` (local idempotency, out-of-order guard), `abc_invoice_events`.
  - No auto-receiving/inventory changes; local PG authoritative; central holds transport metadata only. UI: `AbcOrderPanel` push status + ABC Activity + Invoice + auto-update note.
  - Tests: 6 P4 unit + 16 P4 API; **74/74 full ABC+Relay regression, 6/6 UI checks (iteration_27), zero issues.**
  - **NEEDS ABC DOC/SANDBOX VERIFICATION**: ORDER_INVOICED secret transport; live payload/status variations; order-history & template paths; real Sandbox credentials + production webhook registration.
  - **ABC Supply integration (Phases 1–4) COMPLETE.**

- **[2026-06] Delivery Address Review & Editor COMPLETE & TESTED** — Enhancement:
  - ABC Order panel (`AbcOrderPanel.jsx`) shows a "Deliver To" review (`abc-delivery-review`) + edit modal (`abc-delivery-editor`, 9 fields). Physical delivery override defaults from the linked Job's Property/Customer via `_default_delivery()` (READ-ONLY — never mutates Job/Property/Customer), is snapshotted into `abc_order_submissions.delivery`, exposed on `POOut.abc_delivery`, and shown on submitted orders (`abc-submitted-delivery`).
  - **Delivery override is OPTIONAL** (`_validate_delivery`, purchasing.py): empty override → order falls back to the ABC Ship-To account's registered address (submit builder omits `ship_to.address`); a PARTIAL override requires the full street/city/state/ZIP set (else `validation_failed`). Ship-To account is never changed by editing the delivery destination.
  - Fixed regression where delivery was hard-required at submit (broke "ship to Ship-To default" orders and P3/P4 fixtures with no linked job).
  - Tests: new `tests/test_abc_supply_delivery_api.py` (7 pass + 1 env-only skip) + 31/31 ABC unit regression + 7/7 frontend UI flow (iteration_28). NOTE: ABC HTTP suites share an in-memory mock store — run one file at a time (serial), not under xdist.
  - Optional future polish (pre-existing, not a regression): auto-switch the open panel to the submitted view after a confirmed submit without close/reopen.

- **[2026-06] ABC Order Panel Auto-Refresh COMPLETE & TESTED** — Frontend-only UX:
  - `AbcOrderPanel.jsx` now keeps a local `poState` (synced from the `po` prop) and refetches `GET /api/purchase-orders/{id}` right after a confirmed/already_submitted submit, deriving `submitted` from it. The panel transitions to the submitted view IMMEDIATELY (confirmation #, order #, status badge, submitted timestamp, and the exact persisted `abc_order_submissions.delivery` snapshot) with no close/reopen.
  - No-override submissions show `abc-submitted-delivery-default` (ships to ABC Ship-To default); overrides show the exact snapshot (never reconstructed from Job/Property). Unknown → renders `abc-unknown` immediately (no transition); failed/validation_failed → stays in review/error; price_changed → accept → immediate submitted view. Duplicate protection/pricing/delivery validation unchanged.
  - Tests: iteration_29 — 6/6 frontend checks (all 5 submit outcomes + generic PO regression), backend snapshot verification 100%, 38+1skip ABC unit regression green. Zero issues.


## DB schema (key tables)
`subscriptions`, `billing_events`, `pairing_tokens`, `device_credentials`.

## Cloud deploy (Railway)
- **roofspan-website** (marketing site): service Root Directory `/roofspan-website`, Nixpacks. Config at `roofspan-website/railway.json` (build `yarn build`, start `yarn serve`). Config-as-code path in Railway must be `/roofspan-website/railway.json` (absolute from repo root — it does NOT follow Root Directory).
- **Control Plane** (`cp.roofspan.io`, serves `backend/cp_asgi.py:app`): Dockerfile build via root `railway.json` → `deploy/railway/Dockerfile`. **Build context = repo root** (Dockerfile `COPY backend/ /app/`), so the Railway service Root Directory MUST be empty/repo-root. Required env vars documented in `deploy/railway/README.md` (CONTROL_PLANE_DATABASE_URL, Stripe, KMS, operator issuer/audience) — startup fails-closed without them.
  - **[2026-06] Recovered lost deploy files**: a Save-to-GitHub conflict merge (PR#2 `conflict_190826_0821`) left `main` without `deploy/railway/*`, root `railway.json`, and `backend/cp_asgi.py`; the Railway build then failed with `COPY backend/ → "/backend": not found`. Restored all 4 files from PR#2 onto current `main`; verified `cp_asgi:app` imports and exposes `/health`.
  - **[2026-06] Fixed CP startup crash `ModuleNotFoundError: psycopg2`**: Railway's `DATABASE_URL` is a plain `postgresql://…`, which made `create_async_engine` pick the sync psycopg2 dialect. Added `_to_async_url()` in `backend/control_plane/config.py` to normalize any `postgres://`/`postgresql://`/`+psycopg2`/`+psycopg` URL to the canonical `postgresql+asyncpg://` (the CP sync paths already convert away from `+asyncpg` to psycopg v3). Verified `cp_asgi` imports with a Railway-style URL.
  - **Healthcheck note**: `/health` returns 200 regardless of DB, but the startup event runs first. `require_production_config()` only enforces when `CP_ENV=production` and then requires: `BILLING_MODE=stripe`+`STRIPE_SECRET_KEY`+`STRIPE_WEBHOOK_SECRET`, `CP_KMS_SIGNING_KEY_ID` (if `ENTITLEMENT_SIGNER=kms`), and `CP_OPERATOR_ISSUER`+`CP_OPERATOR_AUDIENCE`. `init_control_plane()` also needs the DB reachable (bounded retry). For a first smoke test, leave `CP_ENV` unset so only the DB is required.

## Inventory Core 2.0 (multi-slice, in progress 2026-06)
### Slice 1 — Data model foundation + SupplierMaterial + ABC backfill (COMPLETE & TESTED)
- Master fields added to `materials` (manufacturer, brand, product_family, subcategory, color, size_variant, purchase_unit, conversion_factor, coverage_amount/unit, weight, upc, manufacturer_part_number, taxable, image_url). Legacy `abc_*` columns retained for backward compat.
- New `supplier_materials` (generic supplier↔material mapping, source of truth; `is_preferred` = user-selected primary, at most one active per material). `suppliers.integration_provider` added.
- Migration `a1b2c3d4e5f6` (down_revision f1a9c4b7d3e2): additive + backfill — seeds "ABC Supply" supplier and a preferred ABC SupplierMaterial for every existing abc-linked material.
- ABC add-to-inventory now also creates/links a SupplierMaterial (new + dedupe paths). New service `services/inventory_core.py` (ensure_supplier, upsert_supplier_material, set_preferred_supplier, compute_quantities, best_known_cost, preferred_supplier_material — quantities/preferred used in later slices).
- API: `GET /api/materials/{id}/suppliers`. Tests: `tests/test_inventory_core_slice1.py` (4 pass). Regression: ABC unit 31, catalog 13, api_integration 23, p2/p3/p4_api 44, delivery 7/1skip, phase5 subset — all green.
- Remaining slices: 2) quantities+ledger types, 3) Materials list revamp+filters, 4) Material Detail page, 5) Add Material (Search/Custom/CSV)+adjustment dropdown, 6) preferred-supplier mgmt+Best Known Cost+full regression.

## Supplier Framework (Part B) — IN PROGRESS (2026-06)
- **Slice 2 backend (Supplier model + CRUD/detail) DONE & TESTED**: Supplier expanded (supplier_type, account_number, sales_rep, ordering_email, website, payment_terms, default_branch, delivery_terms, minimum_order, freight_notes, tax_notes, integration_status, updated_at). APIs: `GET/POST /suppliers` (search/active filter), `GET /suppliers/{id}` (detail+products), `PATCH /suppliers/{id}`, `POST /suppliers/{id}/active?active=`. Secrets never exposed.
- **Slice 3 (Generic connector + ABC adapter) DONE**: `integrations/supplier_connectors.py` — `SupplierConnector` w/ Capability enum, `AbcSupplyConnector` (wraps existing ABC, declares catalog_search/live_pricing/branch_availability/online_order_submission/order_status/order_cancel/account_discovery), `ManualSupplierConnector` (no live caps). Capabilities surfaced on SupplierOut + facets. ABC code unchanged (all ABC tests green).
- **Slice 6 (Manual supplier products + price history) DONE & TESTED**: `POST/PATCH /supplier-materials` (manual mappings: item#, desc, uom, conversion, mfr part#, cost, lead time, notes). Immutable `supplier_price_history` snapshots on every manual cost change. `GET /supplier-materials/{id}/price-history`. Dedup now keys on supplier_id (fixed cross-supplier reuse). Best Known Cost = lowest active cost, shown separately; Preferred never changes from price. Audit on supplier + supplier_material + price changes.
- Migration `d4e5f6a7b8c9` (down c3d4e5f6a7b8): additive suppliers columns + supplier_price_history; backfill integration_status='manual' for non-ABC, supplier_type for ABC. Applied cleanly.
- Tests: `tests/test_supplier_framework.py` (3 pass). Regression green: inventory 13, hardening 6, ABC unit 31, catalog 13, api_integration 23.
- **REMAINING**: Slice 2 frontend (Supplier management UI + detail), Slice 4 (remove PO "ABC Supply" name-magic → Supplier-record select driving connector), Slice 5 (Universal Product Catalog UI + supplier comparison + price-freshness labels), Slice 7 (full frontend regression + UX polish).

### Part B FRONTEND (Slices 2,4,5,7) — COMPLETE & TESTED (2026-06)
- **Slice 2 Supplier Management UI**: `frontend/src/pages/Suppliers.jsx` wired to top-level `/suppliers` route + new sidebar nav item (`nav-suppliers`, between Inventory & Finance). List (search, active/inactive filter), Add/Edit manual supplier, Deactivate/Reactivate. Detail dialog shows full Overview (type/account/contact/rep/phone/email/ordering email/website/terms/branch/delivery/min order/freight+tax notes/capabilities/notes), Products (material, item#, UOM, cost, price-freshness badge, preferred star), and Recent Purchase Orders. Backend `GET /suppliers/{id}` now returns `purchase_orders` + enriched products (supplier_uom, price_status, price_updated_at).
- **Slice 4 PO Supplier Selection Refactor**: `PODialog.jsx` free-text supplier replaced with a Supplier **dropdown** loaded from `/api/suppliers`. ABC behavior now driven by `supplier.integration_provider === 'abc_supply'` (NO name-magic). `POIn` gained `supplier_id`; `create_po` resolves by `supplier_id` first (persists real supplier identity), falls back to `supplier_name` for legacy compat. Manual suppliers → standard material-line flow; ABC → Ship-To/Branch + live product search. Supports `initialSupplierId`/`initialMaterialId` presets for catalog "Add to PO".
- **Slice 5 Universal Product Catalog**: `AbcCatalog.jsx` transformed into `ProductCatalog.jsx` at `/inventory/catalog` (title "Product Catalog"); `/inventory/abc-catalog` now redirects there. Source selector: "All sources (RoofSpan)" + each supplier. All-sources shows master materials comparison table (Preferred Supplier vs Best Known Cost, distinct; price-freshness badges Live/Cached/Manual/Stale/Unavailable + timestamp — no invented stale threshold). ABC source preserves full ABC experience (sync, ship-to/branch context, availability, live pricing, dimensional handling, add-to-inventory). Actions: Add to Inventory, View Material, Add to PO (no estimate/quote/job actions). Backend `GET /materials` enriched with `primary_supplier_provider/status/updated_at`, `best_supplier_name/provider/status/updated_at`, `supplier_count` (new `inventory_core.best_known_supplier_material` + `supplier_material_count`).
- **Slice 7 UX/Regression**: obsolete "Type ABC Supply" copy removed; Inventory catalog button relabeled "Product Catalog". Backend regression green: supplier_framework+inventory core+hardening 22, ABC catalog 13 (serial), phase5+p1+p3_api 31. Frontend testing_agent iteration_34 = 100% (29/29 checks, zero bugs). No name-based ABC behavior remains in PO creation. ABC is now one supplier/source inside the Product Catalog.

## Inventory Core 2.0 — Hardening (Part A) COMPLETE & TESTED (2026-06)
- **CSV parser** moved server-side to Python's standards-compliant `csv` module (`routers/operations.py::_parse_csv_text`): quoted fields, commas inside quotes, escaped `""`, CRLF/LF, UTF-8 BOM, blank optional fields, header validation (needs sku or name). `/materials/import/preview` + `/commit` now accept `csv_text` (rows still supported). Preview/confirm workflow unchanged. Frontend sends raw file text.
- **DB preferred-supplier invariant**: migration `c3d4e5f6a7b8` resolves any existing duplicates non-destructively (keep earliest created preferred, unset rest, RAISE NOTICE count) then creates PARTIAL UNIQUE INDEX `uq_supplier_materials_one_active_preferred ON supplier_materials(material_id) WHERE is_preferred AND active`. Service `set_preferred_supplier` reordered (clear others → flush → set chosen) so the index is never transiently violated.
- Tests: `tests/test_inventory_core_hardening.py` (6 pass — CSV quoted/escaped/CRLF/header-validation + DB rejects 2nd active preferred via savepoint). Regression green: inventory 13, ABC unit 31, catalog 13, api_integration 23.
- **Part B (Supplier Framework & Universal Product Catalog) — NOT STARTED** (7 slices: Supplier model+UI, connector abstraction+ABC adapter, remove supplier-name magic in PO, Universal Product Catalog+comparison, manual supplier products+price history, preferred workflow, regression).

### Slices 2–6 — COMPLETE & TESTED (2026-06)
- Slice 2 Quantities & Ledger: `services/inventory_core.compute_quantities` (On Hand/Reserved/Available=OnHand−Reserved/On Order=Σmax(qty−received,0) on open POs/Required=active-job plans/Projected=OnHand+OnOrder−Required). Structured TXN_TYPES; `job_reservation` never reduces On Hand. Migration `b2c3d4e5f6a7` adds inventory_txns.job_id+location. Endpoint `GET /materials/{id}/quantities`.
- Slice 3 Materials List 2.0: `GET /materials` returns quantities + preferred supplier + best_known_cost + status, with filters q/category/manufacturer/supplier_id/active/low_stock; `GET /materials/facets`. Frontend Inventory materials tab revamped (new columns + filter bar + row→detail).
- Slice 4 Material Detail: `GET /materials/{id}/detail` (overview, quantities, suppliers, open POs, jobs, txn history). Frontend `MaterialDetail.jsx` at /inventory/materials/:id.
- Slice 5 Add Material/CSV: 3-mode add (Create custom / Search supplier catalog / Import CSV). `POST /materials/import/preview` + `/commit` (create + update-by-SKU, preview of actions, confirm_updates required + UI checkbox — no silent overwrite).
- Slice 6 Adjustment+Preferred: adjust reason is a structured dropdown + notes (validated ∈ TXN_TYPES). `POST /materials/{id}/suppliers/{sm_id}/prefer` (exactly one active preferred/material). Best Known Cost shown separately from preferred supplier.
- Tests: `test_inventory_core_slice1.py` (4), `test_inventory_core_slice2_6.py` (9, incl. exact quantity math + reservation invariant + CSV confirm). Frontend testing_agent iteration_33 = 100% (10/10). Full ABC + business-workflow regression green.

## ABC branch selection fix (2026-06)
- **Bug (live sandbox):** after connecting real ABC and choosing a Default Ship-To (Big Pine 2010466-2), the Default Branch dropdown was empty → couldn't save a branch → ABC Catalog blocked with "Select a Branch".
- **Root cause:** `GET /branches?ship_to=` re-fetched the Ship-To DETAIL endpoint, whose response omits the branch list for some accounts (even though the account SEARCH result that populated the picker had branches).
- **Fix:** `list_branches(ship_to)` now sources branches from the account SEARCH result first (`list_ship_to_accounts` match), then falls back to Ship-To detail, then to a Location API branch search by the ship-to's state. Frontend `AbcSupply.jsx` also seeds the branch dropdown from the selected account's embedded branches while the API resolves. Mock models the real case via Ship-To `2010466-2` (search has branches; detail omits them).
- **Tests:** new `test_06b_branches_when_shipto_detail_omits_branches` + updated accounts-filter test; full ABC regression green; frontend verified 100% (iteration_32).

## ABC Supply Vendor Catalog (Inventory) — COMPLETE & TESTED (2026-06)
- **Goal:** browse/search the ABC catalog inside Inventory, see branch availability + customer pricing, and "Add to Inventory" to create a RoofSpan Material that preserves the ABC item identity for future ordering. Catalog = VENDOR data, kept separate from RoofSpan on-hand stock; branch availability is never treated as quantity-on-hand.
- **DB:** new `abc_catalog_items` (vendor cache, unique `abc_item_number`, `material_id` link, `raw_data`, `status` active/inactive, `branch_numbers`), `abc_catalog_sync` (singleton sync status). Material gained nullable `vendor`, `abc_item_number` (indexed), `abc_catalog_item_id`, `abc_uom`, `abc_metadata`. Migration `f1a9c4b7d3e2` (down_revision d4a7b2c8e1f6), additive-only.
- **API (all /api/integrations/abc, RBAC owner|administrator|office):** `GET /catalog` (q,page,page_size,category,active_only,branch,live — serves local cache, warms/queries ABC live when empty/requested), `GET /catalog/{item_number}`, `POST /catalog/{item_number}/add-to-inventory` (create OR dedupe by abc_item_number; on-hand defaults 0; never duplicates identity), `POST /catalog/sync[?full]` (background full/incremental via `sinceLastModifiedDateTime`; upsert; inactive→marked inactive, never deleted), `GET /catalog/sync/status`. Pricing reuses `POST /pricing` (batch, visible page). ABC APIs: POST /product/v1/search/items (live search), GET /product/v1/items (full sync), POST /pricing/v2/prices; availability derived from embedded branches (ABC exposes no stock qty).
- **UI:** `/inventory/abc-catalog` (`AbcCatalog.jsx`) — Ship-To/Branch context, Sync button+status, search (description or item#), paginated results with availability badges (Available/Not at branch/Unknown — never a number), batch customer pricing, Add to Inventory / In Inventory. Entry button on Inventory Materials tab. Disconnected/needs-selection banners route to Settings → ABC Supply.
- **Tests:** new `tests/test_abc_supply_catalog_api.py` (13 pass: mapping, sync, active/inactive, search by desc+item#, pagination, add+dedupe, ABC identity preserved, on-hand=0, no token leak, sales 403). Full ABC regression green (31 unit + 22 + 14 + 14 + 16 + 7/1skip). phase4/phase5 (materials/PO/receiving) 21 pass. Frontend UI 100% (iteration_31). No real ABC credentials committed (only synthetic mock values in tests).

## Live ABC Sandbox — OAuth redirect URI (2026-06)
- **User hit ABC/Okta HTTP 400 on Connect** ("'redirect_uri' must be a Login redirect URI in the client app settings") when using their REAL ABC sandbox credentials from their local Windows install. **Root cause: external ABC Developer Portal config**, NOT a RoofSpan bug — the redirect URI `http://127.0.0.1:8001/api/integrations/abc/callback` was not registered byte-for-byte in the ABC app's "OAuth 2.0 Redirect URI(s)". RoofSpan already sends the configured URI correctly (PKCE S256, Basic-auth token exchange) — confirmed via integration_expert.
- **Fix = user action:** register that exact URI (scheme `http`, host `127.0.0.1` not `localhost`, port 8001, path, no trailing slash) in the ABC portal, then retry. If 400 persists after saving, wait/retry or have ABC Support confirm portal→Okta propagation.
- **In-app aid added** (`frontend/src/pages/admin/AbcSupply.jsx`): prominent amber callout (shown when not connected & not mock) with the exact effective redirect URI + Copy button, plus an always-visible Copy affordance on the OAuth Redirect URI config field. Verified iteration_30 (100%, mock-mode gating correct, no regressions).

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

## Estimating Modernization — COMPLETE & TESTED (2026-06)
Goal flow: Supplier Cost → RoofSpan Material → Estimate → Waste/UOM/Assemblies → Markup/Margin → Customer Quote. Customer selling price is NEVER the same as supplier cost; historical estimates/quotes retain pricing snapshots.
- **Architecture**: `Material → SupplierMaterial → Supplier → SupplierConnector`; `Estimate → EstimateLineItem (catalog-linked, cost/waste/markup/snapshot/assembly fields)`; `Assembly → AssemblyItem`; `PriceBook → PriceBookEntry`; `Quote → QuoteLineItem (+ package_id)` and `Quote → QuotePackage` (Good/Better/Best).
- **Migration `e5f6a7b8c9d0`** (down `d4e5f6a7b8c9`): additive-only. Extends `estimate_line_items` (material_id, supplier_material_id, line_kind, base/material/labor/equipment/subcontract cost, measured_quantity, waste_percent, order_quantity, purchase_unit, conversion_factor, markup_percent, selling_unit_price, cost snapshot provenance, assembly snapshot); backfills selling_unit_price=unit_price & measured_quantity=quantity. New tables: `assemblies`, `assembly_items`, `price_books` (+partial-unique one-default index), `price_book_entries`, `quote_packages`; `quotes` gains multi_package + accepted_package_id; `quote_line_items` gains package_id + internal cost snapshot. Seeds one neutral default 'Standard' price book.
- **Calc engine** `services/estimating.py` (server-authoritative): calculated_quantity=measured*(1+waste/100) (measured NEVER overwritten); markup%=(price-cost)/cost*100 vs margin%=(price-cost)/price*100 (distinct); order_quantity=ceil(calc_qty*conversion_factor) (explicit, never guessed; validation-safe None when no conversion); summarize() → material/labor/equipment/subcontract/estimated_total_cost, selling, gross_profit, gross_margin%.
- **APIs**: estimates `GET/POST/PUT` now snapshot cost + compute lines + RBAC-gated `cost_summary`/`can_see_cost` (owner/admin/office only; sales sees selling price only); `GET /estimates/{id}/cost-refresh/preview` + `POST .../apply` (explicit, never auto-applies, optional sell recalc). `POST /quotes` snapshots SELLING prices (+internal cost hidden from output) and supports `multi_package`+`packages`; `POST /quotes/{id}/accept` records `accepted_package_id`. New router `/api/estimating`: assemblies CRUD + `/expand` (snapshots version+cost), price-books CRUD + `/entries`, one-active-default enforcement.
- **UI**: dedicated `/estimates/:id` Estimate Editor (Add Item → Search Product Catalog / Add Assembly / Add Custom Line; measured/waste/qty, cost/markup/sell with two-way calc, cost/margin summary gated, Cost Refresh dialog, Generate Quote). New top-level 'Estimating' sidebar (owner/admin/office): Assemblies + Price Books management pages. LeadDetail: New estimate → editor; multi-package quote display + package-selecting acceptance.
- **Tests**: `tests/test_estimating_modernization.py` 12 pass (calc math incl 31.5+12%→35.28, markup≠margin, ceil order qty, waste summary, default price book, assembly expand+version bump, quote cost-hidden snapshot, multi-package accept, cost-refresh no-autoapply, legacy custom line). Regression: phase3 14, phase5 7, supplier framework 3, inventory core 13+6 — all green (hardening's DB-invariant test must run in isolation due to a cross-file async event-loop teardown artifact). Frontend testing_agent iteration_35 = 100% (13/13 features), zero bugs.
- **Known limitations**: Price Book rules are managed but NOT yet auto-applied to editor lines (adding a catalog product defaults selling_unit_price=snapshot cost until markup/price set) — candidate next enhancement. Job Material Automation / Smart Purchasing NOT started (deferred per instruction).

## Git workflow (legacy note)
User develops on remote `Asgard-Solutions/roofspan`; use "Save to GitHub". Preserve `.git`/`.emergent`.
