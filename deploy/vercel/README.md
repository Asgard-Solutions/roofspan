# RoofSpan Operator (Cognito) auth — MOVED into the live Vercel project

> **This staging folder no longer holds the operator code.** The operator-auth serverless functions,
> the operator console page, and the Vercel rewrites now live inside the **actual Vercel project that
> serves roofspan.io / www.roofspan.io**: `roofspan-website/`. Keeping a second copy here caused Vercel
> to serve the marketing SPA for `/operator/*` and `/api/operator/*` because those files were never part
> of the deployed project.

## Canonical location (deploy from here)
```
roofspan-website/api/operator/_lib.js        PKCE + cookie helpers + server-side token exchange
roofspan-website/api/operator/login.js       GET /operator/login    -> 302 to Cognito Hosted UI (Auth Code + PKCE S256)
roofspan-website/api/operator/callback.js    GET /operator/callback -> validate state, exchange code, set HttpOnly id_token cookie
roofspan-website/api/operator/whoami.js      GET /api/operator/whoami -> JSON proof: calls CP GET /operator/me with Bearer
roofspan-website/public/operator/index.html  GET /operator          -> minimal protected console (calls whoami)
roofspan-website/vercel.json                 operator route rewrites (merged into the marketing project)
roofspan-website/tests/operator_auth.test.mjs        unit tests (PKCE, callback validation, code exchange)
roofspan-website/tests/deployment_wiring.test.mjs    deployment tests (routes resolve to functions, not SPA)
```
Vercel auto-detects the Create React App build (`react-scripts build` -> `build/`); `api/*` deploy as
Node serverless functions and `public/operator/index.html` is copied to `build/operator/index.html`.
The marketing React app is untouched.

## Canonical production host
Vercel redirects apex `roofspan.io` -> `www.roofspan.io`, so the operator flow uses **www**:
- Callback: `https://www.roofspan.io/operator/callback`
- Login:    `https://www.roofspan.io/operator/login`

Set the Cognito **Allowed callback URL** to `https://www.roofspan.io/operator/callback` (exact) and
`OPERATOR_REDIRECT_URI` to the same value.

## Vercel environment variables (the roofspan.io project) — HUMAN REQUIRED
| Variable | Example / value |
|---|---|
| `COGNITO_DOMAIN` | `https://<hosted-ui-domain>.auth.us-east-2.amazoncognito.com` (no trailing slash) |
| `COGNITO_CLIENT_ID` | `<COGNITO_APP_CLIENT_ID>` (must equal Railway `CP_OPERATOR_AUDIENCE`) |
| `COGNITO_CLIENT_SECRET` | *(optional; only for a confidential client — server-side only. Prefer a public PKCE client and leave unset.)* |
| `OPERATOR_REDIRECT_URI` | `https://www.roofspan.io/operator/callback` |
| `COGNITO_LOGOUT_URI` | `https://www.roofspan.io/operator/login` (optional) |
| `CONTROL_PLANE_BASE_URL` | `https://cp.roofspan.io` |

## Tests
- `node --test roofspan-website/tests/operator_auth.test.mjs` — PKCE, callback validation, mocked exchange.
- `node --test roofspan-website/tests/deployment_wiring.test.mjs` — routes resolve to serverless functions
  (not the SPA), operator page present, vercel.json rewrites correct, canonical www host.
- `python -m pytest backend/tests/test_operator_auth_vercel.py -o addopts=''` — static security boundary.

## Post-deploy smoke
```
curl -I https://www.roofspan.io/operator/login        # -> 302 to Cognito
curl    https://www.roofspan.io/api/operator/whoami    # -> {"authenticated":false}
```
