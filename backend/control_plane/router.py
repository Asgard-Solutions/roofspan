"""Control Plane API router (mounted at /api/control-plane).

Public: activation (bootstrap-credential-gated) and installation-authenticated entitlement refresh.
Admin/dev: revoke, key rotation, subscription updates, version-policy writes — guarded by the DEV
admin secret in C1 (production uses proper operator auth — HUMAN REQUIRED).

NOTE: these endpoints are NOT gated by the customer SubscriptionGuardMiddleware allowlist concern —
they are the Control Plane itself. The guard only protects business routes on the installation.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane import config, service
from control_plane.db import get_cp_db
from licensing import reqsig
from control_plane.schemas import (
    ActivateIn, ActivateOut, RefreshOut, SigningKeysOut, SetSubscriptionIn,
    VersionPolicyOut, VersionPolicyUpdateIn,
)

router = APIRouter(prefix="/api/control-plane", tags=["control-plane"])


def _cp_error(e: service.CPError):
    return HTTPException(status_code=e.status, detail=e.detail)


def _require_admin(x_roofspan_admin: str | None = Header(default=None)):
    if x_roofspan_admin != config.DEV_ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Control Plane admin authentication required")
    return True


@router.get("/health")
async def cp_health():
    return {"status": "ok", "service": "roofspan-control-plane"}


@router.post("/activate", response_model=ActivateOut)
async def activate(payload: ActivateIn, db: AsyncSession = Depends(get_cp_db)):
    try:
        result = await service.activate(
            db, company_name=payload.company_name, requested_seats=payload.requested_seats,
            public_key_pem=payload.installation_public_key, software_version=payload.software_version,
            bootstrap_credential=payload.bootstrap_credential,
        )
        return ActivateOut(**result)
    except service.CPError as e:
        raise _cp_error(e)


@router.post("/entitlement/refresh", response_model=RefreshOut)
async def refresh(request: Request, db: AsyncSession = Depends(get_cp_db)):
    body = await request.body()
    h = request.headers
    installation_id = h.get(reqsig.H_INSTALLATION)
    timestamp = h.get(reqsig.H_TIMESTAMP)
    nonce = h.get(reqsig.H_NONCE)
    signature = h.get(reqsig.H_SIGNATURE)
    if not all([installation_id, timestamp, nonce, signature]):
        raise HTTPException(status_code=401, detail="Missing installation authentication headers")
    try:
        result = await service.refresh_entitlement(
            db, installation_id=installation_id, timestamp=timestamp, nonce=nonce,
            body=body, signature_b64=signature,
        )
        return RefreshOut(**result)
    except service.CPError as e:
        raise _cp_error(e)


@router.get("/signing-keys/public", response_model=SigningKeysOut)
async def signing_keys_public(db: AsyncSession = Depends(get_cp_db)):
    from control_plane import keys as cp_keys
    return SigningKeysOut(keys=await cp_keys.public_keys(db))


@router.get("/version-policy", response_model=VersionPolicyOut)
async def version_policy(db: AsyncSession = Depends(get_cp_db)):
    vp = await service.get_version_policy(db)
    return VersionPolicyOut(
        office_latest=vp.office_latest, office_min_supported=vp.office_min_supported,
        office_recommended=vp.office_recommended, mobile_latest=vp.mobile_latest,
        mobile_min_supported=vp.mobile_min_supported, mobile_recommended=vp.mobile_recommended,
        office_update_mandatory=vp.office_update_mandatory, mobile_update_mandatory=vp.mobile_update_mandatory,
        updated_at=vp.updated_at,
    )


# ---------------- admin/dev ----------------

@router.post("/installations/{installation_id}/revoke")
async def revoke(installation_id: str, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    try:
        await service.revoke_installation(db, installation_id=installation_id)
        return {"ok": True, "installation_id": installation_id, "status": "REVOKED"}
    except service.CPError as e:
        raise _cp_error(e)


@router.post("/signing-keys/rotate")
async def rotate(_: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    kid = await service.rotate_signing_key(db)
    return {"ok": True, "active_kid": kid}


@router.put("/subscriptions/{company_id}")
async def set_subscription(company_id: str, payload: SetSubscriptionIn, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    try:
        sub = await service.set_subscription(db, company_id=company_id, state=payload.state, seats=payload.seats)
        return {"ok": True, "company_id": company_id, "state": sub.state, "seats": sub.seats}
    except service.CPError as e:
        raise _cp_error(e)


@router.put("/version-policy", response_model=VersionPolicyOut)
async def update_version_policy(payload: VersionPolicyUpdateIn, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    vp = await service.update_version_policy(db, payload.model_dump())
    return VersionPolicyOut(
        office_latest=vp.office_latest, office_min_supported=vp.office_min_supported,
        office_recommended=vp.office_recommended, mobile_latest=vp.mobile_latest,
        mobile_min_supported=vp.mobile_min_supported, mobile_recommended=vp.mobile_recommended,
        office_update_mandatory=vp.office_update_mandatory, mobile_update_mandatory=vp.mobile_update_mandatory,
        updated_at=vp.updated_at,
    )


# ---------------- billing (Phase C2) ----------------

@router.post("/billing/webhook")
async def billing_webhook(request: Request, db: AsyncSession = Depends(get_cp_db)):
    body = await request.body()
    try:
        return await service.process_webhook(db, headers=dict(request.headers), body=body)
    except service.CPError as e:
        raise _cp_error(e)


@router.post("/billing/reconcile")
async def billing_reconcile(company_id: str, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    try:
        return await service.reconcile_subscription(db, company_id=company_id)
    except service.CPError as e:
        raise _cp_error(e)


@router.post("/billing/checkout")
async def billing_checkout(company_id: str, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    try:
        return {"url": await service.checkout_url(company_id), "company_id": company_id}
    except service.CPError as e:
        raise _cp_error(e)


@router.get("/billing/portal-url")
async def billing_portal(company_id: str, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    try:
        return {"url": await service.portal_url(company_id), "company_id": company_id}
    except service.CPError as e:
        raise _cp_error(e)
