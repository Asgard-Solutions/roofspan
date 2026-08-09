from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SubscriptionStatusOut(BaseModel):
    """Practical subscription status for Administration → Subscription."""
    state: str                    # effective state enforced now
    reported_state: str           # state the Control Plane last asserted
    business_access: bool
    seats_licensed: int
    active_users: int
    available_seats: int
    min_seats: int
    max_seats: int
    product: str
    online: bool                  # last Control Plane check succeeded
    within_offline_grace: bool
    last_verified: Optional[datetime] = None
    next_refresh_at: Optional[datetime] = None
    grace_until: Optional[datetime] = None


class LicenseStatusOut(BaseModel):
    """Detailed license/entitlement status (sensitive roles)."""
    installation_id: str
    company_id: str
    license_id: Optional[str] = None
    kid: Optional[str] = None
    reported_state: str
    effective_state: str
    seats_licensed: int
    active_users: int
    product: str
    min_supported_version: Optional[str] = None
    issued_at: Optional[datetime] = None
    refresh_at: Optional[datetime] = None
    grace_until: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    last_check_at: Optional[datetime] = None
    last_check_ok: bool = False
    last_error: Optional[str] = None
    verified: bool = False
    mode: str


class BillingLinkOut(BaseModel):
    configured: bool
    provider: Optional[str] = None
    url: Optional[str] = None
    message: str


class RefreshResultOut(BaseModel):
    ok: bool
    offline: bool
    state: Optional[str] = None
    error: Optional[str] = None


class DevSetStateIn(BaseModel):
    state: str                    # ACTIVE | GRACE | SUSPENDED | CANCELLED
    seats_licensed: Optional[int] = None
    license_id: Optional[str] = None
