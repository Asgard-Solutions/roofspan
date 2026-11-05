from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ActivateIn(BaseModel):
    company_name: str = ""
    company_phone: str = Field(default="", max_length=64)
    company_address: str = Field(default="", max_length=500)
    requested_seats: int = 5
    installation_public_key: str
    software_version: str = "1.0.0"
    bootstrap_credential: str


class RecoverIn(BaseModel):
    recovery_code: str = Field(min_length=8, max_length=64)
    installation_public_key: str
    software_version: str = "1.0.0"
    bootstrap_credential: str


class ActivateOut(BaseModel):
    installation_id: str
    company_id: str
    license_id: str
    entitlement_jws: str
    signing_public_keys: dict
    recovery_code: str | None = None  # only when the company was just created
    company_name: str | None = None
    company_phone: str | None = None
    company_address: str | None = None


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
