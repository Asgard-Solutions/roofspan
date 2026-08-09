from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ActivateIn(BaseModel):
    company_name: str = ""
    requested_seats: int = 5
    installation_public_key: str
    software_version: str = "1.0.0"
    bootstrap_credential: str


class ActivateOut(BaseModel):
    installation_id: str
    company_id: str
    license_id: str
    entitlement_jws: str
    signing_public_keys: dict


class RefreshOut(BaseModel):
    entitlement_jws: str
    signing_public_keys: dict


class SigningKeysOut(BaseModel):
    keys: dict  # kid -> public PEM


class SetSubscriptionIn(BaseModel):
    state: str
    seats: int


class VersionPolicyOut(BaseModel):
    office_latest: str
    office_min_supported: str
    office_recommended: str
    mobile_latest: str
    mobile_min_supported: str
    mobile_recommended: str
    office_update_mandatory: bool
    mobile_update_mandatory: bool
    updated_at: Optional[datetime] = None


class VersionPolicyUpdateIn(BaseModel):
    office_latest: Optional[str] = None
    office_min_supported: Optional[str] = None
    office_recommended: Optional[str] = None
    mobile_latest: Optional[str] = None
    mobile_min_supported: Optional[str] = None
    mobile_recommended: Optional[str] = None
    office_update_mandatory: Optional[bool] = None
    mobile_update_mandatory: Optional[bool] = None
