# ABC Supply Integration (RoofSpan Office / Desktop)

> Scope: **RoofSpan Office / Desktop only** (local FastAPI + React + local PostgreSQL). No ABC
> functionality is added to RoofSpan Mobile, iOS, Android, or the marketing website. The public
> RoofSpan Relay is extended **only** to receive ABC webhooks (Phase 4). Local PostgreSQL remains
> authoritative for all business/purchasing data.

Official ABC documentation: https://apidocs.abcsupply.com/

## Architecture

```
RoofSpan Office UI (React)
        │  /api/integrations/abc/*
        ▼
Local FastAPI  ──►  integrations/abc_supply/  ──►  ABC Supply APIs (or local mock)
        │
        ▼
Local PostgreSQL  (abc_integrations, abc_account_links, + existing purchasing tables)
```

Webhooks (Phase 4):
```
ABC Supply ──HTTPS──► RoofSpan Relay (/webhooks/abc/order) ──existing tunnel──► Customer RoofSpan Office ──► local PostgreSQL
```
The Relay is transport-only and never the source of truth for ABC orders.

## Integration model — Third-Party Aggregator

RoofSpan is a commercial app used by many independent ABC customers. Each customer connects **their
own** myABCSupply account via OAuth. RoofSpan does **not** use one shared ABC account.

## Provider layer (`backend/integrations/abc_supply/`)

| File | Purpose |
|------|---------|
| `config.py` | Centralized environment/URL/scope configuration + mock resolution |
| `auth.py` | OAuth 2.0 helpers: PKCE (S256), authorize params, code exchange, refresh, client credentials |
| `client.py` | Async HTTP client: bearer injection, timeouts, request IDs, bounded retries + 429 Retry-After, error normalization |
| `exceptions.py` | ABC error → RoofSpan user-safe error normalization |
| `accounts.py` | Account API (search + sold/bill/ship-to + contacts; retired ship-to filtering) |
| `locations.py` | Location API (search branches, get branch) |
| `products.py` / `pricing.py` / `orders.py` / `notifications.py` | Added in Phases 2–4 |
| `schemas.py` | RoofSpan-facing request/response DTOs |
| `mock_server.py` | Local mock ABC server for development/testing |

## OAuth 2.0

