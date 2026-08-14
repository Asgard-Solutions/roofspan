# RoofSpan Operator (Cognito) auth — Vercel drop-in

Internal RoofSpan **operator/admin** authentication only. **NOT** customer auth, **NOT** mobile auth, no
self-registration, no Apple/Google/customer sign-in. It lets an internal operator sign in via the Cognito
Hosted UI and obtain a bearer the Railway Control Plane accepts for production admin endpoints.

## What this adds (drop into the existing `roofspan.io` Vercel project)
```
api/operator/_lib.js       PKCE + cookie helpers + server-side token exchange (validateCallback, exchangeCode)
api/operator/login.js      GET /operator/login    -> redirect to Cognito Hosted UI (Auth Code + PKCE S256)
api/operator/callback.js   GET /operator/callback -> validate state, exchange code, set HttpOnly id_token cookie
api/operator/whoami.js     GET /api/operator/whoami -> proof: calls CP GET /operator/me with Bearer
public/operator/index.html /operator              -> minimal protected console (calls whoami)
vercel.json                route rewrites
```
Copy `api/operator/*` into the Vercel project's `api/operator/`, `public/operator/index.html` into
`public/operator/`, and merge `vercel.json` rewrites. Marketing site content is untouched.

## Auth flow (Authorization Code + PKCE, no browser secret)
1. `/operator/login` → generate PKCE verifier + `state`, store both in short-lived **HttpOnly** cookies,
   redirect to `${COGNITO_DOMAIN}/oauth2/authorize` (`code_challenge_method=S256`, `scope=openid email profile`).
2. Cognito → `/operator/callback` with `code` + `state`.
3. Callback verifies `state` matches the cookie (CSRF) and `code` is present, then exchanges the code
   **server-side** at `${COGNITO_DOMAIN}/oauth2/token` with the PKCE `code_verifier` (public client = no
   secret; optional confidential client uses HTTP Basic **server-side only**).
4. The Cognito **id_token** (its `aud` = app client id, `iss` = user-pool issuer — exactly what the Control
   Plane's `operator_auth.verify_operator` validates) is stored in an **HttpOnly, Secure, SameSite=Lax**
   cookie `op_token`. Tokens are never exposed to JS / localStorage.
5. `/operator` calls `/api/operator/whoami`, which forwards `Authorization: Bearer <id_token>` to the
   Control Plane `GET /api/control-plane/operator/me` (200 ⇒ authenticated).

## Vercel environment variables (operator project) — HUMAN REQUIRED
| Variable | Example / value | Notes |
|---|---|---|
| `COGNITO_DOMAIN` | `https://<hosted-ui-domain>.auth.us-east-2.amazoncognito.com` | Cognito Hosted UI domain (no trailing slash). **HUMAN**: real domain. |
| `COGNITO_CLIENT_ID` | `<COGNITO_APP_CLIENT_ID>` | App client id. Not secret. **HUMAN**. |
| `COGNITO_CLIENT_SECRET` | *(optional)* | ONLY if the app client is "confidential". Server-side only; never shipped to browser. Prefer a **public** (no-secret) PKCE client and leave this unset. **HUMAN**. |
| `OPERATOR_REDIRECT_URI` | `https://roofspan.io/operator/callback` | Must EXACTLY match the Cognito callback URL. |
| `COGNITO_LOGOUT_URI` | `https://roofspan.io/operator/login` | Optional. |
| `CONTROL_PLANE_BASE_URL` | `https://cp.roofspan.io` | Railway CP base (server-side fetch target). |

No secret values are committed. Set these in the Vercel project settings.

## Railway Control Plane variables (already documented in deploy/railway/README.md)
```
CP_OPERATOR_ISSUER=https://cognito-idp.us-east-2.amazonaws.com/<USER_POOL_ID>
CP_OPERATOR_AUDIENCE=<COGNITO_APP_CLIENT_ID>     # must equal COGNITO_CLIENT_ID above
```

## HUMAN REQUIRED — Cognito configuration
1. In the existing internal user pool, use an **app client** (self-registration already disabled).
2. Enable **Authorization code grant** + **PKCE**; scopes `openid email profile`. Prefer a **public**
   client (no secret) so no secret is needed anywhere; otherwise set `COGNITO_CLIENT_SECRET` in Vercel only.
3. Allowed callback URL: **`https://roofspan.io/operator/callback`** (exact). Sign-out URL:
   `https://roofspan.io/operator/login` (optional).
4. Set the Cognito Hosted UI **domain** and put it in `COGNITO_DOMAIN`.
5. Ensure Railway `CP_OPERATOR_ISSUER` = `https://cognito-idp.<region>.amazonaws.com/<USER_POOL_ID>` and
   `CP_OPERATOR_AUDIENCE` = the same app client id as `COGNITO_CLIENT_ID`.

## Tests
- `node --test deploy/vercel/tests/operator_auth.test.mjs` — PKCE, callback validation (missing/mismatched
  state, missing code), mocked code exchange, no-secret public-client path. (7 tests)
- `python -m pytest backend/tests/test_operator_auth_vercel.py -o addopts=''` — route exists, state/code
  validation, HttpOnly-not-localStorage, no browser secret, exact callback URL, id_token bearer → CP. (7)
