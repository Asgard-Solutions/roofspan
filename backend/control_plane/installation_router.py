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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane import config, service
from control_plane.db import get_cp_db
from control_plane.models import Installation, License, MobileDevice, Subscription
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

    existing = (
        await db.execute(
            select(Installation)
            .where(Installation.public_key_pem == payload.installation_public_key)
            .order_by(Installation.created_at.asc())
        )
    ).scalars().first()

    if existing is None:
        try:
            result = await service.activate(
                db,
                company_name=payload.company_name,
                requested_seats=payload.requested_seats,
                public_key_pem=payload.installation_public_key,
                software_version=payload.software_version,
                bootstrap_credential=payload.bootstrap_credential,
            )
            return ActivateOut(**result)
        except service.CPError as exc:
            raise _cp_error(exc) from exc

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
