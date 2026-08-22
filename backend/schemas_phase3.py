from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class LineItemIn(BaseModel):
    description: str = ""
    quantity: float = 1
    unit: str = "ea"
    unit_price: float = 0
    # --- Estimating Modernization (all optional; legacy custom lines unaffected) ---
    material_id: Optional[str] = None
    supplier_material_id: Optional[str] = None
    line_kind: Optional[str] = None            # custom | material | labor | assembly
    base_cost: Optional[float] = None
    material_cost: Optional[float] = None
    labor_cost: Optional[float] = None
    equipment_cost: Optional[float] = None
    subcontract_cost: Optional[float] = None
    measured_quantity: Optional[float] = None
    waste_percent: Optional[float] = None
    conversion_factor: Optional[float] = None
    purchase_unit: Optional[str] = None
    markup_percent: Optional[float] = None
    margin_percent: Optional[float] = None
    pricing_mode: Optional[str] = None         # markup | margin | fixed
    selling_unit_price: Optional[float] = None
    # snapshot provenance (client may pass; server re-snapshots authoritatively when material given)
    cost_source_supplier_id: Optional[str] = None
    cost_source_supplier_name: Optional[str] = None
    supplier_item_number: Optional[str] = None
    cost_source: Optional[str] = None
    assembly_id: Optional[str] = None
    assembly_version: Optional[int] = None
    assembly_name: Optional[str] = None


class LineItemOut(BaseModel):
    id: str
    description: str = ""
    quantity: float = 1
    unit: str = "ea"
    unit_price: float = 0
    line_total: float = 0
    # estimating fields (may be None for pure custom lines; cost fields gated by RBAC on estimate output)
    material_id: Optional[str] = None
    supplier_material_id: Optional[str] = None
    line_kind: Optional[str] = None
    base_cost: Optional[float] = None
    material_cost: Optional[float] = None
    labor_cost: Optional[float] = None
    equipment_cost: Optional[float] = None
    subcontract_cost: Optional[float] = None
    unit_cost: Optional[float] = None
    extended_cost: Optional[float] = None
    measured_quantity: Optional[float] = None
    waste_percent: Optional[float] = None
    order_quantity: Optional[float] = None
    purchase_unit: Optional[str] = None
    conversion_factor: Optional[float] = None
    markup_percent: Optional[float] = None
    selling_unit_price: Optional[float] = None
    cost_source_supplier_id: Optional[str] = None
    cost_source_supplier_name: Optional[str] = None
    supplier_item_number: Optional[str] = None
    cost_source: Optional[str] = None
    cost_snapshot_at: Optional[datetime] = None
    assembly_id: Optional[str] = None
    assembly_version: Optional[int] = None
    assembly_name: Optional[str] = None


# ---- Customers ----
class CustomerIn(BaseModel):
    name: str = Field(min_length=1)
    phone: Optional[str] = None
    email: Optional[str] = None
    billing_address: Optional[str] = None
    status: str = "active"
    notes: Optional[str] = None


