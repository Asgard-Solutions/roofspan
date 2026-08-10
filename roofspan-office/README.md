# RoofSpan Office (pointer)

**This folder contains no application code.** It documents where the RoofSpan Office product physically
lives. Because the Emergent platform requires the backend at `/app/backend` and the frontend at
`/app/frontend`, the Office code is **not** nested under this folder — moving it would break the preview
and deployment.

RoofSpan Office = the locally installed Windows application with a **local browser UI**
(browser → localhost → local FastAPI → local PostgreSQL). It is NOT a hosted SaaS web app.

## Real code locations
- Backend (local FastAPI + business DB models/Alembic migrations): **`/app/backend`**
- Local browser UI (React, Office only): **`/app/frontend`**
- Windows installer/updater (WiX/MSI scaffold + Python updater logic): **`/app/windows`**

## Build / test
- Backend: `cd /app/backend && python -m pytest tests/ -q`
- Frontend: `cd /app/frontend && yarn build` / `yarn test`

> Note: `/app/backend/control_plane` and `/app/backend/relay` are **central services** currently
> colocated in the backend for runtime reasons — see `/app/central-services/README.md`. They are not part
> of the customer's roofing business-data application.
