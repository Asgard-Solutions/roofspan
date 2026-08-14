"""LicenseService: installation identity, entitlement refresh/cache, effective state, seat enforcement.

Entitlement verification does NOT require a Control Plane call per request: the signed entitlement
is cached locally and verified from cache. The Control Plane is contacted only on scheduled refresh
(startup + every REFRESH_INTERVAL_HOURS) or an explicit admin refresh.
"""
from __future__ import annotations

import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from db import SessionLocal
from models import AppConfig, User, LicenseCache
from licensing import config, keys, control_plane
from licensing import entitlement as ent
from licensing import state as state_mod

logger = logging.getLogger("roofspan")

INSTALLATION_KEY = "installation"
SEAT_ADVISORY_LOCK_KEY = 748419  # arbitrary constant; serializes concurrent seat activations

# In-process effective-state snapshot for the guard middleware (avoids per-request DB/CP work).
_snapshot: dict = {"state": None, "at": 0.0}


def invalidate_snapshot() -> None:
    _snapshot["state"] = None
    _snapshot["at"] = 0.0


async def get_installation(db: AsyncSession) -> tuple[str, str]:
    """Return (installation_id, company_id); generate a stable identity on first use."""
    row = (await db.execute(select(AppConfig).where(AppConfig.key == INSTALLATION_KEY))).scalar_one_or_none()
    if row and isinstance(row.value, dict) and row.value.get("installation_id"):
        return row.value["installation_id"], row.value["company_id"]
    value = {
        "installation_id": str(uuid.uuid4()),
        "company_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if row is None:
        db.add(AppConfig(key=INSTALLATION_KEY, value=value))
    else:
        row.value = value
    await db.commit()
    logger.info("Generated RoofSpan installation identity %s", value["installation_id"])
    return value["installation_id"], value["company_id"]


async def _installation_row(db: AsyncSession):
    return (await db.execute(select(AppConfig).where(AppConfig.key == INSTALLATION_KEY))).scalar_one_or_none()


async def is_activated(db: AsyncSession) -> bool:
    """True only once the Control Plane has issued this installation an authoritative identity.

    Presence of a locally-generated provisional installation_id/company_id (from get_installation) is
    NOT activation: a provisional identity is unknown to the Control Plane and must never be used for
    signed refresh/checkout requests until /activate has adopted the CP-assigned ids."""
    row = await _installation_row(db)
    return bool(row and isinstance(row.value, dict) and row.value.get("activated") is True)


async def persist_activation(db: AsyncSession, data: dict) -> tuple[str, str]:
    """Adopt the Control-Plane-assigned authoritative identity and cache its first signed entitlement.

    Replaces any provisional local installation_id/company_id with the server-issued ids, marks the
    installation activated, caches the CP verification keys, and stores + verifies the initial
    entitlement JWS into license_cache. Idempotent: safe to call again with the same activation data.
    """
    installation_id = data["installation_id"]
    company_id = data["company_id"]
    license_id = data.get("license_id")

    # Trust the CP verification keys so the entitlement verifies (now and offline).
    keys.cache_trusted_cp_keys(data.get("signing_public_keys", {}) or {})

    # Authoritative identity + activation marker (replaces the provisional local identity).
    row = await _installation_row(db)
    base = row.value if (row and isinstance(row.value, dict)) else {}
    value = {**base, "installation_id": installation_id, "company_id": company_id,
             "license_id": license_id, "activated": True,
             "activated_at": datetime.now(timezone.utc).isoformat()}
    if row is None:
        db.add(AppConfig(key=INSTALLATION_KEY, value=value))
    else:
        row.value = value
    await db.commit()

    # Cache + cryptographically verify the initial entitlement into license_cache.
    token = data.get("entitlement_jws")
    if token:
        try:
            entitlement = ent.verify_entitlement(token, keys.get_trusted_verify_keys())
        except ent.EntitlementError as e:
            logger.warning("Activation entitlement failed verification (kept identity): %s", e)
            return installation_id, company_id
        crow = await _get_cache_row(db)
        if crow is not None and crow.installation_id != installation_id:
            await db.delete(crow)  # drop a stale provisional cache row (installation_id is the PK)
            await db.flush()
            crow = None
        now = datetime.now(timezone.utc)
        if crow is None:
            crow = LicenseCache(installation_id=installation_id, company_id=company_id)
            db.add(crow)
        crow.installation_id = installation_id
        crow.company_id = entitlement.company_id
        crow.license_id = entitlement.license_id
        crow.entitlement_jws = token
        crow.kid = entitlement.kid
        crow.subscription_state = entitlement.subscription_state
        crow.seats_licensed = entitlement.seats_licensed
        crow.product = entitlement.product
        crow.min_supported_version = entitlement.min_supported_version
        crow.issued_at = entitlement.issued_at
        crow.refresh_at = entitlement.refresh_at
        crow.grace_until = entitlement.grace_until
        crow.fetched_at = now
        crow.last_check_at = now
        crow.last_check_ok = True
        crow.last_error = None
        await db.commit()
        invalidate_snapshot()
    return installation_id, company_id


async def _get_cache_row(db: AsyncSession) -> Optional[LicenseCache]:
    return (await db.execute(select(LicenseCache).limit(1))).scalar_one_or_none()


def _to_naive_utc(dt: datetime) -> datetime:
    """Store timezone-aware UTC as naive-UTC-aware consistently (columns are timezone=True)."""
    return dt


async def refresh(db: AsyncSession, *, force: bool = False) -> dict:
    """Fetch a fresh signed entitlement from the Control Plane, verify it, and cache it.

    On a Control Plane/network outage, the existing cache is preserved (offline tolerance) and the
    failure is recorded — the installation is NOT suspended by an outage.
    """
    if config.LICENSING_MODE == "http" and not await is_activated(db):
        # Not yet activated: signing a refresh with the provisional local id would be rejected by the
        # Control Plane ("Unknown installation"). Wait until first-run activation adopts the CP id.
        return {"ok": False, "offline": True, "error": "not activated (awaiting first-run activation)"}
    installation_id, company_id = await get_installation(db)
    client = control_plane.get_client()
    now = datetime.now(timezone.utc)
    row = await _get_cache_row(db)
    if row is None:
        row = LicenseCache(installation_id=installation_id, company_id=company_id)
        db.add(row)

    try:
        token = await client.fetch_entitlement(db, installation_id=installation_id, company_id=company_id)
        entitlement = ent.verify_entitlement(token, keys.get_trusted_verify_keys())
        if entitlement.installation_id != installation_id:
            raise ent.EntitlementError("Entitlement installation_id mismatch")
        row.installation_id = installation_id
        row.company_id = entitlement.company_id
        row.license_id = entitlement.license_id
        row.entitlement_jws = token
        row.kid = entitlement.kid
        row.subscription_state = entitlement.subscription_state
        row.seats_licensed = entitlement.seats_licensed
        row.product = entitlement.product
        row.min_supported_version = entitlement.min_supported_version
        row.issued_at = entitlement.issued_at
        row.refresh_at = entitlement.refresh_at
        row.grace_until = entitlement.grace_until
        row.fetched_at = now
        row.last_check_at = now
        row.last_check_ok = True
        row.last_error = None
        await db.commit()
        invalidate_snapshot()
        return {"ok": True, "state": entitlement.subscription_state, "offline": False}
    except (control_plane.ControlPlaneUnavailable, Exception) as e:
        # Preserve existing cache; record the failed attempt. Do not suspend on an outage.
        is_unavailable = isinstance(e, control_plane.ControlPlaneUnavailable)
        row.last_check_at = now
        row.last_check_ok = False
        row.last_error = ("unreachable: " if is_unavailable else "error: ") + str(e)[:400]
        await db.commit()
        invalidate_snapshot()
        logger.warning("License refresh failed (kept cached entitlement): %s", e)
        return {"ok": False, "offline": True, "error": row.last_error}


async def load_cached_entitlement(db: AsyncSession) -> Optional[ent.Entitlement]:
    """Load and cryptographically re-verify the cached entitlement. Returns None if absent/invalid."""
    row = await _get_cache_row(db)
    if row is None or not row.entitlement_jws:
        return None
    try:
        return ent.verify_entitlement(row.entitlement_jws, keys.get_trusted_verify_keys())
    except ent.EntitlementError:
        return None  # expired (offline grace exhausted) or tampered -> treated as no entitlement


async def get_effective(db: AsyncSession) -> state_mod.EffectiveStatus:
    entitlement = await load_cached_entitlement(db)
    return state_mod.evaluate(entitlement)


async def count_active_users(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(User).where(User.is_active == True))).scalar_one()  # noqa: E712


