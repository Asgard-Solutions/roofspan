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

    async def create_initial_checkout(self, db: AsyncSession, *, company_id: str,
                                      installation_id: str | None = None, seats: int | None = None) -> dict:
        """DEV: return a mock hosted-checkout URL (no external account, no Stripe secret)."""
        from control_plane import billing as cp_billing
        n = int(seats or config.MIN_SEATS)
        url = cp_billing.get_provider().checkout_url(company_id)
        return {"checkout_url": url, "company_id": company_id, "seats": n, "monthly_price_usd": n * 49}


class HttpControlPlaneClient:
    mode = "http"

    def _base(self) -> str:
        base = config.CONTROL_PLANE_URL
        if not base:
            raise ControlPlaneUnavailable("Control Plane URL not configured")
        return base.rstrip("/")

    async def activate(self, db: AsyncSession, *, company_name: str | None = None,
                       requested_seats: int | None = None) -> dict:
        """First-run activation: register this installation's PUBLIC key and receive the CP-assigned
        identity + first signed entitlement. ONLY the public key is sent — the private key never
        leaves the machine. This method performs NO local persistence; the caller
        (licensing.service.persist_activation) adopts the returned ids/entitlement so the operation is
        idempotent and testable."""
        import httpx
        from licensing import identity

        _priv, pub_pem = identity.get_or_create_identity()  # _priv stays local; only pub_pem is sent
        payload = {
            "company_name": company_name or config.ACTIVATION_COMPANY_NAME,
            "requested_seats": int(requested_seats if requested_seats is not None else config.ACTIVATION_REQUESTED_SEATS),
            "installation_public_key": pub_pem,
            "software_version": config.SOFTWARE_VERSION,
            "bootstrap_credential": config.ACTIVATION_BOOTSTRAP_CREDENTIAL,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(f"{self._base()}/activate", json=payload)
        except httpx.HTTPError as e:
            raise ControlPlaneUnavailable(f"Activation request failed: {e}") from e
        if resp.status_code != 200:
            raise ControlPlaneUnavailable(f"Activation rejected ({resp.status_code}): {resp.text[:200]}")
        return resp.json()

    async def fetch_entitlement(self, db: AsyncSession, *, installation_id: str, company_id: str) -> str:
        import time
        import uuid as _uuid
        import httpx
        from licensing import identity, keys as lkeys, reqsig

        priv = identity.load_private_key()
        if priv is None:
            raise ControlPlaneUnavailable("Installation not activated (no installation identity)")
        timestamp = str(int(time.time()))
        nonce = _uuid.uuid4().hex
        body = b""
        signature = reqsig.sign_request(priv, installation_id=installation_id, timestamp=timestamp, nonce=nonce, body=body)
        headers = {
            reqsig.H_INSTALLATION: installation_id,
            reqsig.H_TIMESTAMP: timestamp,
            reqsig.H_NONCE: nonce,
            reqsig.H_SIGNATURE: signature,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(f"{self._base()}/entitlement/refresh", content=body, headers=headers)
        except httpx.HTTPError as e:
            raise ControlPlaneUnavailable(f"Entitlement refresh failed: {e}") from e
        if resp.status_code == 403:
            # Explicit revocation is authoritative — surface as an error (not a transient outage).
            raise RuntimeError("Installation identity revoked by Control Plane")
        if resp.status_code != 200:
            raise ControlPlaneUnavailable(f"Refresh rejected ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()
        lkeys.cache_trusted_cp_keys(data.get("signing_public_keys", {}))
        return data["entitlement_jws"]

    async def create_initial_checkout(self, db: AsyncSession, *, company_id: str,
                                      installation_id: str | None = None, seats: int | None = None) -> dict:
        """PRODUCTION: ask the central Control Plane to create the hosted checkout, authenticated with
        this installation's identity (reqsig). Stripe secrets stay central; only the hosted URL comes back."""
        import time
        import uuid as _uuid
        import httpx
        from licensing import identity, reqsig

        if not installation_id:
            raise ControlPlaneUnavailable("Installation not activated (no installation identity)")
        priv = identity.load_private_key()
        if priv is None:
            raise ControlPlaneUnavailable("Installation not activated (no installation identity)")
        timestamp = str(int(time.time()))
        nonce = _uuid.uuid4().hex
        body = b""
        signature = reqsig.sign_request(priv, installation_id=installation_id, timestamp=timestamp, nonce=nonce, body=body)
        headers = {
            reqsig.H_INSTALLATION: installation_id,
            reqsig.H_TIMESTAMP: timestamp,
            reqsig.H_NONCE: nonce,
            reqsig.H_SIGNATURE: signature,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(f"{self._base()}/billing/stripe/initial-checkout", content=body, headers=headers)
        except httpx.HTTPError as e:
            raise ControlPlaneUnavailable(f"Checkout request failed: {e}") from e
        if resp.status_code != 200:
            raise ControlPlaneUnavailable(f"Checkout rejected ({resp.status_code}): {resp.text[:200]}")
        return resp.json()


def get_client():
    if config.LICENSING_MODE == "http":
        return HttpControlPlaneClient()
    return DevControlPlaneClient()
