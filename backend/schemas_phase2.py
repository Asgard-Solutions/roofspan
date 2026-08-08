from datetime import datetime
from typing import Optional, Any, List

from pydantic import BaseModel, Field


# ---- Territories ----
class TerritoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    color: str = "#2563EB"
    geometry: dict  # GeoJSON Polygon
    active: bool = True


class TerritoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    geometry: Optional[dict] = None
    active: Optional[bool] = None


class TerritoryOut(BaseModel):
    id: str
    name: str
    description: str
    color: str
    geometry: dict
    active: bool
    property_count: int = 0
    created_by: Optional[str] = None
    created_at: datetime


# ---- Properties ----
class ContactOut(BaseModel):
    id: str
    kind: str
    name: str
    contact_type: Optional[str] = None
    mailing_address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class VisitOut(BaseModel):
    id: str
    visited_at: datetime
    user_email: str
    outcome: str
    notes: Optional[str] = None
    created_at: datetime


class VisitIn(BaseModel):
    outcome: str = "no_answer"
    notes: Optional[str] = None
    visited_at: Optional[datetime] = None


class PropertyOut(BaseModel):
    id: str
    external_id: Optional[str] = None
    source: str
    territory_id: Optional[str] = None
    formatted_address: str
    address_line1: str
    city: str
    state: str
    zip_code: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    property_type: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    square_footage: Optional[int] = None
    year_built: Optional[int] = None
    owner_occupied: Optional[bool] = None
    do_not_knock: bool
    do_not_knock_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class PropertyDetail(PropertyOut):
    contacts: List[ContactOut] = []
    visits: List[VisitOut] = []
    lead_id: Optional[str] = None


class PropertyCreate(BaseModel):
    territory_id: Optional[str] = None
    address_line1: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    property_type: Optional[str] = None
    owner_name: Optional[str] = None


class PropertyPatch(BaseModel):
    do_not_knock: Optional[bool] = None
    do_not_knock_reason: Optional[str] = None
    notes: Optional[str] = None
    territory_id: Optional[str] = None


# ---- Imports ----
class ImportPreviewIn(BaseModel):
    mode: Optional[str] = None  # "rentcast" | "sample" | None(auto)
    max_records: int = Field(default=50, ge=1, le=500)


class ImportPreviewOut(BaseModel):
    mode: str
    rentcast_configured: bool
    estimated_requests: int
    estimated_properties: int
    radius_miles: float
    sample: List[dict] = []
    note: str = ""


class ImportStartIn(BaseModel):
    mode: Optional[str] = None
    max_records: int = Field(default=50, ge=1, le=500)


class ImportJobOut(BaseModel):
    id: str
    territory_id: Optional[str] = None
    mode: str
    status: str
    estimated_requests: int
    estimated_properties: int
    total: int
    processed: int
    created_count: int
    updated_count: int
    skipped_count: int
    error: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None


# ---- Leads ----
class ConvertLeadIn(BaseModel):
    visit_id: Optional[str] = None
    name: str = ""
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


class LeadOut(BaseModel):
    id: str
    property_id: Optional[str] = None
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    status: str
    notes: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    property_address: Optional[str] = None


class LeadPatch(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


# ---- Account ----
class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)
