from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class LineItemIn(BaseModel):
    description: str = ""
    quantity: float = 1
    unit: str = "ea"
    unit_price: float = 0


class LineItemOut(LineItemIn):
    id: str
    line_total: float


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


# ---- Quotes ----
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


class QuoteUpdate(BaseModel):
    status: Optional[str] = None
    tax_rate: Optional[float] = None
    issue_date: Optional[datetime] = None
    expiration_date: Optional[datetime] = None
    terms: Optional[str] = None
    items: Optional[List[LineItemIn]] = None


class QuoteAccept(BaseModel):
    acceptance_name: Optional[str] = None
    notes: Optional[str] = None


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
    created_by: Optional[str] = None
    created_at: datetime
    property_address: Optional[str] = None
    owner_name: Optional[str] = None
    customer_name: Optional[str] = None
    visits: list = []
