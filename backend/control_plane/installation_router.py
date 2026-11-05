"""Installation-owned Control Plane endpoints used by RoofSpan Office.

These routes are deliberately separate from operator/admin routes:

* ``/installation/register`` is an idempotent activation/recovery endpoint keyed by the
  installation public key. It prevents duplicate hosted registrations when an Office request is
  retried or when an older Office build previously registered against its local embedded Control
  Plane.
* ``/installation/status`` lets Office prove that a stored Control Plane installation id belongs to
  the currently configured hosted Control Plane before it creates or lists pairing records.
* ``/pairing/devices/{id}/revoke-self`` allows an installation to revoke only one of its own devices
  with the same Ed25519 request-signing contract used by create/list. No operator secret is shipped
  in RoofSpan Office.

No customer roofing/business data is stored or returned here.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from control_plane import recovery
from control_plane.schemas import RecoverIn
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane import config, service
from control_plane.db import get_cp_db
from control_plane.models import Company, Installation, License, MobileDevice, Subscription
from control_plane.schemas import ActivateIn, ActivateOut
from licensing import reqsig

router = APIRouter(prefix="/api/control-plane", tags=["control-plane-installation"])


def _cp_error(exc: service.CPError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail)


def _activation_lock_key(public_key_pem: str) -> int:
    """Stable signed 64-bit advisory-lock key for one installation public key."""
    digest = hashlib.sha256(public_key_pem.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


async def _authed_installation(request: Request, db: AsyncSession) -> Installation:
    body = await request.body()
    headers = request.headers
    installation_id = headers.get(reqsig.H_INSTALLATION)
    timestamp = headers.get(reqsig.H_TIMESTAMP)
    nonce = headers.get(reqsig.H_NONCE)
    signature = headers.get(reqsig.H_SIGNATURE)
    if not all([installation_id, timestamp, nonce, signature]):
        raise HTTPException(status_code=401, detail="Missing installation authentication headers")
    try:
        return await service._verify_installation_request(
            db,
            installation_id=installation_id,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
            signature_b64=signature,
        )
    except service.CPError as exc:
        raise _cp_error(exc) from exc


def _company_exists() -> HTTPException:
    return HTTPException(status_code=409, detail={
        "code": "company_exists",
        "message": "This company is already registered with RoofSpan. Use 'Restore my company' "
                   "and enter your company recovery code.",
    })


async def _installation_for_key(db: AsyncSession, public_key_pem: str):
    """The identity's installation: the ACTIVE row if any (there is at most one), else the newest."""
    return (
        await db.execute(
            select(Installation)
            .where(Installation.public_key_pem == public_key_pem)
            .order_by((Installation.status == "ACTIVE").desc(), Installation.created_at.desc())
        )
    ).scalars().first()


