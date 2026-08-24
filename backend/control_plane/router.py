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


def _require_admin(authorization: str | None = Header(default=None),
                   x_roofspan_admin: str | None = Header(default=None)):
    # Production: RoofSpan-internal operator JWT (Cognito). Dev: isolated X-RoofSpan-Admin header.
    if config.CP_ENV == "production":
        from control_plane import operator_auth
        return operator_auth.verify_operator(authorization)
    if x_roofspan_admin != config.DEV_ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Control Plane admin authentication required")
    return True


@router.get("/health")
async def cp_health():
    return {"status": "ok", "service": "roofspan-control-plane"}


@router.get("/ready")
async def cp_ready(db: AsyncSession = Depends(get_cp_db)):
    from sqlalchemy import text
    from control_plane import keys as cp_keys
    checks = {"db": False, "signing_key": False}
    try:
        await db.execute(text("SELECT 1"))
        checks["db"] = True
        keys = await cp_keys.public_keys(db)
        # KMS mode: readiness requires a configured key id + an ACTIVE published public key. We do NOT
        # perform a paid KMS Sign on every readiness probe (startup validate_active_key does the
        # GetPublicKey reconcile). Local mode: an ACTIVE public key must exist.
        if config.ENTITLEMENT_SIGNER == "kms":
            checks["signing_key"] = bool(keys) and bool(config.CP_KMS_SIGNING_KEY_ID)
        else:
            checks["signing_key"] = bool(keys)
    except Exception:  # noqa: BLE001
        pass
    ready = all(checks.values())
    if not ready:
        raise HTTPException(status_code=503, detail={"ready": False, "checks": checks,
                                                     "signer": config.ENTITLEMENT_SIGNER})
    return {"ready": True, "checks": checks, "signer": config.ENTITLEMENT_SIGNER}


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


@router.put("/subscriptions/{company_id}/seats")
async def set_seats(company_id: str, seats: int, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    try:
        return await service.set_subscription_seats(db, company_id=company_id, seats=seats)
    except service.CPError as e:
        raise _cp_error(e)


@router.post("/billing/sweep")
async def billing_sweep(_: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    return await service.sweep_billing(db)


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


# ---------------- Stripe billing engine (authoritative) ----------------

@router.post("/billing/stripe/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_cp_db)):
    body = await request.body()
    try:
        return await service.process_stripe_webhook(db, headers=dict(request.headers), body=body)
    except service.CPError as e:
        raise _cp_error(e)


@router.post("/billing/stripe/checkout")
async def stripe_checkout(company_id: str, payload: dict | None = None, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    payload = payload or {}
    try:
        return await service.stripe_create_checkout(db, company_id=company_id, seats=payload.get("seats"),
                                                    origin_url=payload.get("origin_url"))
    except service.CPError as e:
        raise _cp_error(e)


@router.put("/billing/stripe/seats")
async def stripe_seats(company_id: str, seats: int, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    try:
        return await service.stripe_update_seats(db, company_id=company_id, seats=seats)
    except service.CPError as e:
        raise _cp_error(e)


@router.post("/billing/stripe/cancel")
async def stripe_cancel(company_id: str, cancel: bool = True, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    try:
        return await service.stripe_set_cancel(db, company_id=company_id, cancel=cancel)
    except service.CPError as e:
        raise _cp_error(e)


@router.get("/billing/stripe/portal-url")
async def stripe_portal(company_id: str, return_url: str | None = None, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    try:
        return await service.stripe_portal(db, company_id=company_id, return_url=return_url)
    except service.CPError as e:
        raise _cp_error(e)


@router.post("/billing/stripe/reconcile")
async def stripe_reconcile(company_id: str, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    try:
        return await service.stripe_reconcile(db, company_id=company_id)
    except service.CPError as e:
        raise _cp_error(e)


# ---------------- pairing + version (Phase C3) ----------------

async def _authed_installation(request: Request, db: AsyncSession):
    body = await request.body()
    h = request.headers
    iid, ts, nonce, sig = (h.get(reqsig.H_INSTALLATION), h.get(reqsig.H_TIMESTAMP),
                           h.get(reqsig.H_NONCE), h.get(reqsig.H_SIGNATURE))
    if not all([iid, ts, nonce, sig]):
        raise HTTPException(status_code=401, detail="Missing installation authentication headers")
    try:
        inst = await service._verify_installation_request(db, installation_id=iid, timestamp=ts, nonce=nonce, body=body, signature_b64=sig)
    except service.CPError as e:
        raise _cp_error(e)
    return inst


@router.post("/pairing/create")
async def pairing_create(request: Request, db: AsyncSession = Depends(get_cp_db)):
    inst = await _authed_installation(request, db)
    # Optional user binding travels in the signed request body (never a credential).
    expected_user_id = expected_user_label = None
    try:
        raw = await request.body()
        if raw:
            import json as _json
            data = _json.loads(raw.decode() or "{}")
            expected_user_id = data.get("expected_user_id")
            expected_user_label = data.get("expected_user_label")
    except Exception:
        pass
    return await service.create_pairing(db, installation_id=str(inst.id),
                                        expected_user_id=expected_user_id, expected_user_label=expected_user_label)


@router.post("/pairing/resolve")
async def pairing_resolve(payload: dict, db: AsyncSession = Depends(get_cp_db)):
    try:
        return await service.resolve_pairing(db, token=payload.get("token"),
                                             numeric_code=payload.get("numeric_code"), label=payload.get("label"))
    except service.CPError as e:
        raise _cp_error(e)


@router.get("/pairing/devices")
async def pairing_devices(request: Request, db: AsyncSession = Depends(get_cp_db)):
    inst = await _authed_installation(request, db)
    return {"devices": await service.list_devices(db, installation_id=str(inst.id))}


@router.post("/pairing/devices/{device_id}/revoke")
async def pairing_revoke(device_id: str, _: bool = Depends(_require_admin), db: AsyncSession = Depends(get_cp_db)):
    try:
        await service.revoke_device(db, device_id=device_id)
        return {"ok": True, "device_id": device_id, "status": "REVOKED"}
    except service.CPError as e:
        raise _cp_error(e)


@router.post("/mobile/version-check")
async def mobile_version_check(payload: dict, db: AsyncSession = Depends(get_cp_db)):
    return await service.version_check(db, app_version=str(payload.get("app_version", "0")))
