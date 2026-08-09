"""Control Plane client abstraction.

The client fetches a freshly-signed entitlement for this installation. Two implementations:

  DevControlPlaneClient (Phase C0): signs in-process using the dev key, reading the simulated
    remote subscription (state + seats) from the local `app_config` table. This models the future
    Control Plane WITHOUT any external/AWS dependency, keeping Phase C0 fully local and testable.

  HttpControlPlaneClient (Phase C1+): calls the remote Control Plane over HTTPS. Stubbed in C0 —
    raises ControlPlaneUnavailable so the offline/cached-entitlement path is exercised.

The client NEVER holds the production signing key. In production, signing happens server-side and
the client only receives the already-signed entitlement.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AppConfig
from licensing import config, keys
from licensing import entitlement as ent

DEV_SUBSCRIPTION_KEY = "dev_subscription"  # app_config row simulating the remote subscription


class ControlPlaneUnavailable(Exception):
    """Raised when the Control Plane cannot be reached (transient outage)."""


async def _get_dev_subscription(db: AsyncSession) -> dict:
    row = (await db.execute(select(AppConfig).where(AppConfig.key == DEV_SUBSCRIPTION_KEY))).scalar_one_or_none()
    if row and isinstance(row.value, dict):
        return row.value
    return {"state": config.DEV_DEFAULT_STATE, "seats": config.DEV_DEFAULT_SEATS, "license_id": None}


async def set_dev_subscription(db: AsyncSession, *, state: str, seats: int, license_id: str | None = None) -> dict:
    """DEV ONLY: update the simulated remote subscription (used by tests / the dev set-state endpoint)."""
    value = {"state": state, "seats": int(seats), "license_id": license_id}
    row = (await db.execute(select(AppConfig).where(AppConfig.key == DEV_SUBSCRIPTION_KEY))).scalar_one_or_none()
    if row is None:
        db.add(AppConfig(key=DEV_SUBSCRIPTION_KEY, value=value))
    else:
        row.value = value
    await db.commit()
    return value


class DevControlPlaneClient:
    mode = "dev"

    async def fetch_entitlement(self, db: AsyncSession, *, installation_id: str, company_id: str) -> str:
        sub = await _get_dev_subscription(db)
        now = datetime.now(timezone.utc)
        claims = {
            "installation_id": installation_id,
            "company_id": company_id,
            "license_id": sub.get("license_id"),
            "subscription_state": sub.get("state", config.DEV_DEFAULT_STATE),
            "seats_licensed": int(sub.get("seats", config.DEV_DEFAULT_SEATS)),
            "product": config.PRODUCT,
            "min_supported_version": config.MIN_SUPPORTED_VERSION,
            "issued_at": now,
            "refresh_at": now + timedelta(hours=config.REFRESH_INTERVAL_HOURS),
            "grace_until": now + timedelta(days=config.OFFLINE_GRACE_DAYS),
            "nonce": uuid.uuid4().hex,
        }
        kid, priv = keys.get_dev_signing_key()
        return ent.sign_entitlement(private_key=priv, kid=kid, claims=claims)


class HttpControlPlaneClient:
    mode = "http"

    async def fetch_entitlement(self, db: AsyncSession, *, installation_id: str, company_id: str) -> str:
        # Phase C1+: HTTPS call to the (AWS-hosted) Control Plane. Not implemented in C0.
        raise ControlPlaneUnavailable("HTTP Control Plane not configured (Phase C1+).")


def get_client():
    if config.LICENSING_MODE == "http":
        return HttpControlPlaneClient()
    return DevControlPlaneClient()
