"""Control Plane service logic: init, activation, entitlement issuance/refresh, installation auth +
replay protection, revocation, key rotation, subscription updates, version policy, audit."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, unquote

import psycopg
from psycopg import sql
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane import config, keys as cp_keys
from control_plane.db import engine, CPBase, SessionLocal
from control_plane.models import (
    Company, Installation, License, Subscription, EntitlementIssuance, VersionPolicy,
    RequestNonce, CPAuditLog, SigningKey,
)
from licensing import entitlement as ent
from licensing import reqsig

logger = logging.getLogger("roofspan")


class CPError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


# ---------------- init ----------------

def _ensure_database() -> None:
    """Create the Control Plane database if it does not exist (dev/in-container convenience)."""
    url = config.CONTROL_PLANE_DATABASE_URL.replace("+asyncpg", "").replace("+psycopg", "")
    p = urlparse(url)
    dbname = (p.path or "/").lstrip("/")
    args = dict(host=p.hostname, port=p.port or 5432, user=unquote(p.username or ""),
                password=unquote(p.password or ""), connect_timeout=5)
    try:
        with psycopg.connect(dbname=dbname, **args):
            return
    except psycopg.OperationalError as e:
        if "does not exist" not in str(e):
            raise
    with psycopg.connect(dbname="postgres", autocommit=True, **args) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    logger.info("Created Control Plane database '%s'", dbname)


async def init_control_plane() -> None:
    """Ensure DB + schema + a signing key + a version-policy row exist. Idempotent."""
    _ensure_database()
    async with engine.begin() as conn:
        await conn.run_sync(CPBase.metadata.create_all)
    async with SessionLocal() as db:
        await cp_keys.ensure_active_key(db)
        vp = (await db.execute(select(VersionPolicy).where(VersionPolicy.key == "default"))).scalar_one_or_none()
        if vp is None:
            db.add(VersionPolicy(key="default", office_min_supported=config.MIN_SUPPORTED_VERSION,
                                 mobile_min_supported=config.MIN_SUPPORTED_VERSION))
            await db.commit()


# ---------------- audit ----------------

async def audit(db: AsyncSession, *, actor: str, action: str, entity_type: str | None = None,
                entity_id: str | None = None, detail: dict | None = None) -> None:
    db.add(CPAuditLog(actor=actor, action=action, entity_type=entity_type,
                      entity_id=str(entity_id) if entity_id else None, detail=detail))
    await db.commit()


# ---------------- entitlement issuance ----------------

async def _issue_entitlement(db: AsyncSession, *, installation: Installation, license_row: License,
                             subscription: Subscription, reason: str) -> str:
    signing = await cp_keys.ensure_active_key(db)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    claims = {
        "installation_id": str(installation.id),
        "company_id": str(installation.company_id),
        "license_id": str(license_row.id),
        "subscription_state": subscription.state,
        "seats_licensed": subscription.seats,
        "product": license_row.product,
        "min_supported_version": config.MIN_SUPPORTED_VERSION,
        "issued_at": now,
        "refresh_at": now + timedelta(hours=config.REFRESH_INTERVAL_HOURS),
        "grace_until": now + timedelta(days=config.OFFLINE_GRACE_DAYS),
        "nonce": nonce,
    }
    token = ent.sign_entitlement(private_key=cp_keys.load_private(signing), kid=signing.kid, claims=claims)
    db.add(EntitlementIssuance(
        installation_id=installation.id, license_id=license_row.id, kid=signing.kid,
        subscription_state=subscription.state, seats=subscription.seats, reason=reason,
        issued_at=now, refresh_at=claims["refresh_at"], grace_until=claims["grace_until"], nonce=nonce,
    ))
    await db.commit()
    return token


# ---------------- activation ----------------

async def activate(db: AsyncSession, *, company_name: str, requested_seats: int, public_key_pem: str,
                   software_version: str, bootstrap_credential: str) -> dict:
    if bootstrap_credential != config.DEV_BOOTSTRAP_SECRET:
        raise CPError(401, "Invalid activation credential")
    seats = max(config.MIN_SEATS, min(config.MAX_SEATS, int(requested_seats)))

    company = Company(name=company_name or "")
    db.add(company)
    await db.flush()
    installation = Installation(company_id=company.id, public_key_pem=public_key_pem,
                                software_version=software_version, status="ACTIVE")
    db.add(installation)
    await db.flush()
    license_row = License(company_id=company.id, installation_id=installation.id, product=config.PRODUCT)
    db.add(license_row)
    await db.flush()
    subscription = Subscription(company_id=company.id, license_id=license_row.id, state="ACTIVE", seats=seats)
    db.add(subscription)
    await db.commit()
    await db.refresh(installation)
    await db.refresh(license_row)
    await db.refresh(subscription)

    token = await _issue_entitlement(db, installation=installation, license_row=license_row,
                                     subscription=subscription, reason="activation")
    await audit(db, actor=str(installation.id), action="installation.activate", entity_type="installation",
                entity_id=str(installation.id), detail={"company_id": str(company.id), "seats": seats,
                                                        "software_version": software_version})
    return {
        "installation_id": str(installation.id),
        "company_id": str(company.id),
        "license_id": str(license_row.id),
        "entitlement_jws": token,
        "signing_public_keys": await cp_keys.public_keys(db),
    }


# ---------------- installation-authenticated refresh ----------------

async def _verify_installation_request(db: AsyncSession, *, installation_id: str, timestamp: str,
                                       nonce: str, body: bytes, signature_b64: str) -> Installation:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        raise CPError(401, "Invalid timestamp")
    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - ts) > config.REQUEST_TIMESTAMP_TOLERANCE:
        raise CPError(401, "Request timestamp outside allowed tolerance")

    try:
        inst = (await db.execute(select(Installation).where(Installation.id == uuid.UUID(installation_id)))).scalar_one_or_none()
    except (ValueError, Exception):
        inst = None
    if inst is None:
        raise CPError(404, "Unknown installation")
    if inst.status != "ACTIVE":
        raise CPError(403, "Installation identity is revoked")

    if not reqsig.verify_request(inst.public_key_pem, installation_id=installation_id, timestamp=timestamp,
                                 nonce=nonce, body=body, signature_b64=signature_b64):
        raise CPError(401, "Invalid request signature")

    # Replay protection: reject a re-used nonce within the retention window.
    await db.execute(delete(RequestNonce).where(RequestNonce.expires_at < datetime.now(timezone.utc)))
    existing = (await db.execute(select(RequestNonce).where(RequestNonce.nonce == nonce))).scalar_one_or_none()
    if existing is not None:
        await db.commit()
        raise CPError(409, "Replay detected (nonce already used)")
    db.add(RequestNonce(nonce=nonce, installation_id=inst.id,
                        expires_at=datetime.now(timezone.utc) + timedelta(seconds=config.NONCE_RETENTION_SECONDS)))
    inst.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    return inst


async def refresh_entitlement(db: AsyncSession, *, installation_id: str, timestamp: str, nonce: str,
                              body: bytes, signature_b64: str) -> dict:
    inst = await _verify_installation_request(db, installation_id=installation_id, timestamp=timestamp,
                                              nonce=nonce, body=body, signature_b64=signature_b64)
    license_row = (await db.execute(select(License).where(License.installation_id == inst.id))).scalars().first()
    if license_row is None:
        raise CPError(404, "No license for installation")
    subscription = (await db.execute(select(Subscription).where(Subscription.company_id == inst.company_id))).scalar_one_or_none()
    if subscription is None:
        raise CPError(404, "No subscription for company")
    token = await _issue_entitlement(db, installation=inst, license_row=license_row,
                                     subscription=subscription, reason="refresh")
    await audit(db, actor=str(inst.id), action="entitlement.issue", entity_type="installation",
                entity_id=str(inst.id), detail={"reason": "refresh", "state": subscription.state, "seats": subscription.seats})
    return {"entitlement_jws": token, "signing_public_keys": await cp_keys.public_keys(db)}


# ---------------- admin actions (dev-guarded) ----------------

async def revoke_installation(db: AsyncSession, *, installation_id: str) -> None:
    inst = (await db.execute(select(Installation).where(Installation.id == uuid.UUID(installation_id)))).scalar_one_or_none()
    if inst is None:
        raise CPError(404, "Unknown installation")
    inst.status = "REVOKED"
    inst.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await audit(db, actor="admin", action="installation.revoke", entity_type="installation", entity_id=str(inst.id))


async def rotate_signing_key(db: AsyncSession) -> str:
    row = await cp_keys.rotate_key(db)
    await audit(db, actor="admin", action="signing_key.rotate", entity_type="signing_key", entity_id=row.kid)
    return row.kid


async def set_subscription(db: AsyncSession, *, company_id: str, state: str, seats: int) -> Subscription:
    if state not in ent.VALID_STATES:
        raise CPError(422, "Invalid subscription state")
    seats = max(config.MIN_SEATS, min(config.MAX_SEATS, int(seats)))
    sub = (await db.execute(select(Subscription).where(Subscription.company_id == uuid.UUID(company_id)))).scalar_one_or_none()
    if sub is None:
        raise CPError(404, "Unknown company subscription")
    sub.state = state
    sub.seats = seats
    await db.commit()
    await db.refresh(sub)
    await audit(db, actor="admin", action="subscription.update", entity_type="company", entity_id=company_id,
                detail={"state": state, "seats": seats})
    return sub


async def get_version_policy(db: AsyncSession) -> VersionPolicy:
    vp = (await db.execute(select(VersionPolicy).where(VersionPolicy.key == "default"))).scalar_one_or_none()
    if vp is None:
        vp = VersionPolicy(key="default")
        db.add(vp)
        await db.commit()
        await db.refresh(vp)
    return vp


async def update_version_policy(db: AsyncSession, changes: dict) -> VersionPolicy:
    vp = await get_version_policy(db)
    for k, v in changes.items():
        if v is not None and hasattr(vp, k):
            setattr(vp, k, v)
    await db.commit()
    await db.refresh(vp)
    await audit(db, actor="admin", action="version_policy.update", entity_type="version_policy",
                entity_id="default", detail={k: v for k, v in changes.items() if v is not None})
    return vp
