"""RoofSpan Control Plane (Phase C1) — central commercial metadata service.

Logically separate from the customer's local business data: it runs against its OWN database
(CONTROL_PLANE_DATABASE_URL, default a separate `roofspan_control_plane` DB) and stores only
commercial metadata (companies, installations, licenses, subscriptions, signing keys, entitlement
issuances, version policy, replay nonces, audit). It NEVER stores roofing business data.

In-container this is mounted in the same FastAPI app under /api/control-plane for development and
testing; in production it is intended to run as a standalone AWS-hosted service. The code is
deployment-neutral and configuration-driven.
"""