Two documented patterns are used (source: https://apidocs.abcsupply.com/authorization-methods/):

- **Authorization Code + PKCE (S256)** — user token, for account/pricing/order actions on behalf of
  the connected customer. Requests `offline_access` to receive a refresh token.
  - Scopes: `account.read pricing.read order.read order.write product.read location.read notification.read notification.write offline_access`
- **Client Credentials (Third-Party Aggregator)** — application-level, for `location.read`, `product.read`,
  `notification.read`, `notification.write`. **Never** used for customer pricing or user-scoped actions.

Token lifetimes (per ABC): access token 30 min; refresh token effectively unlimited if used within 30
days. RoofSpan auto-refreshes ~60s before expiry and rotates the refresh token when ABC returns a new
one. On refresh failure the connection is marked `reconnect_required`.

### Endpoints (base URLs)

| Environment | OAuth base | API base |
|-------------|-----------|----------|
| Sandbox | `https://sandbox.auth.partners.abcsupply.com/oauth2/aus1vp07knpuqf6Xz0h8` | `https://partners-sb.abcsupply.com` |
| Production | `https://auth.partners.abcsupply.com/oauth2/ausvvp0xuwGKLenYy357` | `https://partners.abcsupply.com` |

- Authorize: `{oauth_base}/v1/authorize`  ·  Token: `{oauth_base}/v1/token` (HTTP Basic `clientId:clientSecret`, form-encoded).

## Environment variables

Per-install config is stored (encrypted where sensitive) in the `abc_integrations` table and edited in
the UI — **not** in source. The following process env vars control behavior:

| Var | Meaning |
|-----|---------|
| `ABC_MOCK_ENABLED` | When true, mounts the local mock ABC server at `/abc-mock` and routes all ABC calls to it |
| `ABC_MOCK_INTERNAL_BASE` | Loopback base for server-to-server mock calls (default `http://127.0.0.1:8001`) |
| `ABC_OAUTH_BASE_URL` / `ABC_API_BASE_URL` | Optional overrides of the documented base URLs (non-mock) |

Per-install settings (via Settings → Integrations → ABC Supply): `environment` (sandbox|production),
`client_id`, `client_secret` (encrypted), `redirect_uri`, `webhook_public_url`.

## URLs to register with ABC

- **OAuth redirect URI** (loopback into the local RoofSpan FastAPI):
  `http://127.0.0.1:<configured-port>/api/integrations/abc/callback`
  (In this hosted preview it resolves to `<REACT_APP_BACKEND_URL>/api/integrations/abc/callback`.)
- **Webhook public URL** (public RoofSpan Relay, Phase 4): e.g. `https://relay.roofspan.io/webhooks/abc/order`

Both are configurable; do not hardcode final production domains/ports.

## Sandbox → Production transition

1. Obtain ABC Sandbox `client_id`/`client_secret` from the ABC Developer Portal.
2. Set `ABC_MOCK_ENABLED=false`, restart backend.
3. In Settings → Integrations → ABC Supply, set environment=`sandbox`, enter client id/secret and the
   exact registered redirect URI, then Connect and validate.
4. After ABC certification, switch environment to `production` and enter production credentials.
   Production mode requires explicit configuration.

## Security

- Client secret and OAuth access/refresh tokens are AES-GCM encrypted (`core.encrypt_secret`) in local
  PostgreSQL. The client secret is never sent to the browser.
- Tokens, refresh tokens, client secrets, authorization codes, and webhook secrets are **never logged**.
- OAuth uses PKCE (S256) + an opaque `state` value bound to the in-flight authorization (CSRF).

## Audit

Actions logged via the existing audit log: `abc.config.update`, `abc.config.set_secret`,
`abc.connect.start`, `abc.connect`, `abc.disconnect`, `abc.account.select`, `abc.branch.select`,
`abc.test` (Phases 2–4 add `abc.price.refresh`, `abc.po.create`, `abc.order.submit`,
`abc.order.confirmed`, `abc.order.status_update`, `abc.webhook.received`, `abc.webhook.rejected`).

## RBAC

- Owner/Administrator: connect/disconnect, configure credentials & defaults (SENSITIVE_ROLES).
- Office: read status, search accounts/branches (MANAGE_ROLES). Sales permissions are unchanged.

## Local mock server

Enabled via `ABC_MOCK_ENABLED=true`. Emulates OAuth authorize/token (with real PKCE S256 verification)
and the Account/Location APIs with documented-shape canned data (including a retired ship-to to prove
filtering). Also runnable standalone:

```
ABC_MOCK_ENABLED=1 uvicorn integrations.abc_supply.mock_server:mock_app --port 8099
```

## Troubleshooting

- **"Reconnect required"**: refresh token expired/invalid — click Reconnect.
- **Empty ship-to list**: only non-retired accounts (with branches) are shown, per ABC guidance.
- **Test connection fails before connect**: verify client id/secret; client-credentials scopes exclude pricing.

## NEEDS ABC DOC / SANDBOX VERIFICATION

- **Order/Notification** service path **prefixes** (`/api/order/v1`, `/api/notification/v1`) are inferred
  from the Account/Location/Product pattern; the public docs list only resource names (`/orders`,
  `/webhooks`). Isolated in `config.py`. (Pricing verified as `/api/pricing/v2/prices`; Product verified
  as `/api/product/v1/search/items`.)
- Product **image URLs**: ABC docs state image URLs are "available in a future release" — RoofSpan renders
  a placeholder and lazily proxies images through `GET /products/{item}/image` when a href is present.
- Product **recent/frequent/favorite** and **all-items/hierarchy** endpoints exist in the docs but were
  not implemented in P2 (kept to search + details + availability + pricing per scope); revisit if needed.
- Real Sandbox `client_id`/`client_secret`, the exact registered redirect URI, and the webhook public
  URL + webhook secret require ABC Developer Portal provisioning and are pending.

## Phase 2 — Product & Pricing (implemented)

**Product API** (`integrations/abc_supply/products.py`): `POST /api/product/v1/search/items`
(filters: `contains` itemDescription/itemNumber, `equals` itemNumber/productFamilyId/branchNumber;
`embed:["branches"]`; `?familyItems=true`). Item details via search-by-itemNumber. Branch availability
derived from embedded `branches[]` — presented as **Available / Not Available at Branch**, never a stock
quantity (ABC does not expose quantity-on-hand here).

**Pricing API** (`integrations/abc_supply/pricing.py`): `POST /api/pricing/v2/prices` with a **user token**
(`pricing.read`), body `{shipToNumber, branchNumber, purpose, lines:[{id,itemNumber,quantity,uom,length}]}`,
up to 50 lines. HTTP 200 is returned even with per-line errors, so each line's `status` is inspected.
**$0.00 rule**: `status.code == OK` + `unitPrice == 0.00` ⇒ `price_status="unavailable"` (branch has not
entered pricing — NOT free). Per-line `status.code != OK` ⇒ `unavailable` with the ABC message.

**PO integration**: `PurchaseOrder` gains `integration_provider`, `abc_ship_to_number`, `abc_branch_number`;
`POLineItem` gains `integration_provider, abc_item_number, abc_branch_number, abc_ship_to_number, abc_uom,
abc_variation, abc_price, abc_price_status, abc_price_timestamp, abc_product_description, abc_product_family,
abc_product_image_url, pricing_source` (migration `b2d5e7c9a1f3`, all nullable — generic POs unaffected).
`POOut.pricing_warning` surfaces unresolved-pricing lines. `POST /api/purchase-orders/{id}/refresh-price`
re-prices one ABC line (using its current Ship-To/branch/qty/UOM/variation) and optionally applies it,
recomputing the PO total; manual prices are only overwritten when the user explicitly applies. Changing
Ship-To/branch in the PO dialog clears gathered ABC pricing.

**RoofSpan API**: `POST /integrations/abc/products/search`, `GET /integrations/abc/products/{item}`,
`GET /integrations/abc/products/{item}/image`, `POST /integrations/abc/pricing`. Audit: `abc.product.search`,
`abc.product.view`, `abc.price.lookup`, `abc.price.refresh`, `abc.price.apply`.

**UI**: `frontend/src/components/AbcProductSearch.jsx` (debounced search, availability badges, qty/length,
get-price-and-add) integrated into `PODialog.jsx` when supplier is "ABC Supply" (Ship-To/branch context +
unresolved-pricing warning). Product search is debounced (450ms) — no request per keystroke.

**Mock**: search (description/itemNumber/family, branch availability), 1×1 PNG image endpoint, and
`/api/pricing/v2/prices` covering priced / $0-unavailable / dimensional-requires-length / unknown-item.