@router.post("/installation/register", response_model=ActivateOut)
async def register_installation(
    payload: ActivateIn,
    db: AsyncSession = Depends(get_cp_db),
):
    """Register or recover an installation without creating duplicates on retries.

    The existing activation credential contract is preserved. The public key is the durable
    installation identity; its private key never leaves the Office computer.
    """
    if payload.bootstrap_credential != config.DEV_BOOTSTRAP_SECRET:
        raise HTTPException(status_code=401, detail="Invalid activation credential")

    # Serialize duplicate/retry activation attempts for the same public key. This is a transaction
    # advisory lock, so the runtime role needs no elevated PostgreSQL privileges.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _activation_lock_key(payload.installation_public_key)},
    )

    existing = await _installation_for_key(db, payload.installation_public_key)

    if existing is None:
        mk = recovery.match_key(payload.company_name, payload.company_phone, payload.company_address)
        if mk:  # different PCs registering the same company at once wait here, then see each other
            await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _activation_lock_key("company:" + mk)})
        if mk and (await db.execute(
                select(Company.id).where(Company.match_key == mk, Company.status == "ACTIVE").limit(1)
        )).first():
            raise _company_exists()
        try:
            result = await service.activate(
                db,
                company_name=payload.company_name,
                company_phone=payload.company_phone,
                company_address=payload.company_address,
                requested_seats=payload.requested_seats,
                public_key_pem=payload.installation_public_key,
                software_version=payload.software_version,
                bootstrap_credential=payload.bootstrap_credential,
            )
            return ActivateOut(**result)
        except service.CPError as exc:
            raise _cp_error(exc) from exc
        except IntegrityError as exc:  # the DB rule (uq_companies_active_match_key) is the last line of defence
            await db.rollback()
            raise _company_exists() from exc

    if existing.status != "ACTIVE":
        raise HTTPException(status_code=403, detail="Installation identity is revoked")

    license_row = (
        await db.execute(
            select(License)
            .where(License.installation_id == existing.id)
            .order_by(License.created_at.asc())
        )
    ).scalars().first()
    if license_row is not None and license_row.status != "ACTIVE":
        raise HTTPException(status_code=403, detail="Installation license is inactive")

    seats = max(config.MIN_SEATS, min(config.MAX_SEATS, int(payload.requested_seats)))
    if license_row is None:
        license_row = License(
            company_id=existing.company_id,
            installation_id=existing.id,
            product=config.PRODUCT,
            status="ACTIVE",
        )
        db.add(license_row)
        await db.flush()

    subscription = (
        await db.execute(
            select(Subscription).where(Subscription.company_id == existing.company_id)
        )
    ).scalar_one_or_none()
    if subscription is None:
        subscription = Subscription(
            company_id=existing.company_id,
            license_id=license_row.id,
            state="ACTIVE",
            seats=seats,
            current_period_end=datetime.now(timezone.utc)
            + timedelta(days=config.BILLING_PERIOD_DAYS),
        )
        db.add(subscription)
    elif subscription.license_id is None:
        subscription.license_id = license_row.id

    existing.software_version = payload.software_version
    existing.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(existing)
    await db.refresh(license_row)
    await db.refresh(subscription)

    entitlement = await service._issue_entitlement(
        db,
        installation=existing,
        license_row=license_row,
        subscription=subscription,
        reason="activation",
    )
    await service.audit(
        db,
        actor=str(existing.id),
        action="installation.register.reuse",
        entity_type="installation",
        entity_id=str(existing.id),
        detail={"software_version": payload.software_version},
    )
    from control_plane import keys as cp_keys

    return ActivateOut(
        installation_id=str(existing.id),
        company_id=str(existing.company_id),
        license_id=str(license_row.id),
        entitlement_jws=entitlement,
        signing_public_keys=await cp_keys.public_keys(db),
    )


@router.post("/installation/status")
async def installation_status(
    request: Request,
    db: AsyncSession = Depends(get_cp_db),
):
    """Verify a stored installation id/public-key pair against this Control Plane."""
    installation = await _authed_installation(request, db)
    return {
        "installation_id": str(installation.id),
        "company_id": str(installation.company_id),
        "status": installation.status,
        "software_version": installation.software_version,
    }


@router.post("/pairing/devices/{device_id}/revoke-self")
async def revoke_own_device(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_cp_db),
):
    """Revoke a device only when the signed installation owns it."""
    installation = await _authed_installation(request, db)
    try:
        device_uuid = uuid.UUID(device_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Unknown device")

    device = (
        await db.execute(select(MobileDevice).where(MobileDevice.id == device_uuid))
    ).scalar_one_or_none()
    if device is None or device.installation_id != installation.id:
        # Do not disclose whether another installation owns the id.
        raise HTTPException(status_code=404, detail="Unknown device")

    if device.status != "REVOKED":
        device.status = "REVOKED"
        device.revoked_at = datetime.now(timezone.utc)
        await db.commit()
        await service.audit(
            db,
            actor=str(installation.id),
            action="mobile_device.revoke",
            entity_type="mobile_device",
            entity_id=str(device.id),
        )

    return {"ok": True, "device_id": str(device.id), "status": "REVOKED"}


class CompanyNameIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=500)


