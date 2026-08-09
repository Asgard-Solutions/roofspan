"""Licensing / subscription API (Phase C0).

Read-only status + admin refresh + billing link stubs. Business-data enforcement lives in the
guard middleware; seat enforcement lives in the users router. These endpoints are always reachable
(even when SUSPENDED) so an Owner can view status and reach billing recovery.
"""
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User
from core import get_current_user, require_roles, log_action, SENSITIVE_ROLES
from licensing import config, service
from licensing.billing import get_billing_provider, BillingNotConfigured
from schemas_licensing import (
    SubscriptionStatusOut, LicenseStatusOut, BillingLinkOut, RefreshResultOut,
)

router = APIRouter(prefix="/api", tags=["licensing"])


@router.get("/subscription", response_model=SubscriptionStatusOut)
async def get_subscription(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    entitlement = await service.load_cached_entitlement(db)
    from licensing.state import evaluate
    status = evaluate(entitlement)
    active = await service.count_active_users(db)
    seats = entitlement.seats_licensed if entitlement else 0
    row = await service._get_cache_row(db)
    over_by = max(active - seats, 0)
    grace_day = None
    if entitlement and entitlement.grace_started_at and status.effective_state == "GRACE":
        from datetime import datetime, timezone
        grace_day = (datetime.now(timezone.utc) - entitlement.grace_started_at).days + 1
    return SubscriptionStatusOut(
        state=status.effective_state,
        reported_state=status.reported_state,
        business_access=status.business_access,
        seats_licensed=seats,
        active_users=active,
        available_seats=max(seats - active, 0),
        min_seats=config.MIN_SEATS,
        max_seats=config.MAX_SEATS,
        product=entitlement.product if entitlement else config.PRODUCT,
        online=bool(row and row.last_check_ok),
        within_offline_grace=status.within_offline_grace,
        last_verified=row.fetched_at if row else None,
        next_refresh_at=entitlement.refresh_at if entitlement else None,
        grace_until=status.grace_until,
        seat_action_required=over_by > 0,
        active_over_by=over_by,
        cancel_at_period_end=entitlement.cancel_at_period_end if entitlement else False,
        current_period_end=entitlement.current_period_end if entitlement else None,
        scheduled_seats=entitlement.scheduled_seats if entitlement else None,
        scheduled_seats_at=entitlement.scheduled_seats_at if entitlement else None,
        grace_started_at=entitlement.grace_started_at if entitlement else None,
        grace_day=grace_day,
    )


@router.get("/license/status", response_model=LicenseStatusOut)
async def license_status(user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    installation_id, company_id = await service.get_installation(db)
    entitlement = await service.load_cached_entitlement(db)
    status = await service.get_effective(db)
    active = await service.count_active_users(db)
    row = await service._get_cache_row(db)
    return LicenseStatusOut(
        installation_id=installation_id,
        company_id=company_id,
        license_id=(entitlement.license_id if entitlement else (row.license_id if row else None)),
        kid=entitlement.kid if entitlement else (row.kid if row else None),
        reported_state=status.reported_state,
        effective_state=status.effective_state,
        seats_licensed=entitlement.seats_licensed if entitlement else 0,
        active_users=active,
        product=entitlement.product if entitlement else config.PRODUCT,
        min_supported_version=entitlement.min_supported_version if entitlement else None,
        issued_at=entitlement.issued_at if entitlement else None,
        refresh_at=entitlement.refresh_at if entitlement else None,
        grace_until=entitlement.grace_until if entitlement else (row.grace_until if row else None),
        fetched_at=row.fetched_at if row else None,
        last_check_at=row.last_check_at if row else None,
        last_check_ok=bool(row and row.last_check_ok),
        last_error=row.last_error if row else None,
        verified=entitlement is not None,
        mode=config.LICENSING_MODE,
    )


@router.post("/subscription/refresh", response_model=RefreshResultOut)
async def refresh_subscription(request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    result = await service.refresh(db, force=True)
    await log_action(db, user=user, action="subscription.refresh", entity_type="license", detail=result, request=request)
    return RefreshResultOut(ok=result.get("ok", False), offline=result.get("offline", False),
                            state=result.get("state"), error=result.get("error"))


@router.get("/billing/portal-url", response_model=BillingLinkOut)
async def billing_portal(user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    from control_plane import billing as cp_billing, config as cp_config
    _, company_id = await service.get_installation(db)
    if cp_config.BILLING_MODE == "stripe":
        from control_plane.db import SessionLocal as CPSession
        from control_plane import service as cp_service
        try:
            async with CPSession() as cpdb:
                r = await cp_service.stripe_portal(cpdb, company_id=company_id, return_url=cp_config.APP_BASE_URL)
            return BillingLinkOut(configured=True, provider="stripe", url=r["url"], message="ok")
        except cp_service.CPError as e:
            return BillingLinkOut(configured=False, provider="stripe", url=None, message=e.detail)
    provider = cp_billing.get_provider()
    if provider.name == "stub":
        return BillingLinkOut(configured=False, provider=None, url=None, message="Billing provider not configured")
    try:
        url = await provider.portal_url(company_id)
        return BillingLinkOut(configured=True, provider=provider.name, url=url, message="ok")
    except cp_billing.BillingAuthError as e:
        return BillingLinkOut(configured=False, provider=provider.name, url=None, message=str(e))


@router.post("/billing/checkout", response_model=BillingLinkOut)
async def billing_checkout(request: Request, user: User = Depends(require_roles("owner")), db: AsyncSession = Depends(get_db)):
    from control_plane import billing as cp_billing, config as cp_config
    _, company_id = await service.get_installation(db)
    if cp_config.BILLING_MODE == "stripe":
        from control_plane.db import SessionLocal as CPSession
        from control_plane import service as cp_service
        origin = None
        try:
            origin = str(request.headers.get("origin") or "") or None
        except Exception:
            origin = None
        try:
            async with CPSession() as cpdb:
                r = await cp_service.stripe_create_checkout(cpdb, company_id=company_id, seats=None, origin_url=origin)
            return BillingLinkOut(configured=True, provider="stripe", url=r["url"], message="ok")
        except cp_service.CPError as e:
            return BillingLinkOut(configured=False, provider="stripe", url=None, message=e.detail)
    provider = cp_billing.get_provider()
    if provider.name == "stub":
        return BillingLinkOut(configured=False, provider=None, url=None, message="Billing provider not configured")
    try:
        url = provider.checkout_url(company_id)
        return BillingLinkOut(configured=True, provider=provider.name, url=url, message="ok")
    except cp_billing.BillingAuthError as e:
        return BillingLinkOut(configured=False, provider=provider.name, url=None, message=str(e))


@router.post("/billing/add-seats", response_model=BillingLinkOut)
async def billing_add_seats(request: Request, delta: int, user: User = Depends(require_roles("owner")),
                            db: AsyncSession = Depends(get_db)):
    """Add or remove seats by a delta (+1/+5/+10, or negative to schedule a reduction). Same Stripe
    subscription item quantity. Increases are immediate (prorated); decreases schedule at renewal."""
    from control_plane import config as cp_config
    if cp_config.BILLING_MODE != "stripe":
        raise HTTPException(status_code=400, detail="Stripe billing is not enabled (BILLING_MODE != stripe)")
    from control_plane.db import SessionLocal as CPSession
    from control_plane import service as cp_service
    _, company_id = await service.get_installation(db)
    async with CPSession() as cpdb:
        sub = await cp_service._get_sub(cpdb, company_id)
        target = sub.seats + int(delta)
        try:
            result = await cp_service.stripe_update_seats(cpdb, company_id=company_id, seats=target)
        except cp_service.CPError as e:
            raise HTTPException(status_code=e.status, detail=e.detail)
    await log_action(db, user=user, action="billing.add_seats", entity_type="license",
                     detail={"delta": delta, **result}, request=request)
    return BillingLinkOut(configured=True, provider="stripe", url=None, message=str(result))


@router.post("/billing/cancel", response_model=BillingLinkOut)
async def billing_cancel(request: Request, reactivate: bool = False, user: User = Depends(require_roles("owner")),
                         db: AsyncSession = Depends(get_db)):
    """Schedule cancellation at period end (or reverse it). Access continues through the paid term."""
    from control_plane import config as cp_config
    if cp_config.BILLING_MODE != "stripe":
        raise HTTPException(status_code=400, detail="Stripe billing is not enabled (BILLING_MODE != stripe)")
    from control_plane.db import SessionLocal as CPSession
    from control_plane import service as cp_service
    _, company_id = await service.get_installation(db)
    async with CPSession() as cpdb:
        try:
            result = await cp_service.stripe_set_cancel(cpdb, company_id=company_id, cancel=not reactivate)
        except cp_service.CPError as e:
            raise HTTPException(status_code=e.status, detail=e.detail)
    await log_action(db, user=user, action="billing.cancel", entity_type="license",
                     detail={"reactivate": reactivate, **result}, request=request)
    return BillingLinkOut(configured=True, provider="stripe", url=None, message=str(result))


@router.post("/admin/mobile/pair")
async def mobile_pair(user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    from licensing import pairing_client
    try:
        return await pairing_client.create_pairing(db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach RoofSpan Control Plane to pair device: {str(e)[:200]}")


@router.get("/admin/mobile/devices")
async def mobile_devices(user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    from licensing import pairing_client
    try:
        return await pairing_client.list_devices(db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach RoofSpan Control Plane: {str(e)[:200]}")


@router.post("/admin/mobile/devices/{device_id}/revoke")
async def mobile_revoke(device_id: str, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    from licensing import pairing_client
    try:
        return await pairing_client.revoke_device(db, device_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach RoofSpan Control Plane: {str(e)[:200]}")
