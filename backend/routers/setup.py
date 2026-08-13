"""First-run setup / installation bootstrap API.

Drives the customer onboarding wizard: company + first Owner, then the mandatory initial 5-seat
subscription checkout, then activation. All endpoints are reachable while the installation is not yet
initialized (the subscription guard allowlists /api/setup). The bootstrap that creates the first
Owner is permanently closed once initialization completes.

Billing is provider-neutral: the checkout URL comes from the configured provider (mock in dev/test,
Stripe hosted checkout in production). In dev/mock mode a confirmed payment finalizes locally with a
deterministic 5-seat entitlement (NOT the 1000-seat dev convenience default) so seat enforcement is
genuinely exercised.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User, AppConfig
from core import hash_password, create_access_token, require_roles, log_action
import onboarding
from licensing import config as lic_config, service as lic_service, control_plane as lic_cp
from licensing.control_plane import ControlPlaneUnavailable

logger = logging.getLogger("roofspan.setup")

router = APIRouter(prefix="/api/setup", tags=["setup"])

_SETUP_LOCK = 728419  # advisory lock key serializing concurrent bootstraps
SEAT_PRICE_USD = 49
INITIAL_SEATS = lic_config.MIN_SEATS  # 5


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str = ""
    address: str = ""


class OwnerIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8)
    confirm_password: str


class BootstrapIn(BaseModel):
    company: CompanyIn
    owner: OwnerIn


@router.get("/status")
async def setup_status(db: AsyncSession = Depends(get_db)):
    """Unauthenticated, non-sensitive: tells the local UI which entry screen to show."""
    await onboarding.ensure_backfill(db)
    users = (await db.execute(select(func.count(User.id)))).scalar_one()
    return {
        "state": await onboarding.status_label(db),
        "owner_exists": users > 0,
        "seats": INITIAL_SEATS,
        "monthly_price_usd": INITIAL_SEATS * SEAT_PRICE_USD,
    }


@router.post("/bootstrap", status_code=201)
async def bootstrap(payload: BootstrapIn, request: Request, db: AsyncSession = Depends(get_db)):
    """Create the company profile + the first Owner (licensed seat #1). Only works on a genuinely
    uninitialized installation; permanently refuses once an Owner/company exists or setup completed."""
    if payload.owner.password != payload.owner.confirm_password:
        raise HTTPException(status_code=422, detail="Passwords do not match")

    # Serialize concurrent bootstraps; re-check state inside the lock (guards races/repeat bootstrap).
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SETUP_LOCK})
    onb_row = (await db.execute(select(AppConfig).where(AppConfig.key == onboarding.ONBOARDING_KEY))).scalar_one_or_none()
    state = onb_row.value.get("state") if (onb_row and isinstance(onb_row.value, dict)) else None
    users = (await db.execute(select(func.count(User.id)))).scalar_one()
    if users > 0 or (state and state != onboarding.UNINITIALIZED):
        raise HTTPException(status_code=409, detail="RoofSpan Office is already set up. Please sign in instead.")

    email = payload.owner.email.lower().strip()
    owner = User(
        email=email,
        full_name=payload.owner.full_name.strip(),
        password_hash=hash_password(payload.owner.password),
        role="owner",
        is_active=True,
    )
    db.add(owner)

    company_value = {
        "name": payload.company.name.strip(),
        "phone": payload.company.phone.strip(),
        "email": str(payload.company.email).lower().strip(),
        "address": payload.company.address.strip(),
        "license_number": "",
    }
    comp_row = (await db.execute(select(AppConfig).where(AppConfig.key == "company_profile"))).scalar_one_or_none()
    if comp_row is None:
        db.add(AppConfig(key="company_profile", value=company_value))
    else:
        comp_row.value = company_value

    company_id = str(uuid.uuid4())
    onb_value = {"state": onboarding.OWNER_CREATED, "company_id": company_id}
    if onb_row is None:
        db.add(AppConfig(key=onboarding.ONBOARDING_KEY, value=onb_value))
    else:
        onb_row.value = onb_value

    await db.flush()
    oid, oemail, oname, orole = str(owner.id), owner.email, owner.full_name, owner.role
    token = create_access_token(oid, oemail, orole, owner.token_version)
    # log_action commits the whole transaction (owner + company + onboarding + audit) and releases the lock.
    await log_action(db, user=owner, action="setup.bootstrap", entity_type="user", entity_id=oid, request=request)
    onboarding.invalidate_snapshot()
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": oid, "email": oemail, "full_name": oname, "role": orole, "is_active": True},
    }


async def _ensure_installation_identity(db: AsyncSession, client) -> tuple[str, str]:
    """PRODUCTION (http mode): return (installation_id, company_id) from the local installation record,
    activating with the central Control Plane first if this installation has not yet been activated.
    This is the smallest secure bootstrap: activation uses the installation's own key pair + the
    (short-lived, non-master) activation bootstrap credential - never a shared master key."""
    row = (await db.execute(select(AppConfig).where(AppConfig.key == "installation"))).scalar_one_or_none()
    val = row.value if (row and isinstance(row.value, dict)) else {}
    installation_id = val.get("installation_id")
    company_id = val.get("company_id")
    if not installation_id or not company_id:
        data = await client.activate(db)  # registers this installation's public key; stores CP-assigned ids
        installation_id, company_id = data["installation_id"], data["company_id"]
    return installation_id, company_id


@router.post("/checkout")
async def setup_checkout(user: User = Depends(require_roles("owner")), db: AsyncSession = Depends(get_db)):
    """Start the mandatory initial 5-seat ($245/mo) subscription checkout. The hosted checkout is
    created by the CENTRAL Control Plane (which owns the Stripe secret); this local backend only relays
    the request over an installation-authenticated HTTPS call and stores the returned hosted URL.
    Idempotent - returns the existing pending checkout if one is already open."""
    if await onboarding.get_state(db) == onboarding.ACTIVE:
        raise HTTPException(status_code=409, detail="RoofSpan Office is already activated.")

    rec = await onboarding.get_record(db)
    company_id = rec.get("company_id") or str(uuid.uuid4())

    # Idempotency: a repeated click / retry reuses the already-open pending checkout (never creates a
    # second subscription for the same company).
    if rec.get("state") == onboarding.PAYMENT_PENDING and rec.get("checkout_url"):
        return {
            "state": "payment_required",
            "checkout_url": rec["checkout_url"],
            "seats": INITIAL_SEATS,
            "monthly_price_usd": INITIAL_SEATS * SEAT_PRICE_USD,
        }

    client = lic_cp.get_client()
    try:
        if lic_config.LICENSING_MODE == "http":
            installation_id, company_id = await _ensure_installation_identity(db, client)
            data = await client.create_initial_checkout(
                db, company_id=company_id, installation_id=installation_id, seats=INITIAL_SEATS)
        else:
            # dev/mock: no external account, no Stripe secret.
            data = await client.create_initial_checkout(db, company_id=company_id, seats=INITIAL_SEATS)
        url = data["checkout_url"]
        if not url:
            raise ControlPlaneUnavailable("No checkout URL returned")
    except Exception:  # noqa: BLE001 - never leak provider/secret/exception text to the customer
        logger.exception("Initial subscription checkout failed (company_id=%s)", company_id)
        raise HTTPException(status_code=502,
                            detail="Unable to start subscription checkout. Please try again in a moment.")

    checkout_id = rec.get("checkout_id") or f"co_{uuid.uuid4().hex}"
    await onboarding.set_record(db, {
        **rec,
        "state": onboarding.PAYMENT_PENDING,
        "company_id": company_id,
        "checkout_id": checkout_id,
        "checkout_url": url,
        "paid": rec.get("paid", False),
    })
    return {
        "state": "payment_required",
        "checkout_url": url,
        "seats": INITIAL_SEATS,
        "monthly_price_usd": INITIAL_SEATS * SEAT_PRICE_USD,
    }


@router.get("/payment-status")
async def setup_payment_status(user: User = Depends(require_roles("owner")), db: AsyncSession = Depends(get_db)):
    """Poll payment/activation. Payment proof is AUTHORITATIVE from the central subscription state (via
    the signed entitlement refreshed from the Control Plane) - never inferred from a browser redirect.
    Onboarding flips to ACTIVE only when the effective licensing state is ACTIVE (or allowed GRACE)."""
    if await onboarding.get_state(db) == onboarding.ACTIVE:
        return {"state": "initialized"}

    rec = await onboarding.get_record(db)

    if lic_config.LICENSING_MODE == "dev":
        # DEV/MOCK: a confirmed simulated payment (via /dev/pay) finalizes with a real 5-seat entitlement.
        if not rec.get("paid"):
            return {"state": "payment_required", "checkout_url": rec.get("checkout_url"), "can_simulate": True}
        await lic_cp.set_dev_subscription(db, state="ACTIVE", seats=INITIAL_SEATS, license_id=rec.get("company_id"))
        await lic_service.refresh(db, force=True)
    else:
        # PRODUCTION: refresh the signed entitlement from the central Control Plane, which reflects the
        # Stripe-webhook-driven subscription state. A transient outage or not-yet-paid subscription simply
        # keeps us in payment_required.
        try:
            await lic_service.refresh(db, force=True)
        except ControlPlaneUnavailable:
            return {"state": "payment_required", "checkout_url": rec.get("checkout_url"), "can_simulate": False}
        except Exception:  # noqa: BLE001
            logger.exception("Entitlement refresh during payment-status failed")
            return {"state": "payment_required", "checkout_url": rec.get("checkout_url"), "can_simulate": False}

    eff = await lic_service.get_effective(db)
    if eff.effective_state in ("ACTIVE", "GRACE"):
        await onboarding.set_record(db, {**rec, "state": onboarding.ACTIVE})
        return {"state": "initialized"}
    return {"state": "payment_required", "checkout_url": rec.get("checkout_url"),
            "can_simulate": lic_config.LICENSING_MODE == "dev"}


@router.post("/dev/pay")
async def setup_dev_pay(user: User = Depends(require_roles("owner")), db: AsyncSession = Depends(get_db)):
    """DEV/MOCK only: simulate the customer completing the hosted checkout. Never available in
    production (LICENSING_MODE != dev)."""
    if lic_config.LICENSING_MODE != "dev":
        raise HTTPException(status_code=403, detail="Not available")
    rec = await onboarding.get_record(db)
    if rec.get("state") != onboarding.PAYMENT_PENDING:
        raise HTTPException(status_code=409, detail="No pending checkout to complete.")
    await onboarding.set_record(db, {**rec, "paid": True})
    return {"ok": True}
