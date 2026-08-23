"""Pydantic schemas for the RoofSpan-facing ABC integration API (request/response DTOs).

These describe the RoofSpan Office API surface (our own endpoints), not the raw ABC contracts.
Raw ABC objects are passed through as dicts where their shape is large and documented upstream.
"""
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator


# ---- Config / connection ----
class AbcConfigUpdate(BaseModel):
    environment: Optional[str] = None  # sandbox | production
    client_id: Optional[str] = None
    redirect_uri: Optional[str] = None
    webhook_public_url: Optional[str] = None


class AbcSecretUpdate(BaseModel):
    client_secret: str = Field(min_length=1)


class AbcDefaultsUpdate(BaseModel):
    default_ship_to_number: Optional[str] = None
    default_branch_number: Optional[str] = None


class AbcStatusOut(BaseModel):
    environment: str
    status: str  # not_connected | connected | reconnect_required
    is_mock: bool
    has_client_id: bool
    has_client_secret: bool
    client_id_masked: Optional[str] = None
    redirect_uri: Optional[str] = None
    redirect_uri_effective: Optional[str] = None
    webhook_public_url: Optional[str] = None
    connected_identity: Optional[dict] = None
    default_ship_to_number: Optional[str] = None
    default_branch_number: Optional[str] = None
    token_scopes: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    connected_at: Optional[datetime] = None
    last_connected_at: Optional[datetime] = None


class AbcConnectOut(BaseModel):
    authorize_url: str


class AbcTestResult(BaseModel):
    ok: bool
    message: str


class AbcShipToOut(BaseModel):
    number: str
    name: Optional[str] = None
    status: Optional[str] = None
    address: Optional[dict] = None
    bill_to_number: Optional[str] = None
    bill_to_name: Optional[str] = None
    sold_to_number: Optional[str] = None
    sold_to_name: Optional[str] = None
    branches: List[dict] = []
    home_branch_number: Optional[str] = None


class AbcBranchOut(BaseModel):
    number: str
    name: Optional[str] = None
    storefront: Optional[str] = None
    status: Optional[str] = None
    distance: Optional[float] = None
    address: Optional[dict] = None
    home_branch: Optional[bool] = None


# ---- Product & Pricing (Phase 2) ----
class AbcProductSearchIn(BaseModel):
    query: Optional[str] = None
    by: str = "itemDescription"  # itemDescription | itemNumber
    branch_number: Optional[str] = None
    family_id: Optional[str] = None
    page: int = 1


class AbcProductOut(BaseModel):
    item_number: str
    description: Optional[str] = None
    family_id: Optional[str] = None
    family_name: Optional[str] = None
    manufacturer: Optional[str] = None
    is_dimensional: bool = False
    uoms: List[dict] = []
    color: Optional[str] = None
    product_family: Optional[str] = None
    image_url: Optional[str] = None
    available_at_branch: Optional[bool] = None
    branch_number: Optional[str] = None


class AbcPriceLineIn(BaseModel):
    id: str
    item_number: str
    quantity: float = Field(gt=0)
    uom: Optional[str] = None
    length_value: Optional[float] = None
    length_uom: Optional[str] = None


class AbcPriceIn(BaseModel):
    ship_to_number: str
    branch_number: str
    purpose: str = "ordering"
    request_id: Optional[str] = None
    lines: List[AbcPriceLineIn] = []

    @field_validator("purpose")
    @classmethod
    def _valid_purpose(cls, v: str) -> str:
        p = (v or "").strip().lower()
        if p not in ("estimating", "quoting", "ordering"):
            raise ValueError("purpose must be one of: estimating, quoting, ordering")
        return p


# ---- Vendor Catalog (Inventory) ----
class AbcCatalogItemOut(BaseModel):
    id: Optional[str] = None  # local catalog row id (present once cached)
    item_number: str
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    family_id: Optional[str] = None
    family_name: Optional[str] = None
    unit_of_measure: Optional[str] = None
    uoms: List[dict] = []
    status: str = "active"
    is_dimensional: bool = False
    image_url: Optional[str] = None
    available_at_branch: Optional[bool] = None  # for the active/default branch; None = unknown
    branch_number: Optional[str] = None
    in_inventory: bool = False
    material_id: Optional[str] = None


class AbcCatalogContext(BaseModel):
    connected: bool
    ship_to_number: Optional[str] = None
    ship_to_name: Optional[str] = None
    branch_number: Optional[str] = None
    needs_ship_to: bool = False
    needs_branch: bool = False


class AbcCatalogListOut(BaseModel):
    items: List[AbcCatalogItemOut] = []
    page: int = 1
    page_size: int = 25
    total: Optional[int] = None
    total_pages: Optional[int] = None
    source: str = "cache"  # cache | live
    context: AbcCatalogContext


class AbcCatalogSyncOut(BaseModel):
    status: str
    last_synced_at: Optional[datetime] = None
    last_full_sync_at: Optional[datetime] = None
    items_synced: int = 0
    total_items: int = 0
    last_error: Optional[str] = None
    started_at: Optional[datetime] = None


class AbcAddToInventoryIn(BaseModel):
    branch_number: Optional[str] = None
    name_override: Optional[str] = None


class AbcAddToInventoryOut(BaseModel):
    material_id: str
    material_name: str
    created: bool
    already_linked: bool
    abc_item_number: str


class SupplierMaterialOut(BaseModel):
    id: str
    material_id: str
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    integration_provider: Optional[str] = None
    external_item_id: Optional[str] = None
    supplier_item_number: Optional[str] = None
    supplier_description: Optional[str] = None
    supplier_uom: Optional[str] = None
    current_cost: Optional[float] = None
    price_status: Optional[str] = None
    price_updated_at: Optional[datetime] = None
    availability_status: Optional[str] = None
    lead_time_days: Optional[int] = None
    is_preferred: bool = False
    active: bool = True
