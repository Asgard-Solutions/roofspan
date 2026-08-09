"""RoofSpan licensing core (Phase C0).

Deployment-neutral, configuration-driven licensing:
  - Signed entitlements (EdDSA / Ed25519) issued by a Control Plane, verified locally.
  - Local cache with offline grace so a Control Plane outage never suspends a company.
  - ACTIVE / GRACE / SUSPENDED / CANCELLED state machine.
  - Server-side, race-safe active-seat enforcement.

The local RoofSpan installation remains authoritative for users, roles, permissions
and all business data. Licensing controls product entitlement and active-seat limits only.
"""
