"""Subscription state machine and effective-state evaluation.

Distinguishes the Control Plane's *reported* state (what it last asserted, carried inside the
signed entitlement) from the *effective* state the local installation enforces, which also accounts
for the offline grace window. Critically: an inability to CONTACT the Control Plane is NOT the same
as the Control Plane explicitly reporting SUSPENDED.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from licensing.entitlement import Entitlement, ACTIVE, GRACE, SUSPENDED, CANCELLED

# States that permit normal business workflows.
BUSINESS_ALLOWED = {ACTIVE, GRACE}


@dataclass
class EffectiveStatus:
    effective_state: str            # what the installation enforces right now
    reported_state: str             # what the entitlement (Control Plane) asserted
    business_access: bool           # normal business workflows allowed?
    within_offline_grace: bool      # still trusting a cached entitlement while offline?
    grace_until: Optional[datetime]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def evaluate(entitlement: Optional[Entitlement], now: Optional[datetime] = None) -> EffectiveStatus:
    """Compute the effective subscription state from a (verified) entitlement.

    Rules:
      - No valid entitlement (missing/expired/unverifiable) -> SUSPENDED (fail closed).
        Expiry only occurs after the full offline grace window, so transient outages are tolerated.
      - Entitlement reports SUSPENDED/CANCELLED -> that state applies immediately (explicit).
      - Entitlement reports ACTIVE/GRACE and is within grace_until -> that state applies.
    """
    now = now or _now()
    if entitlement is None:
        return EffectiveStatus(SUSPENDED, "UNLICENSED", False, False, None)

    reported = entitlement.subscription_state
    if reported in (SUSPENDED, CANCELLED):
        return EffectiveStatus(reported, reported, False, False, entitlement.grace_until)

    # reported ACTIVE or GRACE
    if now <= entitlement.grace_until:
        return EffectiveStatus(reported, reported, reported in BUSINESS_ALLOWED, True, entitlement.grace_until)

    # Offline grace exhausted without a fresh entitlement -> fail closed.
    return EffectiveStatus(SUSPENDED, reported, False, False, entitlement.grace_until)
