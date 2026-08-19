# roofspan.io — Public Marketing & Download Website

The **standalone** public website for **https://roofspan.io**. This is a self-contained React app with
**no dependency on RoofSpan Office** (no Office auth, API clients, routes, business pages, or billing
admin). It deploys independently to roofspan.io; it is NOT the local RoofSpan Office UI and is NOT served
by the Emergent preview (which runs the Office app at `/app/frontend`).

> There is **no centrally hosted RoofSpan operational web application.** This site only markets RoofSpan
> and links to the Windows installer download.

## What it contains
- Hero + Coming Soon, Features, How It Works, Architecture strip, Pricing, Windows Download, Mobile, Footer
- Public SEO metadata + brand assets (`public/brand/`, duplicated immutable logo/favicon/hero — no runtime coupling to Office)
- Centralized public download config in `src/config.js` (CloudFront URL only; never a backend proxy)

## Commands (independent of Office / Mobile / backend)
```
cd /app/roofspan-website
yarn install
yarn build      # production build -> build/
yarn test       # CI=true yarn test  (pure unit tests: config + content)
yarn start      # dev server on PORT 3001 (Office runs on 3000)
```

## Configuration (`.env` — PUBLIC values only, never secrets)
- `REACT_APP_WINDOWS_INSTALLER_URL` = https://downloads.roofspan.io/latest/RoofSpanSetup.exe
- `REACT_APP_WINDOWS_INSTALLER_AVAILABLE` = `false` (shows "Coming Soon" until the installer is published)
- `REACT_APP_WINDOWS_UPDATE_MANIFEST_URL` = https://downloads.roofspan.io/update/windows/latest.json

When `REACT_APP_WINDOWS_INSTALLER_AVAILABLE=true`, the Download button links **directly** to the
CloudFront installer URL (never proxied). CloudFront/S3/DNS are managed outside this repo — not modified here.

## Deployment
Build (`yarn build`) and deploy `build/` to the roofspan.io hosting target. The RoofSpan Office frontend
(`/app/frontend`) must NOT be deployed to roofspan.io.

## Operator (internal admin) auth — part of THIS Vercel project
This project also ships the RoofSpan **operator** (Cognito) auth as Vercel serverless functions. These are
internal admin-only routes and do NOT touch the marketing React app:
- `api/operator/*.js` — serverless functions (`/operator/login`, `/operator/callback`, `/api/operator/whoami`)
- `public/operator/index.html` — the operator console (served at `/operator`)
- `vercel.json` — the operator route rewrites (merged into this project; marketing routing untouched)

Canonical host is `https://www.roofspan.io` (Vercel redirects apex -> www). Set the Vercel env vars
`COGNITO_DOMAIN`, `COGNITO_CLIENT_ID`, `COGNITO_CLIENT_SECRET` (optional), `OPERATOR_REDIRECT_URI`,
`COGNITO_LOGOUT_URI`, `CONTROL_PLANE_BASE_URL`. See `deploy/vercel/README.md` for the full runbook.
Tests: `node --test tests/operator_auth.test.mjs` and `node --test tests/deployment_wiring.test.mjs`.

