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

from control_plane import config, keys as cp_keys, signer as cp_signer
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
        await cp_keys.validate_active_key(db)  # KMS mode: fail clearly if ACTIVE key != configured KMS key
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

def apply_billing_transitions(subscription, now=None) -> None:
    """Apply time-based billing transitions to a subscription (mutates in place):
      - due scheduled seat reduction -> seats lowered on/after the effective date
      - cancel_at_period_end + past period end -> CANCELLED
      - GRACE longer than the payment grace window -> SUSPENDED
    These are idempotent and safe to call on every issuance/sweep.
    """
    now = now or datetime.now(timezone.utc)
    if (subscription.pending_seats is not None and subscription.pending_seats_effective_at is not None
            and now >= subscription.pending_seats_effective_at):
        subscription.seats = max(config.MIN_SEATS, min(config.MAX_SEATS, subscription.pending_seats))
        subscription.pending_seats = None
        subscription.pending_seats_effective_at = None
    if (subscription.cancel_at_period_end and subscription.current_period_end
            and now >= subscription.current_period_end and subscription.state == "ACTIVE"):
        subscription.state = "CANCELLED"
    if (subscription.state == "GRACE" and subscription.grace_started_at
            and now >= subscription.grace_started_at + timedelta(days=config.PAYMENT_GRACE_DAYS)):
        subscription.state = "SUSPENDED"


async def _issue_entitlement(db: AsyncSession, *, installation: Installation, license_row: License,
                             subscription: Subscription, reason: str) -> str:
    signing = await cp_keys.ensure_active_key(db)
    now = datetime.now(timezone.utc)
    apply_billing_transitions(subscription, now)
    nonce = uuid.uuid4().hex
    scheduled_seats = subscription.pending_seats if subscription.pending_seats is not None else None
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
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "current_period_end": subscription.current_period_end,
        "scheduled_seats": scheduled_seats,
        "scheduled_seats_at": subscription.pending_seats_effective_at,
        "grace_started_at": subscription.grace_started_at,
    }
    token = ent.sign_entitlement_via_signer(
        signer=cp_signer.build_signer(signing.private_pem, signing.kid), kid=signing.kid, claims=claims)
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

    # Idempotency: a retried activation from the SAME installation (same public key) must NOT create a
    # duplicate company/installation. Reuse the existing identity and re-issue a fresh entitlement.
    existing = (await db.execute(
        select(Installation).where(Installation.public_key_pem == public_key_pem))).scalars().first()
    if existing is not None and existing.status == "ACTIVE":
        license_row = (await db.execute(
            select(License).where(License.installation_id == existing.id))).scalars().first()
        subscription = (await db.execute(
            select(Subscription).where(Subscription.company_id == existing.company_id))).scalar_one_or_none()
        if license_row is not None and subscription is not None:
            token = await _issue_entitlement(db, installation=existing, license_row=license_row,
                                             subscription=subscription, reason="activation-idempotent")
            await audit(db, actor=str(existing.id), action="installation.activate.idempotent",
                        entity_type="installation", entity_id=str(existing.id),
                        detail={"company_id": str(existing.company_id)})
            return {
                "installation_id": str(existing.id),
                "company_id": str(existing.company_id),
                "license_id": str(license_row.id),
                "entitlement_jws": token,
                "signing_public_keys": await cp_keys.public_keys(db),
            }

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
    # Activation registers identity ONLY — it does NOT grant paid access. The subscription starts in the
    # fail-closed non-active state (SUSPENDED, 0 usable seats) so Office stays locked until Stripe
    # confirms payment. Stripe is authoritative: a signature-verified webhook (checkout.session.completed
    # / customer.subscription.* / invoice.paid) flips this to ACTIVE with the PURCHASED seat quantity.
    subscription = Subscription(company_id=company.id, license_id=license_row.id, state="SUSPENDED", seats=0,
                                current_period_end=None)
    db.add(subscription)
    await db.commit()
    await db.refresh(installation)
    await db.refresh(license_row)
    await db.refresh(subscription)

    token = await _issue_entitlement(db, installation=installation, license_row=license_row,
                                     subscription=subscription, reason="activation")
    await audit(db, actor=str(installation.id), action="installation.activate", entity_type="installation",
                entity_id=str(installation.id), detail={"company_id": str(company.id),
                                                        "requested_seats": seats, "granted_seats": 0,
                                                        "state": "SUSPENDED", "software_version": software_version})
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

    # Events that mutate subscription (state or billing metadata) are subject to ordering.
    mutating = parsed.normalized_state is not None or parsed.event_type in ("CANCELLATION", "UNCANCELLATION")

    # Out-of-order guard: skip a mutation older than the newest processed event for this company.
    if mutating and company_uuid is not None and parsed.timestamp_ms is not None:
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
        applied_state = None
        if company_uuid is not None:
            applied_state = await _apply_billing_event(db, company_id=company_uuid, event_type=parsed.event_type,
                                                       normalized_state=parsed.normalized_state)
        evt.status = "processed"
        evt.resulting_state = applied_state
        await db.commit()
    except Exception as e:  # record failure without exposing internals
        evt.status = "error"
        evt.error = str(e)[:400]
        await db.commit()
        raise CPError(500, "Failed to process billing event")

    await audit(db, actor="billing", action="billing.event.processed", entity_type="company",
                entity_id=parsed.company_reference,
                detail={"event_type": parsed.event_type, "state": applied_state})
    return {"ok": True, "status": "processed", "event_id": parsed.event_id, "state": applied_state}


