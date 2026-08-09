"""Licensing / subscription API (Phase C0).

Read-only status + admin refresh + billing link stubs. Business-data enforcement lives in the
guard middleware; seat enforcement lives in the users router. These endpoints are always reachable
(even when SUSPENDED) so an Owner can view status and reach billing recovery.
"""
from fastapi import APIRouter, Depends, Request
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
    from control_plane import billing as cp_billing
    _, company_id = await service.get_installation(db)
    provider = cp_billing.get_provider()
    if provider.name == "stub":
        return BillingLinkOut(configured=False, provider=None, url=None, message="Billing provider not configured")
    try:
        url = await provider.portal_url(company_id)
        return BillingLinkOut(configured=True, provider=provider.name, url=url, message="ok")
    except cp_billing.BillingAuthError as e:
        return BillingLinkOut(configured=False, provider=provider.name, url=None, message=str(e))


@router.post("/billing/checkout", response_model=BillingLinkOut)
async def billing_checkout(user: User = Depends(require_roles("owner")), db: AsyncSession = Depends(get_db)):
    from control_plane import billing as cp_billing
    _, company_id = await service.get_installation(db)
    provider = cp_billing.get_provider()
    if provider.name == "stub":
        return BillingLinkOut(configured=False, provider=None, url=None, message="Billing provider not configured")
    try:
        url = provider.checkout_url(company_id)
        return BillingLinkOut(configured=True, provider=provider.name, url=url, message="ok")
    except cp_billing.BillingAuthError as e:
        return BillingLinkOut(configured=False, provider=provider.name, url=None, message=str(e))