@router.post("/installation/company")
async def installation_company_name(
    payload: CompanyNameIn,
    request: Request,
    db: AsyncSession = Depends(get_cp_db),
):
    """Signed Office installation sets ITS company's name, exactly as entered in Office setup/Settings."""
    installation = await _authed_installation(request, db)
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="Company name must not be blank")
    company = await db.get(Company, installation.company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    new = {"name": payload.name,
           "phone": company.phone if payload.phone is None else payload.phone,
           "address": company.address if payload.address is None else payload.address}
    old = {"name": company.name, "phone": company.phone, "address": company.address}
    if new != old:
        company.name, company.phone, company.address = new["name"], new["phone"], new["address"]
        mk = recovery.match_key(*new.values())
        clash = mk and (await db.execute(select(Company.id).where(
            Company.match_key == mk, Company.status == "ACTIVE", Company.id != company.id).limit(1))).first()
        company.match_key = None if clash else mk  # never let an edit collide with another company
        await db.commit()
        await service.audit(db, actor="installation", action="company.update", entity_type="company",
                            entity_id=str(company.id), detail={"from": old, "to": new, "match_conflict": bool(clash)})
    return {"company_id": str(company.id), **new}


@router.post("/installation/recovery-code")
async def installation_recovery_code(request: Request, db: AsyncSession = Depends(get_cp_db)):
    """The signed Office reads its company's recovery code (owner Settings / end of setup)."""
    installation = await _authed_installation(request, db)
    company = await db.get(Company, installation.company_id)
    code = recovery.reveal_code(company)
    if code is None:  # companies created before recovery codes existed
        code = recovery.assign_code(company)
        await db.commit()
        await service.audit(db, actor="installation", action="company.recovery_code.create",
                            entity_type="company", entity_id=str(company.id))
    return {"company_id": str(company.id), "recovery_code": code}


class PrecheckIn(BaseModel):
    company_name: str = Field(default="", max_length=255)
    company_phone: str = Field(default="", max_length=64)
    company_address: str = Field(default="", max_length=500)
    bootstrap_credential: str


@router.post("/installation/precheck")
async def precheck_company(payload: PrecheckIn, db: AsyncSession = Depends(get_cp_db)):
    """Before first-run setup creates anything: is this (name + phone + address) company already registered?"""
    if payload.bootstrap_credential != config.DEV_BOOTSTRAP_SECRET:
        raise HTTPException(status_code=401, detail="Invalid activation credential")
    mk = recovery.match_key(payload.company_name, payload.company_phone, payload.company_address)
    exists = bool(mk) and (await db.execute(
        select(Company.id).where(Company.match_key == mk, Company.status == "ACTIVE").limit(1))).first() is not None
    return {"exists": exists}


_RECOVER_FAILURES: dict[str, list[float]] = {}
_RECOVER_MAX_FAILURES, _RECOVER_WINDOW = 10, 900.0


def _recover_throttle(client: str, failed: bool = False) -> None:
    import time as _t
    now = _t.monotonic()
    hits = [t for t in _RECOVER_FAILURES.get(client, []) if now - t < _RECOVER_WINDOW]
    if failed:
        hits.append(now)
    _RECOVER_FAILURES[client] = hits
    if not failed and len(hits) >= _RECOVER_MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Too many incorrect recovery codes. Try again in 15 minutes.")


@router.post("/installation/recover", response_model=ActivateOut)
async def recover_installation(payload: RecoverIn, request: Request, db: AsyncSession = Depends(get_cp_db)):
    """New/reinstalled PC + company recovery code -> same company. Older PCs of that company are disconnected."""
    if payload.bootstrap_credential != config.DEV_BOOTSTRAP_SECRET:
        raise HTTPException(status_code=401, detail="Invalid activation credential")
    client = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
    _recover_throttle(client)
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                     {"k": _activation_lock_key(payload.installation_public_key)})
    company = (await db.execute(select(Company).where(
        Company.recovery_code_hash == recovery.code_hash(payload.recovery_code), Company.status == "ACTIVE"
    ))).scalar_one_or_none()
    if company is None:
        _recover_throttle(client, failed=True)
        await service.audit(db, actor="anonymous", action="company.recover.failed", entity_type="company",
                            entity_id=None, detail={"client": client})
        raise HTTPException(status_code=404, detail="Recovery code not recognised")
    latest = (await db.execute(select(Installation).where(Installation.company_id == company.id)
                               .order_by(Installation.created_at.desc()))).scalars().first()
    if latest is not None and latest.status == "REVOKED":
        raise HTTPException(status_code=403, detail="This company was disconnected by RoofSpan. Contact RoofSpan support.")
    existing = await _installation_for_key(db, payload.installation_public_key)
    if existing is not None and existing.status == "ACTIVE" and existing.company_id != company.id:
        raise HTTPException(status_code=409, detail="This computer is already connected to a different company")
    if existing is None or existing.status != "ACTIVE":
        replaced = (await db.execute(select(Installation).where(
            Installation.company_id == company.id, Installation.status == "ACTIVE"))).scalars().all()
        for old in replaced:
            old.status = "REPLACED"
        existing = Installation(company_id=company.id, public_key_pem=payload.installation_public_key,
                                software_version=payload.software_version, status="ACTIVE")
        db.add(existing)
        await db.flush()
    license_row = (await db.execute(select(License).where(License.company_id == company.id)
                                    .order_by(License.created_at.asc()))).scalars().first()
    if license_row is not None and license_row.status != "ACTIVE":
        await db.rollback()
        raise HTTPException(status_code=403, detail="This company's license is inactive. Contact RoofSpan support.")
    if license_row is None:
        license_row = License(company_id=company.id, installation_id=existing.id, product=config.PRODUCT)
        db.add(license_row)
    else:
        license_row.installation_id = existing.id
    await db.flush()
    subscription = (await db.execute(select(Subscription).where(Subscription.company_id == company.id))).scalar_one_or_none()
    if subscription is None:
        subscription = Subscription(company_id=company.id, license_id=license_row.id, state="ACTIVE",
                                    seats=config.MIN_SEATS, current_period_end=datetime.now(timezone.utc)
                                    + timedelta(days=config.BILLING_PERIOD_DAYS))
        db.add(subscription)
    else:
        subscription.license_id = license_row.id
    existing.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    entitlement = await service._issue_entitlement(db, installation=existing, license_row=license_row,
                                                   subscription=subscription, reason="recovery")
    await service.audit(db, actor=str(existing.id), action="company.recover", entity_type="company",
                        entity_id=str(company.id), detail={"installation_id": str(existing.id)})
    from control_plane import keys as cp_keys
    return ActivateOut(installation_id=str(existing.id), company_id=str(company.id), license_id=str(license_row.id),
                       entitlement_jws=entitlement, signing_public_keys=await cp_keys.public_keys(db),
                       company_name=company.name, company_phone=company.phone, company_address=company.address)


