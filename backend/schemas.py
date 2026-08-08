from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, EmailStr, Field, ConfigDict

from core import ROLES


# ---- Auth ----
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: EmailStr
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---- Users ----
class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = ""
    password: str = Field(min_length=8)
    role: str = "sales"


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8)


# ---- Integrations ----
class IntegrationOut(BaseModel):
    provider: str
    enabled: bool
    has_secret: bool
    secret_masked: Optional[str] = None
    config: dict = {}
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None


class IntegrationUpdate(BaseModel):
    enabled: Optional[bool] = None
    config: Optional[dict] = None


class SecretUpdate(BaseModel):
    secret: str = Field(min_length=1)


class TestConnectionResult(BaseModel):
    ok: bool
    message: str


# ---- Map config / company ----
class MapConfigOut(BaseModel):
    base_provider: str
    base_style_url: str
    osm_tile_url: str
    attribution: str
    satellite_enabled: bool
    maptiler_configured: bool
    default_center: list[float]
    default_zoom: float


class MapConfigUpdate(BaseModel):
    satellite_enabled: Optional[bool] = None
    default_center: Optional[list[float]] = None
    default_zoom: Optional[float] = None


class CompanyProfile(BaseModel):
    name: str = "RoofSpan Roofing Co."
    phone: str = ""
    email: str = ""
    address: str = ""
    license_number: str = ""


class AuditOut(BaseModel):
    id: str
    timestamp: datetime
    user_email: str
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    detail: Optional[Any] = None
    ip_address: Optional[str] = None


class RoleInfo(BaseModel):
    key: str
    label: str
    description: str
    sensitive: bool
