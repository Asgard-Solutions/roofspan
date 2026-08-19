# RoofSpan Operator (Cognito → Vercel → Control Plane) — Go-Live Runbook

Scope: finish the **live Cognito operator flow** + **Vercel callback** at
`https://www.roofspan.io/operator/callback`, then run **one end-to-end production validation**.
Nothing else (P1-5 / P1-6) starts until this passes.

Current known-good state (your report): Railway CP + Postgres + KMS healthy, Stripe secrets/webhook
staged, Cognito setup in progress. Remaining gap = live Cognito + Vercel callback.

Values that MUST match across all three systems:
- `COGNITO_CLIENT_ID` (Vercel) == `CP_OPERATOR_AUDIENCE` (Railway)  → the id_token `aud`
- `CP_OPERATOR_ISSUER` (Railway) == `https://cognito-idp.<region>.amazonaws.com/<USER_POOL_ID>` → the id_token `iss`
- Callback URL is byte-for-byte identical in Cognito, Vercel `OPERATOR_REDIRECT_URI`, and the code default:
  `https://www.roofspan.io/operator/callback`

---

## STEP 1 — Cognito app client (HUMAN, AWS console)
In the existing internal operator user pool (self-registration already disabled):
1. App client → **Authorization code grant** enabled, **PKCE** enabled. Prefer a **public** client (no secret).
2. OpenID scopes: `openid email profile`.
3. Allowed **callback URL** (exact): `https://www.roofspan.io/operator/callback`
4. Allowed **sign-out URL** (optional): `https://www.roofspan.io/operator/login`
5. Set/confirm the Hosted UI **domain** (you'll paste it into `COGNITO_DOMAIN`).
6. Create at least one **operator test user** (confirmed, password set) — you'll log in as this user in Step 5.

Record these four values:
- Hosted UI domain → `https://<domain>.auth.<region>.amazoncognito.com`
- App client id
- User pool id
- Region

---

## STEP 2 — Vercel env vars (operator/marketing project)
Set in Vercel → Project → Settings → Environment Variables (Production), then redeploy:

| Variable | Value |
|---|---|
| `COGNITO_DOMAIN` | `https://<domain>.auth.<region>.amazoncognito.com`  (no trailing slash) |
| `COGNITO_CLIENT_ID` | `<app client id>` |
| `COGNITO_CLIENT_SECRET` | *(leave UNSET for public/PKCE client)* |
| `OPERATOR_REDIRECT_URI` | `https://www.roofspan.io/operator/callback` |
| `COGNITO_LOGOUT_URI` | `https://www.roofspan.io/operator/login` (optional) |
| `CONTROL_PLANE_BASE_URL` | `https://cp.roofspan.io` |

Confirm `api/operator/*`, `public/operator/index.html`, and the `vercel.json` rewrites are in the live project.

---

## STEP 3 — Railway Control Plane env vars
Set (or confirm) in the Railway CP service, then redeploy:

```
CP_ENV=production
CP_OPERATOR_ISSUER=https://cognito-idp.<region>.amazonaws.com/<USER_POOL_ID>
CP_OPERATOR_AUDIENCE=<app client id>          # MUST equal COGNITO_CLIENT_ID
```
(Note: with `CP_ENV=production`, the dev `X-RoofSpan-Admin` header path is disabled — operator JWT required.)

---

## STEP 4 — Pre-flight smoke (no login needed)
Run from your terminal. All should behave as noted:

```bash
# 4a. CP is up
curl -s https://cp.roofspan.io/api/control-plane/health
# expect: {"status":"ok","service":"roofspan-control-plane"}

# 4b. CP readiness (db + signing key)
curl -s https://cp.roofspan.io/api/control-plane/ready
# expect: {"ready":true,...}

# 4c. operator/me WITHOUT a token → must be 401 (proves it is actually protected)
curl -s -o /dev/null -w "%{http_code}\n" https://cp.roofspan.io/api/control-plane/operator/me
# expect: 401   (500 => CP_OPERATOR_ISSUER/AUDIENCE not set on Railway)

# 4d. Vercel login starts the flow → 302 to Cognito Hosted UI
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" https://www.roofspan.io/operator/login
# expect: 302 https://<domain>.auth.<region>.amazoncognito.com/oauth2/authorize?...
#         (500 "Operator auth not configured." => COGNITO_DOMAIN/CLIENT_ID missing on Vercel)

# 4e. whoami with no cookie → 401 authenticated:false
curl -s https://www.roofspan.io/api/operator/whoami
# expect: {"authenticated":false}
```
Gate: do not proceed to Step 5 until 4a–4e are all correct.

---

## STEP 5 — End-to-end production validation (browser, the real test)
1. Open `https://www.roofspan.io/operator/login` → you should land on the **Cognito Hosted UI**.
2. Sign in with the operator test user from Step 1.
3. Cognito redirects to `https://www.roofspan.io/operator/callback` which (server-side) exchanges the
   code and sets the **HttpOnly** cookie `op_token`, then redirects to `/operator`.
4. On `/operator`, the page calls `/api/operator/whoami` → expect **authenticated: true**.
5. DevTools verification (the security guarantees):
   - Application → Cookies: `op_token` present with **HttpOnly ✓, Secure ✓, SameSite=Lax**.
   - Console: `document.cookie` must **NOT** contain `op_token`; `localStorage`/`sessionStorage` empty of tokens.
   - Network: the token exchange happened server-side (no `client_secret` / `code_verifier` visible to the browser).

Pass criteria (all must hold):
- [ ] Login redirects to Cognito Hosted UI (Step 5.1)
- [ ] Callback succeeds and lands on `/operator` (5.3)
- [ ] `whoami` returns `authenticated: true` (5.4) — proves CP accepted the Cognito id_token
- [ ] `op_token` is HttpOnly+Secure and invisible to JS (5.5)
- [ ] Step 4c returned 401 (endpoint genuinely protected)

---

## Fast triage
| Symptom | Cause | Fix |
|---|---|---|
| 4d returns 500 "Operator auth not configured." | Vercel missing `COGNITO_DOMAIN`/`COGNITO_CLIENT_ID` | set in Step 2, redeploy |
| 4c returns 500 (not 401) | Railway missing `CP_OPERATOR_ISSUER`/`CP_OPERATOR_AUDIENCE` | set in Step 3, redeploy |
| Cognito "redirect_mismatch" | callback URL not exact | make Cognito == `OPERATOR_REDIRECT_URI` == `https://www.roofspan.io/operator/callback` |
| whoami stays `false` after login | `aud`/`iss` mismatch | `COGNITO_CLIENT_ID` must equal `CP_OPERATOR_AUDIENCE`; `CP_OPERATOR_ISSUER` must be the exact user-pool issuer |
| Callback page shows "Invalid or expired sign-in state." | cookies dropped (state/pkce) | ensure single domain `www.roofspan.io`, don't strip cookies at a proxy |
| Callback "sign-in failed" after Cognito | token exchange failed | if the client is confidential, set `COGNITO_CLIENT_SECRET` in Vercel only; else make the client public |

When all Step 5 boxes are checked, reply **"operator flow validated"** and I'll begin **P1-5 (Backup/restore recovery model)** — or P1-6 if you prefer.
