# RoofSpan Architecture

> **Invariant:** There is **no centrally hosted RoofSpan operational web application.** RoofSpan Office is
> a locally installed Windows app with a local browser UI. `roofspan.io` is a public marketing/download
> site only. Mobile connects through the Secure Relay to the customer's local Office install.

## Surfaces
1. **RoofSpan Office** — local Windows app. `Browser → localhost → local FastAPI → local PostgreSQL`.
   Authoritative for users/auth/roles/permissions and ALL roofing business data. Subscription/seat/billing
   admin lives here (redirects to Stripe-hosted pages as needed).
   Code: `/backend`, `/frontend` (local UI only), `/windows`.
2. **RoofSpan Mobile** — Expo/React Native field app. `Mobile → Secure Relay → customer's local Office`.
   Code: `/mobile`.
3. **roofspan.io** — public marketing/download website. Code: `/roofspan-website` (standalone).
4. **Central Services** — licensing/billing-sync/pairing/version/entitlements/Relay, commercial metadata
   only, no business data. Code: `/backend/control_plane`, `/backend/relay` (colocated now; AWS later).

## Data flows
- Office business data never leaves the customer's local PostgreSQL.
- Mobile business calls route through the Secure Relay to the local Office FastAPI (local JWT + local RBAC
  are authoritative). The Relay routes, it never stores business data.
- Central services exchange licensing/billing/pairing/version metadata only.
- Installer/updates are distributed via `downloads.roofspan.io` (CloudFront → private S3); the website
  links directly to the CloudFront URL (never proxied through any backend).

## Deployment boundaries (independent)
- **RoofSpan Office** → Windows installer (from `/backend` + `/frontend` + `/windows`).
- **RoofSpan Mobile** → Expo/EAS build.
- **roofspan.io** → standalone website deploy of `/roofspan-website`. The Office frontend must NOT be
  deployed to roofspan.io.
- **Central Services** → AWS (future). Not provisioned.

## Platform note (Emergent)
The Emergent platform requires the backend at `/app/backend` and the frontend at `/app/frontend`. Nested
monorepo relocation of those is unsupported and would break preview/deploy. Hence `/roofspan-office` and
`/central-services` are documentation pointers, and true per-surface independent deploy pipelines are
achieved by separate deploy targets (and, for full isolation, separate projects/repos) rather than nesting.

## Shared code
`/shared` is reserved for genuinely shared, product-neutral contracts (e.g., protocol/version schemas,
public cryptographic verification contracts, immutable brand metadata). Business logic must not live there.
Nothing has been extracted yet to avoid source-level coupling between the surfaces.
