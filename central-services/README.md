# Central Services (pointer)

**This folder contains no application code (yet).** It documents the centrally hosted RoofSpan
commercial/connectivity services and marks the logical boundary between them and the customer's local
roofing **business** application.

These services hold **commercial/connectivity metadata only** — licensing state, subscription/seat state,
Stripe/RevenueCat synchronization, signed entitlements, installation activation, Mobile pairing
resolution, version policy, and Secure Relay routing. **They do NOT own or store roofing operational
business data** (leads, jobs, customers, properties, inspections, photos, notes) — that stays in each
customer's local RoofSpan Office PostgreSQL.

## Real code locations (currently colocated inside the Office backend)
- Control Plane: **`/app/backend/control_plane`** (own DB `roofspan_control_plane`, own Alembic history)
- Secure Relay: **`/app/backend/relay`**

## Why colocated for now (3a)
The running FastAPI project imports and runs these modules in-container, which is how they are tested
today. Physically extracting them into separate deployables now would require risky refactors/import
shims for no immediate benefit. **Planned extraction:** during the AWS production-deployment phase they
become independently deployed services (e.g., ECS/Fargate + RDS for the Control Plane DB, a horizontally
scalable Relay behind ALB with a shared pub/sub registry). See `/app/memory/COMMERCIAL_ARCHITECTURE.md`.

## Tests
`cd /app/backend && python -m pytest tests/test_relay.py tests/test_pairing.py tests/test_stripe_billing.py -q`
