# RoofSpan

RoofSpan is a **locally installed** roofing-operations product — **not** a centrally hosted SaaS.
There is **NO centrally hosted RoofSpan operational web application.**

## Product surfaces & where the code lives

### 1. RoofSpan Office — the local Windows application
The primary product. Installed on the customer's Windows machine; the user works through a **local
browser UI** served by the installed app (browser → localhost → local FastAPI → local PostgreSQL). It is
authoritative for all users, auth, roles, permissions, and roofing business data (leads, jobs, customers,
properties, inspections, photos, notes, assignments, inventory, finance). Subscription/seat/billing
administration happens here (may redirect to Stripe-hosted pages).

Physical code today (kept at these paths due to Emergent platform requirements):
- `/backend`  — local FastAPI backend + business DB models/migrations (Alembic)
- `/frontend` — the RoofSpan Office **local browser UI only** (React)
- `/windows`  — Windows installer/updater work (WiX/MSI scaffold + Python updater logic)

### 2. RoofSpan Mobile — the field app
- `/mobile` — Expo/React Native. Connects **through the RoofSpan Secure Relay** to the customer's local
  RoofSpan Office installation. It does not host business data.

### 3. roofspan.io — the public marketing/download website
- `/roofspan-website` — standalone React app for **https://roofspan.io** (marketing, pricing, Coming
  Soon, Windows installer download link, Mobile Coming Soon). Deploys independently. Imports **no** Office
  code. Not served by the Emergent preview.

### Central Services (commercial/connectivity only — NOT a business app)
Licensing/subscription commercial metadata, Stripe/RevenueCat sync, Secure Relay, pairing resolution,
version policy, entitlement issuance. They store **no** roofing operational data.
Currently physically colocated inside the Office backend (see below); to be extracted into independently
deployed services during the AWS phase.
- `/backend/control_plane` — Control Plane (licensing/billing/pairing/version/identity)
- `/backend/relay` — Secure Relay transport

## Deployment boundaries (four independent outputs)
| Output | Built from | Target |
| --- | --- | --- |
| RoofSpan Office | `/backend` + `/frontend` + `/windows` | Windows installer (local install) |
| RoofSpan Mobile | `/mobile` | Expo/EAS build (App Store / Play Store) |
| roofspan.io | `/roofspan-website` | Static website hosting (roofspan.io) |
| Central Services | `/backend/control_plane`, `/backend/relay` | AWS (future) |

These pipelines are independent: the website does not build the Office backend; the Office installer does
not build the website; Mobile does not depend on the website.

## Repo layout
```
/app
├── backend/            # RoofSpan Office backend + colocated Control Plane / Relay
├── frontend/           # RoofSpan Office LOCAL browser UI only
├── mobile/             # RoofSpan Mobile
├── windows/            # Office Windows installer/updater
├── roofspan-website/   # Public roofspan.io website (standalone, own build/test)
├── roofspan-office/    # Architecture pointer/docs only (real code is /backend + /frontend + /windows)
├── central-services/   # Architecture pointer/docs only (real code is /backend/control_plane + /backend/relay)
├── docs/               # Architecture & deployment documentation
├── shared/             # Reserved for genuinely shared, product-neutral code (see docs)
└── memory/             # Product docs (PRD, commercial architecture, credentials)
```

See `docs/ARCHITECTURE.md` for the full picture.
