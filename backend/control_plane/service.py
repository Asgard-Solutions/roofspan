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
    """Ensure DB + schema (via Alembic) + a signing key + a version-policy row exist. Idempotent."""
    import asyncio
    from control_plane.migrations_runner import run_cp_migrations
    await asyncio.to_thread(run_cp_migrations)
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


# ---------------- billing (Phase C2) ----------------

async def _apply_subscription_state(db: AsyncSession, *, company_id, state: str | None, seats: int | None) -> None:
    if state is None and seats is None:
        return
    sub = (await db.execute(select(Subscription).where(Subscription.company_id == company_id))).scalar_one_or_none()
    if sub is None:
        return
    if state is not None:
        sub.state = state
    if seats is not None:
        sub.seats = max(config.MIN_SEATS, min(config.MAX_SEATS, int(seats)))
    await db.commit()


async def process_webhook(db: AsyncSession, *, headers: dict, body: bytes) -> dict:
    """Validate + idempotently process a billing webhook, then transition subscription state.

    A webhook can NEVER bypass the normalized boundary: provider event -> validation -> normalized
    event -> subscription state transition. Only verified normalized state changes licensing state.
    """
    import json
    from control_plane import billing as cp_billing
    from control_plane.models import BillingEvent

    provider = cp_billing.get_provider()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (ValueError, UnicodeDecodeError):
        raise CPError(400, "Invalid webhook body")
    try:
        parsed = provider.verify_and_parse_webhook(headers, body, payload)
    except cp_billing.BillingAuthError as e:
        raise CPError(401, str(e))
    if not parsed.event_id:
        raise CPError(400, "Missing event id")

    # Idempotency: reject duplicate delivery by unique event_id.
    existing = (await db.execute(select(BillingEvent).where(BillingEvent.event_id == parsed.event_id))).scalar_one_or_none()
    if existing is not None:
        return {"ok": True, "status": "duplicate", "event_id": parsed.event_id}

    company_uuid = None
    if parsed.company_reference:
        try:
            company_uuid = uuid.UUID(parsed.company_reference)
        except ValueError:
            company_uuid = None

    evt = BillingEvent(provider=provider.name, event_id=parsed.event_id, event_type=parsed.event_type,
                       event_timestamp_ms=parsed.timestamp_ms, company_reference=parsed.company_reference,
                       status="received")
    db.add(evt)
    await db.commit()

    # Out-of-order guard: skip a state change older than the newest processed event for this company.
    if parsed.normalized_state is not None and company_uuid is not None and parsed.timestamp_ms is not None:
        newest = (await db.execute(
            select(BillingEvent.event_timestamp_ms)
            .where(BillingEvent.company_reference == parsed.company_reference,
                   BillingEvent.status == "processed",
                   BillingEvent.event_timestamp_ms.isnot(None))
            .order_by(BillingEvent.event_timestamp_ms.desc()).limit(1)
        )).scalar_one_or_none()
        if newest is not None and parsed.timestamp_ms < newest:
            evt.status = "ignored"
            evt.error = "out-of-order (older than last processed)"
            await db.commit()
            await audit(db, actor="billing", action="billing.event.ignored", entity_type="company",
                        entity_id=parsed.company_reference, detail={"event_type": parsed.event_type})
            return {"ok": True, "status": "ignored", "event_id": parsed.event_id}

    try:
        if parsed.normalized_state is not None and company_uuid is not None:
            await _apply_subscription_state(db, company_id=company_uuid, state=parsed.normalized_state, seats=None)
        evt.status = "processed"
        evt.resulting_state = parsed.normalized_state
        await db.commit()
    except Exception as e:  # record failure without exposing internals
        evt.status = "error"
        evt.error = str(e)[:400]
        await db.commit()
        raise CPError(500, "Failed to process billing event")

    await audit(db, actor="billing", action="billing.event.processed", entity_type="company",
                entity_id=parsed.company_reference,
                detail={"event_type": parsed.event_type, "state": parsed.normalized_state})
    return {"ok": True, "status": "processed", "event_id": parsed.event_id, "state": parsed.normalized_state}


async def reconcile_subscription(db: AsyncSession, *, company_id: str) -> dict:
    """Provider reconciliation: authoritatively re-derive current subscription state from the provider
    (recovers from missed/delayed/out-of-order webhooks). Provider-neutral."""
    from control_plane import billing as cp_billing
    provider = cp_billing.get_provider()
    try:
        result = await provider.reconcile(company_id)
    except cp_billing.BillingAuthError as e:
        raise CPError(400, str(e))
    await _apply_subscription_state(db, company_id=uuid.UUID(company_id),
                                    state=result.get("state"), seats=result.get("seats"))
    await audit(db, actor="admin", action="billing.reconcile", entity_type="company", entity_id=company_id,
                detail={"state": result.get("state")})
    return result


async def checkout_url(company_id: str) -> str:
    from control_plane import billing as cp_billing
    try:
        return cp_billing.get_provider().checkout_url(company_id)
    except cp_billing.BillingAuthError as e:
        raise CPError(400, str(e))


async def portal_url(company_id: str) -> str | None:
    from control_plane import billing as cp_billing
    try:
        return await cp_billing.get_provider().portal_url(company_id)
    except cp_billing.BillingAuthError as e:
        raise CPError(400, str(e))