async def _apply_billing_event(db: AsyncSession, *, company_id, event_type: str, normalized_state: str | None) -> str | None:
    """Apply event-specific billing effects per the locked C2 rules. Returns the resulting state."""
    sub = (await db.execute(select(Subscription).where(Subscription.company_id == company_id))).scalar_one_or_none()
    if sub is None:
        return None
    now = datetime.now(timezone.utc)
    period_end = now + timedelta(days=config.BILLING_PERIOD_DAYS)
    if event_type == "CANCELLATION":
        # Auto-renew off: remain ACTIVE through the paid period; CANCELLED only at period end.
        sub.cancel_at_period_end = True
        if sub.current_period_end is None:
            sub.current_period_end = period_end
    elif event_type == "UNCANCELLATION":
        sub.cancel_at_period_end = False
        if sub.state == "ACTIVE":
            sub.state = "ACTIVE"
    elif normalized_state == "GRACE":
        if sub.state != "GRACE":
            sub.grace_started_at = now
        sub.state = "GRACE"
    elif normalized_state == "ACTIVE":
        sub.state = "ACTIVE"
        sub.grace_started_at = None
        sub.cancel_at_period_end = False
        sub.current_period_end = period_end
    elif normalized_state == "SUSPENDED":
        sub.state = "SUSPENDED"
    elif normalized_state == "CANCELLED":
        sub.state = "CANCELLED"
    await db.commit()
    return sub.state


async def set_subscription_seats(db: AsyncSession, *, company_id: str, seats: int) -> dict:
    """Seat increase = immediate; seat decrease = scheduled for the next billing date (locked rule)."""
    seats = max(config.MIN_SEATS, min(config.MAX_SEATS, int(seats)))
    sub = (await db.execute(select(Subscription).where(Subscription.company_id == uuid.UUID(company_id)))).scalar_one_or_none()
    if sub is None:
        raise CPError(404, "Unknown company subscription")
    if seats >= sub.seats:
        sub.seats = seats
        sub.pending_seats = None
        sub.pending_seats_effective_at = None
        result = {"effect": "immediate", "seats": seats}
    else:
        sub.pending_seats = seats
        sub.pending_seats_effective_at = sub.current_period_end or (datetime.now(timezone.utc) + timedelta(days=config.BILLING_PERIOD_DAYS))
        result = {"effect": "scheduled", "current_seats": sub.seats, "pending_seats": seats,
                  "effective_at": sub.pending_seats_effective_at.isoformat()}
    await db.commit()
    await audit(db, actor="admin", action="subscription.seats", entity_type="company", entity_id=company_id, detail=result)
    return result