async def seats_licensed(db: AsyncSession) -> int:
    entitlement = await load_cached_entitlement(db)
    return entitlement.seats_licensed if entitlement else 0


async def ensure_seat_available(db: AsyncSession) -> None:
    """Race-safe active-seat guard. MUST be called inside the same transaction that activates a user.

    Uses a transaction-scoped Postgres advisory lock so concurrent activations are serialized and can
    never exceed the licensed seat count. Owner counts as a seat; disabled users do not.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SEAT_ADVISORY_LOCK_KEY})
    limit = await seats_licensed(db)
    active = await count_active_users(db)
    if active >= limit:
        raise HTTPException(
            status_code=422,
            detail=f"Your RoofSpan subscription includes {limit} active users. Add another licensed seat to activate this user.",
        )


async def effective_state_cached() -> str:
    """Return the effective state string using a short-lived in-process snapshot (for middleware)."""
    now = time.monotonic()
    if _snapshot["state"] is not None and (now - _snapshot["at"]) < config.STATE_SNAPSHOT_TTL_SECONDS:
        return _snapshot["state"]
    async with SessionLocal() as db:
        status = await get_effective(db)
    _snapshot["state"] = status.effective_state
    _snapshot["at"] = now
    return status.effective_state


async def bootstrap(db: AsyncSession) -> None:
    """Startup: ensure installation identity and a cached entitlement exist."""
    await get_installation(db)
    if config.LICENSING_MODE == "http" and not await is_activated(db):
        # Fresh production install: nothing to refresh until the owner completes setup + activation.
        # Never sign a Control Plane request with the provisional local id (would 404 at the CP).
        return
    row = await _get_cache_row(db)
    if row is None or not row.entitlement_jws:
        await refresh(db, force=True)