@router.post("/installation/billing/session")
async def installation_billing_session(
    request: Request,
    db: AsyncSession = Depends(get_cp_db),
):
    """Signed Office installation -> Stripe customer portal (or Checkout when it has never subscribed)."""
    installation = await _authed_installation(request, db)
    try:
        return await service.installation_billing_session(
            db, company_id=str(installation.company_id), public_origin=_public_origin(request))
    except service.CPError as exc:
        raise _cp_error(exc) from exc


def _public_origin(request: Request) -> str:
    """Origin the caller used to reach this Control Plane (behind the ingress: X-Forwarded-Proto/Host)."""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    return f"{proto}://{host}"


_RETURN_MESSAGES = {
    "success": ("Subscription started", "Thanks! Your RoofSpan subscription is active."),
    "cancel": ("Checkout cancelled", "No charge was made."),
    "portal": ("Billing updated", "Your billing changes have been saved."),
}


@router.get("/billing/return", response_class=HTMLResponse)
@router.get("/billing/return/", response_class=HTMLResponse, include_in_schema=False)  # no http:// slash-redirect
async def billing_return(result: str = "portal"):
    """Static landing page after Stripe; the result is looked up, never echoed."""
    title, msg = _RETURN_MESSAGES.get(result, _RETURN_MESSAGES["portal"])
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><title>RoofSpan billing</title>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'></head>"
        "<body style='font-family:system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 1.5rem;color:#0f172a'>"
        f"<h1 data-testid='billing-return-title' style='font-size:1.5rem'>{title}</h1>"
        f"<p data-testid='billing-return-message'>{msg}</p>"
        "<p>You can close this tab and return to RoofSpan Office. Your subscription status updates there "
        "automatically, or select <b>Refresh</b> on the Subscription page.</p></body></html>")