async def sweep_billing(db: AsyncSession) -> dict:
    """Apply time-based transitions (grace expiry, cancellation at period end, scheduled seat reductions)
    across all subscriptions. Safe to run periodically (cron)."""
    subs = (await db.execute(select(Subscription))).scalars().all()
    changed = 0
    for sub in subs:
        before = (sub.state, sub.seats)
        apply_billing_transitions(sub)
        if (sub.state, sub.seats) != before:
            changed += 1
    await db.commit()
    return {"swept": len(subs), "changed": changed}


# ---------------- Stripe billing engine (authoritative) ----------------

async def _find_subscription_for_event(db: AsyncSession, parsed):
    """Resolve the CP Subscription row for a Stripe event, by company_id -> sub id -> customer id."""
    from control_plane.models import Subscription as _Sub
    # 1) company reference (metadata/client_reference_id) if it is a valid company UUID
    if parsed.company_reference:
        try:
            cu = uuid.UUID(parsed.company_reference)
            sub = (await db.execute(select(_Sub).where(_Sub.company_id == cu))).scalar_one_or_none()
            if sub is not None:
                return sub
        except (ValueError, Exception):
            pass
    # 2) by stripe subscription id
    if parsed.provider_subscription_id:
        sub = (await db.execute(select(_Sub).where(_Sub.provider_subscription_id == parsed.provider_subscription_id))).scalar_one_or_none()
        if sub is not None:
            return sub
    # 3) by stripe customer id
    if parsed.provider_customer_id:
        sub = (await db.execute(select(_Sub).where(_Sub.provider_customer_id == parsed.provider_customer_id))).scalar_one_or_none()
        if sub is not None:
            return sub
    return None


async def _apply_stripe_event(db: AsyncSession, *, parsed, provider) -> str | None:
    sub = await _find_subscription_for_event(db, parsed)
    if sub is None:
        return None
    now = datetime.now(timezone.utc)
    sub.provider = "stripe"
    if parsed.provider_customer_id:
        sub.provider_customer_id = parsed.provider_customer_id
    if parsed.provider_subscription_id:
        sub.provider_subscription_id = parsed.provider_subscription_id

    if parsed.event_type == "checkout.session.completed":
        # Fetch authoritative subscription details (seats/period/cancel) from Stripe.
        if parsed.provider_subscription_id:
            norm = provider.normalize_subscription(provider.retrieve_subscription(parsed.provider_subscription_id))
            sub.seats = norm["seats"] or sub.seats
            sub.current_period_end = norm["current_period_end"] or sub.current_period_end
            sub.cancel_at_period_end = bool(norm["cancel_at_period_end"])
        sub.state = "ACTIVE"
        sub.grace_started_at = None
    elif parsed.normalized_state == "GRACE":
        if sub.state != "GRACE":
            sub.grace_started_at = now
        sub.state = "GRACE"
    elif parsed.normalized_state == "ACTIVE":
        sub.state = "ACTIVE"
        sub.grace_started_at = None
        if parsed.seats is not None:
            # Stripe quantity is authoritative (a scheduled decrease materialized at renewal clears pending).
            if sub.pending_seats is not None and parsed.seats == sub.pending_seats:
                sub.pending_seats = None
                sub.pending_seats_effective_at = None
            sub.seats = parsed.seats
        if parsed.current_period_end is not None:
            sub.current_period_end = parsed.current_period_end
        if parsed.cancel_at_period_end is not None:
            sub.cancel_at_period_end = parsed.cancel_at_period_end
    elif parsed.normalized_state == "SUSPENDED":
        sub.state = "SUSPENDED"
    elif parsed.normalized_state == "CANCELLED":
        sub.state = "CANCELLED"
    await db.commit()
    return sub.state