class CustomerPatch(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    billing_address: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class CustomerOut(BaseModel):
    id: str
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    billing_address: Optional[str] = None
    status: str
    notes: Optional[str] = None
    created_at: datetime
    property_ids: List[str] = []


# ---- Inspections ----
class InspectionIn(BaseModel):
    lead_id: Optional[str] = None
    customer_id: Optional[str] = None
    property_id: Optional[str] = None
    inspection_date: Optional[datetime] = None
    inspector: Optional[str] = None
    roof_condition: Optional[str] = None
    findings: Optional[str] = None
    recommended_work: Optional[str] = None
    measurements: Optional[str] = None
    notes: Optional[str] = None


class InspectionOut(InspectionIn):
    id: str
    created_by: Optional[str] = None
    created_at: datetime


# ---- Estimates ----
class EstimateIn(BaseModel):
    lead_id: Optional[str] = None
    customer_id: Optional[str] = None
    property_id: Optional[str] = None
    inspection_id: Optional[str] = None
    tax_rate: float = 0
    notes: Optional[str] = None
    items: List[LineItemIn] = []


class EstimateOut(BaseModel):
    id: str
    number: str
    lead_id: Optional[str] = None
    customer_id: Optional[str] = None
    property_id: Optional[str] = None
    inspection_id: Optional[str] = None
    status: str
    tax_rate: float
    subtotal: float
    tax: float
    total: float
    notes: Optional[str] = None
    version: int
    created_at: datetime
    items: List[LineItemOut] = []
    # cost/margin summary — populated only for authorized (internal) roles, else None
    cost_summary: Optional[dict] = None
    can_see_cost: bool = False


# ---- Quotes ----
class QuotePackageIn(BaseModel):
    id: Optional[str] = None
    name: str = ""
    tier: int = 0
    notes: Optional[str] = None
    items: List[LineItemIn] = []


class QuotePackageOut(BaseModel):
    id: str
    name: str
    tier: int
    subtotal: float
    tax: float
    total: float
    notes: Optional[str] = None
    items: List[LineItemOut] = []


class QuoteIn(BaseModel):
    estimate_id: Optional[str] = None
    lead_id: Optional[str] = None
    customer_id: Optional[str] = None
    property_id: Optional[str] = None
    tax_rate: float = 0
    issue_date: Optional[datetime] = None
    expiration_date: Optional[datetime] = None
    terms: Optional[str] = None
    items: List[LineItemIn] = []
    multi_package: bool = False
    packages: List[QuotePackageIn] = []


class QuoteUpdate(BaseModel):
    status: Optional[str] = None
    tax_rate: Optional[float] = None
    issue_date: Optional[datetime] = None
    expiration_date: Optional[datetime] = None
    terms: Optional[str] = None
    items: Optional[List[LineItemIn]] = None
    multi_package: Optional[bool] = None
    packages: Optional[List[QuotePackageIn]] = None


class QuoteAccept(BaseModel):
    acceptance_name: Optional[str] = None
    notes: Optional[str] = None
    package_id: Optional[str] = None


class QuoteOut(BaseModel):
    id: str
    number: str
    estimate_id: Optional[str] = None
    lead_id: Optional[str] = None
    customer_id: Optional[str] = None
    property_id: Optional[str] = None
    status: str
    issue_date: Optional[datetime] = None
    expiration_date: Optional[datetime] = None
    tax_rate: float
    subtotal: float
    tax: float
    total: float
    terms: Optional[str] = None
    accepted_at: Optional[datetime] = None
    accepted_by: Optional[str] = None
    acceptance_name: Optional[str] = None
    version: int
    created_at: datetime
    items: List[LineItemOut] = []
    multi_package: bool = False
    accepted_package_id: Optional[str] = None
    packages: List[QuotePackageOut] = []


class QuoteAcceptResult(BaseModel):
    quote: QuoteOut
    job_id: str


# ---- Jobs ----
class JobOut(BaseModel):
    id: str
    number: str
    quote_id: Optional[str] = None
    customer_id: Optional[str] = None
    property_id: Optional[str] = None
    status: str
    scope: Optional[str] = None
    total: float
    created_at: datetime
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None


# ---- Invoices ----
class InvoiceIn(BaseModel):
    quote_id: Optional[str] = None
    job_id: Optional[str] = None
    customer_id: Optional[str] = None
    property_id: Optional[str] = None
    tax_rate: float = 0
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    items: List[LineItemIn] = []


class InvoiceStatusIn(BaseModel):
    status: str


class InvoiceOut(BaseModel):
    id: str
    number: str
    quote_id: Optional[str] = None
    job_id: Optional[str] = None
    customer_id: Optional[str] = None
    property_id: Optional[str] = None
    status: str
    issue_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    tax_rate: float
    subtotal: float
    tax: float
    total: float
    notes: Optional[str] = None
    created_at: datetime
    items: List[LineItemOut] = []


# ---- Lead detail (enriched) ----
class LeadDetailOut(BaseModel):
    id: str
    property_id: Optional[str] = None
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    status: str
    notes: Optional[str] = None
    customer_id: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    property_address: Optional[str] = None
    owner_name: Optional[str] = None
    customer_name: Optional[str] = None
    visits: list = []
