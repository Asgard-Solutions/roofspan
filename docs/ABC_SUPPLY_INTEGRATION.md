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

- Pricing/Order/Notification service path **prefixes** (`/api/pricing/v1`, `/api/order/v1`,
  `/api/notification/v1`) are inferred from the Account/Location/Product prefix pattern; the public docs
  list only resource names (`/prices`, `/orders`, `/webhooks`). Isolated in `config.py` for one-line
  reconciliation once verified against Sandbox.
- Real Sandbox `client_id`/`client_secret`, the exact registered redirect URI, and the webhook public
  URL + webhook secret require ABC Developer Portal provisioning and are pending.