async def process_stripe_webhook(db: AsyncSession, *, headers: dict, body: bytes) -> dict:
    """Verify a Stripe webhook (signature), idempotently record it, guard ordering, and transition state.

    Stripe is the authoritative billing engine: signature-verified event -> normalized boundary ->
    subscription state. No card data is ever stored.
    """
    from control_plane import billing as cp_billing
    from control_plane.models import BillingEvent

    provider = cp_billing.get_stripe_provider()
    try:
        parsed = provider.verify_and_parse_webhook(headers, body, {})
    except cp_billing.BillingAuthError as e:
        raise CPError(401, str(e))
    if not parsed.event_id:
        raise CPError(400, "Missing event id")

    existing = (await db.execute(select(BillingEvent).where(BillingEvent.event_id == parsed.event_id))).scalar_one_or_none()
    if existing is not None:
        return {"ok": True, "status": "duplicate", "event_id": parsed.event_id}

    evt = BillingEvent(provider="stripe", event_id=parsed.event_id, event_type=parsed.event_type,
                       event_timestamp_ms=parsed.timestamp_ms, company_reference=parsed.company_reference,
                       status="received")
    db.add(evt)
    await db.commit()

    # Out-of-order guard: skip a state mutation older than the newest processed event for this reference.
    if parsed.normalized_state is not None and parsed.company_reference and parsed.timestamp_ms is not None:
        newest = (await db.execute(
            select(BillingEvent.event_timestamp_ms)
            .where(BillingEvent.provider == "stripe",
                   BillingEvent.company_reference == parsed.company_reference,
                   BillingEvent.status == "processed", BillingEvent.event_timestamp_ms.isnot(None))
            .order_by(BillingEvent.event_timestamp_ms.desc()).limit(1))).scalar_one_or_none()
        if newest is not None and parsed.timestamp_ms < newest:
            evt.status = "ignored"
            evt.error = "out-of-order (older than last processed)"
            await db.commit()
            return {"ok": True, "status": "ignored", "event_id": parsed.event_id}

    try:
        applied = await _apply_stripe_event(db, parsed=parsed, provider=provider)
        evt.status = "processed"
        evt.resulting_state = applied
        await db.commit()
    except Exception as e:
        evt.status = "error"
        evt.error = str(e)[:400]
        await db.commit()
        raise CPError(500, "Failed to process billing event")

    await audit(db, actor="billing", action="billing.stripe.processed", entity_type="company",
                entity_id=parsed.company_reference, detail={"event_type": parsed.event_type, "state": applied})
    return {"ok": True, "status": "processed", "event_id": parsed.event_id, "state": applied}


async def _get_sub(db: AsyncSession, company_id: str):
    from control_plane.models import Subscription as _Sub
    sub = (await db.execute(select(_Sub).where(_Sub.company_id == uuid.UUID(company_id)))).scalar_one_or_none()
    if sub is None:
        raise CPError(404, "Unknown company subscription")
    return sub


async def stripe_create_checkout(db: AsyncSession, *, company_id: str, seats: int | None, origin_url: str | None) -> dict:
    from control_plane import billing as cp_billing
    sub = await _get_sub(db, company_id)
    provider = cp_billing.get_stripe_provider()
    want = seats if seats is not None else max(config.MIN_SEATS, sub.seats)
    try:
        url = provider.create_checkout_session(company_id, want, origin_url)
    except cp_billing.BillingAuthError as e:
        raise CPError(400, str(e))
    await audit(db, actor="admin", action="billing.stripe.checkout", entity_type="company", entity_id=company_id,
                detail={"seats": provider._clamp(want)})
    return {"url": url, "company_id": company_id, "seats": provider._clamp(want)}


