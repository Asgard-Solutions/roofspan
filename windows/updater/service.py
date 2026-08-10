"""RoofSpan Office update service foundation — background check cadence + a testable planning step.

The Windows update service (roofspan-update-service.exe) calls plan_update() every CHECK_INTERVAL_SECONDS
and, when an update applies, hands off to updater.orchestrator.UpdateOrchestrator with Windows-native
effects injected. A future in-Office "Check for Updates" admin action reuses plan_update().
"""
from __future__ import annotations

from updater.manifest import decide_update
from updater.signing import verify_manifest

# Background cadence: every 12 hours (aligns with the entitlement-refresh philosophy; no tight polling).
CHECK_INTERVAL_SECONDS = 12 * 60 * 60


def plan_update(current_version: str, manifest, public_pem: str) -> str:
    """Return one of: 'blocked' (bad signature), 'current', 'optional', 'required'."""
    if not verify_manifest(manifest, public_pem):
        return "blocked"
    return decide_update(current_version, manifest)
