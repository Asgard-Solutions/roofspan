"""First-run installation onboarding state machine (durable, restart-safe).

RoofSpan Office is a single-company local Windows install. Before a brand-new installation can be
used it must be initialized: create the company + first Owner and purchase the mandatory initial
5-seat subscription. This module owns the durable local initialization state so the decision is
made server-side (never inferred from UI navigation) and survives backend/Windows restarts.

States: UNINITIALIZED -> OWNER_CREATED -> PAYMENT_PENDING -> ACTIVE (finalized/initialized).
Stored in the `app_config` table under key 'onboarding'. Once ACTIVE, the public bootstrap is
permanently closed.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import AppConfig, User

ONBOARDING_KEY = "onboarding"

UNINITIALIZED = "UNINITIALIZED"
OWNER_CREATED = "OWNER_CREATED"
PAYMENT_PENDING = "PAYMENT_PENDING"
ACTIVE = "ACTIVE"

# Non-sensitive public labels surfaced by GET /api/setup/status.
_LABEL = {
    UNINITIALIZED: "setup_required",
    OWNER_CREATED: "owner_created",
    PAYMENT_PENDING: "payment_required",
    ACTIVE: "initialized",
}

_snapshot: dict = {"state": None, "at": 0.0}
_TTL_SECONDS = 5.0


def invalidate_snapshot() -> None:
    _snapshot["state"] = None
    _snapshot["at"] = 0.0


async def _row(db: AsyncSession):
    return (await db.execute(select(AppConfig).where(AppConfig.key == ONBOARDING_KEY))).scalar_one_or_none()


async def get_record(db: AsyncSession) -> dict:
    r = await _row(db)
    if r and isinstance(r.value, dict):
        return dict(r.value)
    return {"state": UNINITIALIZED}


async def get_state(db: AsyncSession) -> str:
    return (await get_record(db)).get("state", UNINITIALIZED)


async def set_record(db: AsyncSession, value: dict) -> dict:
    """Persist the onboarding record (single commit). Callers must not hold an advisory xact lock
    they rely on across this call — this commits."""
    value = {**value, "updated_at": datetime.now(timezone.utc).isoformat()}
    r = await _row(db)
    if r is None:
        db.add(AppConfig(key=ONBOARDING_KEY, value=value))
    else:
        r.value = value
    await db.commit()
    invalidate_snapshot()
    return value


async def status_label(db: AsyncSession) -> str:
    return _LABEL.get(await get_state(db), "setup_required")


async def is_initialized(db: AsyncSession) -> bool:
    return (await get_state(db)) == ACTIVE


async def ensure_backfill(db: AsyncSession) -> None:
    """Idempotent: create the onboarding record if missing. An existing installation that already
    has users (legacy DB or dev owner seed) is treated as ACTIVE/initialized so it never re-enters
    setup; a truly empty install stays UNINITIALIZED."""
    if await _row(db) is not None:
        return
    users = (await db.execute(select(func.count(User.id)))).scalar_one()
    await set_record(db, {"state": ACTIVE if users > 0 else UNINITIALIZED, "backfilled": users > 0})


async def state_cached() -> str:
    """Short-lived in-process snapshot for the guard middleware (avoids a DB hit per request)."""
    from db import SessionLocal

    now = time.monotonic()
    if _snapshot["state"] is not None and (now - _snapshot["at"]) < _TTL_SECONDS:
        return _snapshot["state"]
    async with SessionLocal() as db:
        st = await get_state(db)
    _snapshot["state"] = st
    _snapshot["at"] = now
    return st