async def stripe_update_seats(db: AsyncSession, *, company_id: str, seats: int) -> dict:
    from control_plane import billing as cp_billing
    sub = await _get_sub(db, company_id)
    provider = cp_billing.get_stripe_provider()
    if not sub.provider_subscription_id:
        raise CPError(409, "No active Stripe subscription — complete checkout first")
    seats = max(config.MIN_SEATS, min(config.MAX_SEATS, int(seats)))
    try:
        result = provider.update_seats(sub.provider_subscription_id, seats)
    except cp_billing.BillingAuthError as e:
        raise CPError(400, str(e))
    if result["effect"] == "immediate":
        sub.seats = seats
        sub.pending_seats = None
        sub.pending_seats_effective_at = None
    else:
        sub.pending_seats = seats
        sub.pending_seats_effective_at = result.get("effective_at") or sub.current_period_end
        result["effective_at"] = sub.pending_seats_effective_at.isoformat() if sub.pending_seats_effective_at else None
    await db.commit()
    await audit(db, actor="admin", action="billing.stripe.seats", entity_type="company", entity_id=company_id, detail=result)
    return result


async def stripe_set_cancel(db: AsyncSession, *, company_id: str, cancel: bool) -> dict:
    from control_plane import billing as cp_billing
    sub = await _get_sub(db, company_id)
    provider = cp_billing.get_stripe_provider()
    if not sub.provider_subscription_id:
        raise CPError(409, "No active Stripe subscription")
    try:
        result = provider.set_cancel_at_period_end(sub.provider_subscription_id, cancel)
    except cp_billing.BillingAuthError as e:
        raise CPError(400, str(e))
    sub.cancel_at_period_end = result["cancel_at_period_end"]
    if result.get("current_period_end"):
        sub.current_period_end = result["current_period_end"]
    await db.commit()
    await audit(db, actor="admin", action="billing.stripe.cancel", entity_type="company", entity_id=company_id,
                detail={"cancel_at_period_end": sub.cancel_at_period_end})
    return {"cancel_at_period_end": sub.cancel_at_period_end,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None}


async def stripe_portal(db: AsyncSession, *, company_id: str, return_url: str | None) -> dict:
    from control_plane import billing as cp_billing
    sub = await _get_sub(db, company_id)
    provider = cp_billing.get_stripe_provider()
    if not sub.provider_customer_id:
        raise CPError(409, "No Stripe customer yet — complete checkout first")
    try:
        url = provider.create_portal_session(sub.provider_customer_id, return_url)
    except cp_billing.BillingAuthError as e:
        raise CPError(400, str(e))
    return {"url": url, "company_id": company_id}


async def stripe_reconcile(db: AsyncSession, *, company_id: str) -> dict:
    from control_plane import billing as cp_billing
    sub = await _get_sub(db, company_id)
    provider = cp_billing.get_stripe_provider()
    if not sub.provider_subscription_id:
        raise CPError(409, "No Stripe subscription to reconcile")
    norm = provider.normalize_subscription(provider.retrieve_subscription(sub.provider_subscription_id))
    if norm["state"]:
        sub.state = norm["state"]
    if norm["seats"]:
        sub.seats = norm["seats"]
    if norm["current_period_end"]:
        sub.current_period_end = norm["current_period_end"]
    sub.cancel_at_period_end = bool(norm["cancel_at_period_end"])
    if norm["state"] == "ACTIVE":
        sub.grace_started_at = None
    await db.commit()
    await audit(db, actor="admin", action="billing.stripe.reconcile", entity_type="company", entity_id=company_id,
                detail={"state": norm["state"], "seats": norm["seats"]})
    return norm


# ---------------- pairing + version (Phase C3) ----------------

import random  # noqa: E402


def _version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except ValueError:
        return (0,)


