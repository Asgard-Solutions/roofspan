from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ---- Materials ----
class MaterialIn(BaseModel):
    name: str = Field(min_length=1)
    sku: Optional[str] = None
    category: Optional[str] = None
    unit: str = "each"
    description: Optional[str] = None
    active: bool = True
    reorder_threshold: float = Field(default=0, ge=0)
    quantity_on_hand: float = Field(default=0, ge=0)


class MaterialPatch(BaseModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None
    reorder_threshold: Optional[float] = Field(default=None, ge=0)


class MaterialOut(BaseModel):
    id: str
    name: str
    sku: Optional[str] = None
    category: Optional[str] = None
    unit: str
    description: Optional[str] = None
    active: bool
    quantity_on_hand: float
    reorder_threshold: float
    low_stock: bool
    vendor: Optional[str] = None
    abc_item_number: Optional[str] = None


class AdjustIn(BaseModel):
    delta: float
    reason: str = "adjustment"
    note: Optional[str] = None


# ---- Suppliers ----
class SupplierIn(BaseModel):
    name: str = Field(min_length=1)
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True


class SupplierOut(SupplierIn):
    id: str


# ---- Jobs ----
class JobPatch(BaseModel):
    status: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    schedule_notes: Optional[str] = None
    assigned_to: Optional[str] = None
    scope: Optional[str] = None
    notes: Optional[str] = None


class JobMaterialIn(BaseModel):
    material_id: str
    planned_quantity: float = 1
    notes: Optional[str] = None


class JobMaterialOut(BaseModel):
    id: str
    material_id: str
    material_name: str
    unit: str
    planned_quantity: float
    quantity_on_hand: float
    low_stock: bool
    notes: Optional[str] = None


class JobDetailOut(BaseModel):
    id: str
    number: str
    quote_id: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    property_id: Optional[str] = None
    property_address: Optional[str] = None
    status: str
    scope: Optional[str] = None
    notes: Optional[str] = None
    total: float
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    schedule_notes: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    created_at: datetime
    materials: List[JobMaterialOut] = []
    purchase_orders: list = []


# ---- Purchase Orders ----
class POLineIn(BaseModel):
    material_id: Optional[str] = None
    description: str = ""
    quantity: float = Field(default=1, gt=0)
    unit: str = "each"
    unit_cost: float = Field(default=0, ge=0)
    # ABC Supply line metadata (optional; only present for ABC-supplied lines)
    integration_provider: Optional[str] = None
    abc_item_number: Optional[str] = None
    abc_branch_number: Optional[str] = None
    abc_ship_to_number: Optional[str] = None
    abc_uom: Optional[str] = None
    abc_variation: Optional[dict] = None
    abc_price: Optional[float] = None
    abc_price_status: Optional[str] = None
    abc_product_description: Optional[str] = None
    abc_product_family: Optional[str] = None
    abc_product_image_url: Optional[str] = None
    pricing_source: Optional[str] = None


class POLineOut(POLineIn):
    id: str
    line_total: float
    received_quantity: float
    abc_price_timestamp: Optional[datetime] = None


class POIn(BaseModel):
    supplier_name: Optional[str] = None
    job_id: Optional[str] = None
    expected_date: Optional[datetime] = None
    notes: Optional[str] = None
    integration_provider: Optional[str] = None
    abc_ship_to_number: Optional[str] = None
    abc_branch_number: Optional[str] = None
    items: List[POLineIn] = []


class POStatusIn(BaseModel):
    status: str


class RefreshPriceIn(BaseModel):
    po_item_id: str
    apply: bool = False  # when true, apply the refreshed ABC price to the line unit_cost


class RefreshPriceOut(BaseModel):
    po_item_id: str
    previous_unit_cost: float
    abc_price: Optional[float] = None
    price_status: str
    changed: bool
    applied: bool
    message: Optional[str] = None


class AbcSubmitReviewIn(BaseModel):
    apply_price_changes: bool = False


class AbcSubmitIn(BaseModel):
    submission_key: str = Field(min_length=8, max_length=80)
    accept_price_changes: bool = False
    delivery: Optional[dict] = None
    delivery_service: str = "OTG"  # ABC delivery service enum (e.g. OTG: Our Truck Ground)


class ReceiveLine(BaseModel):
    po_item_id: str
    quantity: float = Field(gt=0)


class ReceiveIn(BaseModel):
    items: List[ReceiveLine] = []


class POOut(BaseModel):
    id: str
    number: str
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    job_id: Optional[str] = None
    status: str
    order_date: Optional[datetime] = None
    expected_date: Optional[datetime] = None
    total: float
    notes: Optional[str] = None
    created_at: datetime
    integration_provider: Optional[str] = None
    abc_ship_to_number: Optional[str] = None
    abc_branch_number: Optional[str] = None
    external_order_number: Optional[str] = None
    external_confirmation_number: Optional[str] = None
    external_tracking_id: Optional[str] = None
    abc_order_status: Optional[str] = None
    abc_normalized_status: Optional[str] = None
    abc_submitted_at: Optional[datetime] = None
    abc_last_sync_at: Optional[datetime] = None
    abc_delivery: Optional[dict] = None
    pricing_warning: Optional[str] = None
    items: List[POLineOut] = []
