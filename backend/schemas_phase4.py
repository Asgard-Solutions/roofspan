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
    # master fields (all optional)
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    product_family: Optional[str] = None
    subcategory: Optional[str] = None
    color: Optional[str] = None
    size_variant: Optional[str] = None
    purchase_unit: Optional[str] = None
    conversion_factor: float = Field(default=1, gt=0)
    coverage_amount: Optional[float] = None
    coverage_unit: Optional[str] = None
    weight: Optional[float] = None
    upc: Optional[str] = None
    manufacturer_part_number: Optional[str] = None
    taxable: bool = True
    image_url: Optional[str] = None
    standard_cost: Optional[float] = None
    default_sell_price: Optional[float] = None


class MaterialPatch(BaseModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None
    reorder_threshold: Optional[float] = Field(default=None, ge=0)
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    product_family: Optional[str] = None
    subcategory: Optional[str] = None
    color: Optional[str] = None
    size_variant: Optional[str] = None
    purchase_unit: Optional[str] = None
    conversion_factor: Optional[float] = Field(default=None, gt=0)
    coverage_amount: Optional[float] = None
    coverage_unit: Optional[str] = None
    weight: Optional[float] = None
    upc: Optional[str] = None
    manufacturer_part_number: Optional[str] = None
    taxable: Optional[bool] = None
    image_url: Optional[str] = None
    standard_cost: Optional[float] = None
    default_sell_price: Optional[float] = None


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


class QuantitiesOut(BaseModel):
    on_hand: float
    reserved: float
    available: float
    on_order: float
    required: float
    projected: float


class MaterialListItemOut(MaterialOut):
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    status: str = "active"
    # operational quantities
    on_hand: float = 0
    reserved: float = 0
    available: float = 0
    on_order: float = 0
    required: float = 0
    projected: float = 0
    # supplier context
    primary_supplier_name: Optional[str] = None   # user-selected preferred supplier
    primary_supplier_cost: Optional[float] = None
    primary_supplier_provider: Optional[str] = None
    primary_supplier_status: Optional[str] = None      # priced | live | cached | manual | unavailable
    primary_supplier_updated_at: Optional[datetime] = None
    best_known_cost: Optional[float] = None        # lowest active supplier cost (labeled separately)
    best_supplier_name: Optional[str] = None
    best_supplier_provider: Optional[str] = None
    best_supplier_status: Optional[str] = None
    best_supplier_updated_at: Optional[datetime] = None
    supplier_count: int = 0
    # --- Effective Cost + Default-Price-Book Price (computed live; never stored) ---
    effective_cost: Optional[float] = None
    effective_cost_source: Optional[str] = None        # preferred_supplier | best_known_cost | standard_cost | mwac
    effective_cost_supplier_id: Optional[str] = None
    effective_cost_supplier_name: Optional[str] = None
    effective_price: Optional[float] = None
    price_book_id: Optional[str] = None
    price_book_name: Optional[str] = None
    matched_rule_id: Optional[str] = None
    matched_rule_type: Optional[str] = None
    matched_rule_label: Optional[str] = None
    # Planning values (manual). standard_cost is a fallback cost; never MWAC.
    standard_cost: Optional[float] = None
    default_sell_price: Optional[float] = None


class MaterialFacetsOut(BaseModel):
    categories: List[str] = []
    manufacturers: List[str] = []
    suppliers: List[dict] = []  # {id, name}


class TxnOut(BaseModel):
    id: str
    txn_type: str
    delta: float
    note: Optional[str] = None
    po_id: Optional[str] = None
    job_id: Optional[str] = None
    location: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime


class OpenPOLineOut(BaseModel):
    po_id: str
    po_number: str
    status: str
    quantity: float
    received_quantity: float
    remaining: float
    unit_cost: float


class JobRequirementOut(BaseModel):
    job_id: str
    job_title: Optional[str] = None
    planned_quantity: float


class MaterialDetailOut(BaseModel):
    material: MaterialListItemOut
    quantities: QuantitiesOut
    suppliers: List[dict] = []
    open_po_lines: List[OpenPOLineOut] = []
    jobs: List[JobRequirementOut] = []
    transactions: List[TxnOut] = []


class AdjustIn(BaseModel):
    delta: float
    reason: str = "manual_correction"
    note: Optional[str] = None
    job_id: Optional[str] = None
    location: Optional[str] = None


class CsvImportRow(BaseModel):
    sku: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    reorder_threshold: Optional[float] = None
    quantity_on_hand: Optional[float] = None


class CsvPreviewIn(BaseModel):
    rows: List[dict] = []
    csv_text: Optional[str] = None  # raw CSV text (parsed server-side with a standards-compliant parser)


class CsvPreviewRowOut(BaseModel):
    row_number: int
    action: str  # create | update | error
    sku: Optional[str] = None
    name: Optional[str] = None
    material_id: Optional[str] = None
    changes: dict = {}
    errors: List[str] = []


class CsvPreviewOut(BaseModel):
    rows: List[CsvPreviewRowOut] = []
    create_count: int = 0
    update_count: int = 0
    error_count: int = 0
    header_errors: List[str] = []


class CsvCommitIn(BaseModel):
    rows: List[dict] = []
    csv_text: Optional[str] = None
    confirm_updates: bool = False  # explicit confirmation required to apply updates


# ---- Suppliers ----
class SupplierIn(BaseModel):
    name: str = Field(min_length=1)
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True
    supplier_type: Optional[str] = None
    account_number: Optional[str] = None
    sales_rep: Optional[str] = None
    ordering_email: Optional[str] = None
    website: Optional[str] = None
    payment_terms: Optional[str] = None
    default_branch: Optional[str] = None
    delivery_terms: Optional[str] = None
    minimum_order: Optional[float] = None
    freight_notes: Optional[str] = None
    tax_notes: Optional[str] = None


class SupplierPatch(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    active: Optional[bool] = None
    supplier_type: Optional[str] = None
    account_number: Optional[str] = None
    sales_rep: Optional[str] = None
    ordering_email: Optional[str] = None
    website: Optional[str] = None
    payment_terms: Optional[str] = None
    default_branch: Optional[str] = None
    delivery_terms: Optional[str] = None
    minimum_order: Optional[float] = None
    freight_notes: Optional[str] = None
    tax_notes: Optional[str] = None


class SupplierOut(SupplierIn):
    id: str
    integration_provider: Optional[str] = None  # never exposes secrets
    integration_status: Optional[str] = None
    capabilities: List[str] = []


class ManualSupplierMaterialIn(BaseModel):
    material_id: str
    supplier_id: str
    supplier_item_number: Optional[str] = None
    supplier_description: Optional[str] = None
    supplier_uom: Optional[str] = None
    conversion_factor: float = 1
    manufacturer_part_number: Optional[str] = None
    current_cost: Optional[float] = None
    lead_time_days: Optional[int] = None
    notes: Optional[str] = None


class ManualSupplierMaterialPatch(BaseModel):
    supplier_item_number: Optional[str] = None
    supplier_description: Optional[str] = None
    supplier_uom: Optional[str] = None
    conversion_factor: Optional[float] = None
    manufacturer_part_number: Optional[str] = None
    current_cost: Optional[float] = None
    lead_time_days: Optional[int] = None
    notes: Optional[str] = None


class PriceHistoryOut(BaseModel):
    id: str
    cost: Optional[float] = None
    source: Optional[str] = None
    branch_context: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime


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
    supplier_id: Optional[str] = None
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
    location_id: Optional[str] = None


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