async def create_pairing(db: AsyncSession, *, installation_id: str) -> dict:
    """Issue a short-lived, single-use pairing token (QR + numeric fallback). No secrets in payload."""
    from control_plane.models import PairingToken
    now = datetime.now(timezone.utc)
    token = uuid.uuid4().hex
    numeric = f"{random.randint(0, 999999):06d}"
    expires = now + timedelta(seconds=config.PAIRING_TTL_SECONDS)
    db.add(PairingToken(token=token, numeric_code=numeric, installation_id=uuid.UUID(installation_id), expires_at=expires))
    await db.commit()
    await audit(db, actor=installation_id, action="pairing.create", entity_type="installation", entity_id=installation_id)
    qr_payload = {"v": config.PROTOCOL_VERSION, "installation_id": installation_id, "token": token,
                  "relay": config.RELAY_ENDPOINT, "expires_at": int(expires.timestamp())}
    return {"token": token, "numeric_code": numeric, "expires_at": expires.isoformat(),
            "relay_endpoint": config.RELAY_ENDPOINT, "protocol_version": config.PROTOCOL_VERSION,
            "qr_payload": qr_payload}


async def resolve_pairing(db: AsyncSession, *, token: str | None, numeric_code: str | None, label: str | None) -> dict:
    """Mobile resolves a pairing token/code -> installation binding + relay endpoint (no secrets).
    Consumes the token (single-use) and registers the device."""
    from control_plane.models import PairingToken, MobileDevice
    now = datetime.now(timezone.utc)
    q = select(PairingToken)
    if token:
        q = q.where(PairingToken.token == token)
    elif numeric_code:
        q = q.where(PairingToken.numeric_code == numeric_code)
    else:
        raise CPError(400, "token or numeric_code required")
    pt = (await db.execute(q.order_by(PairingToken.created_at.desc()))).scalars().first()
    if pt is None:
        raise CPError(404, "Invalid pairing code")
    if pt.used_at is not None:
        raise CPError(409, "Pairing code already used")
    if now > pt.expires_at:
        raise CPError(410, "Pairing code expired")
    pt.used_at = now
    import secrets as _secrets
    import hashlib as _hashlib
    device_secret = _secrets.token_urlsafe(32)  # durable per-device credential — returned ONCE
    device = MobileDevice(installation_id=pt.installation_id, label=label, status="ACTIVE", last_seen_at=now,
                          credential_hash=_hashlib.sha256(device_secret.encode()).hexdigest())
    db.add(device)
    await db.commit()
    await db.refresh(device)
    await audit(db, actor=str(pt.installation_id), action="pairing.resolve", entity_type="mobile_device", entity_id=str(device.id))
    vp = await get_version_policy(db)
    return {"installation_id": str(pt.installation_id), "device_id": str(device.id),
            "device_credential": device_secret,  # store in Mobile secure storage; never returned again
            "relay_endpoint": config.RELAY_ENDPOINT, "protocol_version": config.PROTOCOL_VERSION,
            "min_mobile_version": vp.mobile_min_supported}


async def list_devices(db: AsyncSession, *, installation_id: str) -> list[dict]:
    from control_plane.models import MobileDevice
    rows = (await db.execute(select(MobileDevice).where(MobileDevice.installation_id == uuid.UUID(installation_id))
                             .order_by(MobileDevice.paired_at.desc()))).scalars().all()
    return [{"id": str(d.id), "label": d.label, "status": d.status, "paired_at": d.paired_at.isoformat(),
             "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None} for d in rows]


async def revoke_device(db: AsyncSession, *, device_id: str) -> None:
    from control_plane.models import MobileDevice
    d = (await db.execute(select(MobileDevice).where(MobileDevice.id == uuid.UUID(device_id)))).scalar_one_or_none()
    if d is None:
        raise CPError(404, "Unknown device")
    d.status = "REVOKED"
    d.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await audit(db, actor="admin", action="mobile_device.revoke", entity_type="mobile_device", entity_id=device_id)


async def version_check(db: AsyncSession, *, app_version: str) -> dict:
    vp = await get_version_policy(db)
    cur, minimum, latest = _version_tuple(app_version), _version_tuple(vp.mobile_min_supported), _version_tuple(vp.mobile_latest)
    if cur < minimum:
        status = "must_update"
    elif cur < latest:
        status = "update_available"
    else:
        status = "ok"
    return {"status": status, "latest": vp.mobile_latest, "min_supported": vp.mobile_min_supported,
            "mandatory": vp.mobile_update_mandatory}


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
