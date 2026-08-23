from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class CanvassSectionCreate(BaseModel):
    territory_id: str
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    color: str = "#2563EB"
    geometry: dict  # GeoJSON Polygon
    assigned_user_id: Optional[str] = None
    active: bool = True


class CanvassSectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    geometry: Optional[dict] = None
    assigned_user_id: Optional[str] = None
    active: Optional[bool] = None


class CanvassSectionOut(BaseModel):
    id: str
    territory_id: str
    name: str
    description: str
    color: str
    geometry: dict
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    active: bool
    property_count: int = 0
    do_not_knock_count: int = 0
    created_by: Optional[str] = None
    created_at: datetime


class CanvassSectionPreviewIn(BaseModel):
    territory_id: str
    geometry: dict
    exclude_section_id: Optional[str] = None


class ConflictOut(BaseModel):
    property_id: str
    address: str
    section_id: str
    section_name: str
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None


class CanvassSectionPreviewOut(BaseModel):
    property_count: int
    available_count: int
    conflict_count: int
    do_not_knock_count: int
    conflicts: List[ConflictOut] = []


class CanvassSectionPropertyOut(BaseModel):
    id: str
    formatted_address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    property_type: Optional[str] = None
    owner_occupied: Optional[bool] = None
    do_not_knock: bool = False
