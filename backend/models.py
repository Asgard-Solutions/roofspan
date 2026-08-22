import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, Integer, Float, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


def _now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="sales")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class IntegrationSetting(Base):
    """Server-side provider credentials & config (RentCast, MapTiler)."""
    __tablename__ = "integration_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AppConfig(Base):
    """Singleton-style non-secret configuration (map config, company profile)."""
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ---------- Phase 2: Property Acquisition ----------

class Territory(Base):
    __tablename__ = "territories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#2563EB", nullable=False)
    geometry: Mapped[dict] = mapped_column(JSONB, nullable=False)  # GeoJSON Polygon
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="rentcast", nullable=False)
    territory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("territories.id", ondelete="SET NULL"), nullable=True, index=True)

    formatted_address: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    address_line1: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    zip_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    property_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[float | None] = mapped_column(Float, nullable=True)
    square_footage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_occupied: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    do_not_knock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    do_not_knock_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class PropertyContact(Base):
    __tablename__ = "property_contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="owner", nullable=False)  # owner | renter
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    contact_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # Individual | Company
    mailing_address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    visited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    outcome: Mapped[str] = mapped_column(String(32), default="no_answer", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    source_visit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    territory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("territories.id", ondelete="SET NULL"), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="rentcast", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)  # pending|running|completed|failed
    estimated_requests: Mapped[int] = mapped_column(Integer, default=0)
    estimated_properties: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------- Phase 3: Sales ----------

class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class CustomerProperty(Base):
    __tablename__ = "customer_properties"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), index=True)


class Inspection(Base):
    __tablename__ = "inspections"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    property_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    inspection_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inspector: Mapped[str | None] = mapped_column(String(255), nullable=True)
    roof_condition: Mapped[str | None] = mapped_column(String(64), nullable=True)
    findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    measurements: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_refs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class _LineItem:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    description: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=1, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), default="ea", nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    line_total: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Estimate(Base):
    __tablename__ = "estimates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    property_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    inspection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("inspections.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    tax_rate: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    subtotal: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    tax: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    total: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class EstimateLineItem(_LineItem, Base):
    __tablename__ = "estimate_line_items"
    estimate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("estimates.id", ondelete="CASCADE"), index=True)
    # --- Estimating Modernization: catalog linkage (nullable — custom lines still work) ---
    material_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id", ondelete="SET NULL"), nullable=True, index=True)
    supplier_material_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("supplier_materials.id", ondelete="SET NULL"), nullable=True)
    line_kind: Mapped[str] = mapped_column(String(24), default="custom", nullable=False)  # custom | material | labor | assembly
    # cost components (per estimate unit)
    base_cost: Mapped[float] = mapped_column(Float, default=0, nullable=False)          # snapshot supplier cost / estimate unit
    material_cost: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    labor_cost: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    equipment_cost: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    subcontract_cost: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    # quantities (measured vs waste-adjusted vs order)
    measured_quantity: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    waste_percent: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    order_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)          # in purchase UOM
    purchase_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conversion_factor: Mapped[float | None] = mapped_column(Float, nullable=True)       # estimate-unit → purchase-unit
    # pricing
    markup_percent: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    selling_unit_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)  # customer price / unit (mirrors unit_price)
    # cost snapshot provenance
    cost_source_supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cost_source_supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_item_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost_source: Mapped[str | None] = mapped_column(String(24), nullable=True)           # live | cached | manual
    cost_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # assembly provenance (snapshot)
    assembly_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assembly_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assembly_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Quote(Base):
    __tablename__ = "quotes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    estimate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("estimates.id", ondelete="SET NULL"), nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    property_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    issue_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tax_rate: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    subtotal: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    tax: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    total: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    acceptance_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    multi_package: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    accepted_package_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class QuoteLineItem(_LineItem, Base):
    __tablename__ = "quote_line_items"
    quote_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), index=True)
    package_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("quote_packages.id", ondelete="CASCADE"), nullable=True, index=True)
    # internal-only cost snapshot (NEVER exposed on customer-facing output)
    material_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    total_unit_cost: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    markup_percent: Mapped[float] = mapped_column(Float, default=0, nullable=False)


class QuotePackage(Base):
    __tablename__ = "quote_packages"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quote_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="", nullable=False)  # e.g. Good / Better / Best (user-defined)
    tier: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subtotal: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    tax: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    total: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Assembly(Base):
    __tablename__ = "assemblies"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit_basis: Mapped[str] = mapped_column(String(32), default="SQ", nullable=False)  # e.g. per 1 SQ
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AssemblyItem(Base):
    __tablename__ = "assembly_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assembly_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assemblies.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id", ondelete="SET NULL"), nullable=True)
    description: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    quantity_factor: Mapped[float] = mapped_column(Float, default=1, nullable=False)  # qty per 1 unit_basis
    unit: Mapped[str] = mapped_column(String(32), default="ea", nullable=False)
    waste_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_labor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PriceBook(Base):
    __tablename__ = "price_books"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class PriceBookEntry(Base):
    __tablename__ = "price_book_entries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    price_book_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("price_books.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(24), default="material", nullable=False)  # material | labor | assembly
    material_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), nullable=True)
    assembly_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)  # for labor/service entries
    rule_type: Mapped[str] = mapped_column(String(16), default="markup", nullable=False)  # fixed | markup | margin
    fixed_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    markup_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    quote_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("quotes.id", ondelete="SET NULL"), nullable=True, unique=True, index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    property_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False, index=True)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    total: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    property_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    quote_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("quotes.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    issue_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tax_rate: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    subtotal: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    tax: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    total: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class InvoiceLineItem(_LineItem, Base):
    __tablename__ = "invoice_line_items"
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), index=True)


class Counter(Base):
    __tablename__ = "counters"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------- Phase 4: Operations ----------

class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (UniqueConstraint("name", name="uq_materials_name"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit: Mapped[str] = mapped_column(String(32), default="each", nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    quantity_on_hand: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    reorder_threshold: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    # --- Master material identity (RoofSpan-owned; supplier-independent). All optional. ---
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_family: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(128), nullable=True)
    color: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_variant: Mapped[str | None] = mapped_column(String(128), nullable=True)
    purchase_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)   # purchase UoM
    conversion_factor: Mapped[float] = mapped_column(Float, default=1, nullable=False)  # purchase→base
    coverage_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    upc: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manufacturer_part_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    taxable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    # Vendor linkage (LEGACY — kept for backward compat only; SupplierMaterial is the source of truth).
    # ABC branch AVAILABILITY is never written to quantity_on_hand — these fields are identity only.
    vendor: Mapped[str | None] = mapped_column(String(64), nullable=True)  # e.g. "ABC Supply"
    abc_item_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    abc_catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    abc_uom: Mapped[str | None] = mapped_column(String(32), nullable=True)
    abc_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class InventoryTxn(Base):
    __tablename__ = "inventory_txns"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), index=True)
    delta: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), default="adjustment", nullable=False)
    po_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    integration_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)  # "abc_supply" | None(manual)
    integration_status: Mapped[str | None] = mapped_column(String(24), nullable=True)  # connected|not_connected|manual
    supplier_type: Mapped[str | None] = mapped_column(String(48), nullable=True)  # distributor|manufacturer|manual|other
    account_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sales_rep: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ordering_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(128), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delivery_terms: Mapped[str | None] = mapped_column(String(128), nullable=True)
    minimum_order: Mapped[float | None] = mapped_column(Float, nullable=True)
    freight_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tax_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class SupplierPriceHistory(Base):
    """Immutable price snapshot for a SupplierMaterial. Manual price edits and supplier price refreshes
    append a row; historical PO/estimate/quote costs are never rewritten from these."""
    __tablename__ = "supplier_price_history"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    supplier_material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("supplier_materials.id", ondelete="CASCADE"), index=True, nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    material_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True, nullable=True)
    branch_context: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(24), nullable=True)  # manual|abc_live|abc_cache
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SupplierMaterial(Base):
    """Generic supplier↔material mapping. Source of truth for supplier-specific identity/pricing/
    availability so the core Material stays supplier-independent. ABC Supply is one provider; SRS/Beacon/
    manual can be added without touching Material. `is_preferred` marks the user-selected primary
    supplier (at most one active preferred per material — enforced in the service layer)."""
    __tablename__ = "supplier_materials"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), index=True, nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), index=True, nullable=True)
    integration_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)  # "abc_supply" | "manual"
    external_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    supplier_item_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supplier_description: Mapped[str | None] = mapped_column(String(600), nullable=True)
    supplier_uom: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conversion_factor: Mapped[float] = mapped_column(Float, default=1, nullable=False)
    manufacturer_part_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    branch_context: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    price_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    availability_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    availability_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class JobMaterial(Base):
    __tablename__ = "job_materials"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), index=True)
    planned_quantity: Mapped[float] = mapped_column(Float, default=1, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    order_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ABC Supply linkage (nullable; only set for ABC-supplied POs). Does not affect generic POs.
    integration_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)  # "abc_supply"
    abc_ship_to_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abc_branch_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # ABC order (Phase 3) — set only after an ABC order is submitted.
    external_order_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_confirmation_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_tracking_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abc_order_status: Mapped[str | None] = mapped_column(String(48), nullable=True)  # raw ABC status
    abc_normalized_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    abc_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    abc_last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class POLineItem(Base):
    __tablename__ = "po_line_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id", ondelete="SET NULL"), nullable=True)
    description: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=1, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), default="each", nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    line_total: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    received_quantity: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    # ABC Supply line metadata (nullable; retained for Phase 3 ordering + traceability).
    integration_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)  # "abc_supply"
    abc_item_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abc_branch_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abc_ship_to_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abc_uom: Mapped[str | None] = mapped_column(String(32), nullable=True)
    abc_variation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    abc_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    abc_price_status: Mapped[str | None] = mapped_column(String(24), nullable=True)  # priced | unavailable
    abc_price_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    abc_product_description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    abc_product_family: Mapped[str | None] = mapped_column(String(255), nullable=True)
    abc_product_image_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    pricing_source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # abc | manual



class Photo(Base):
    __tablename__ = "photos"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    object_path: Mapped[str] = mapped_column(String(400), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream", nullable=False)
    record_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    record_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


# ---------- Commercial Layer / Phase C0: Licensing ----------

class LicenseCache(Base):
    """Locally-cached signed entitlement (source of truth for offline licensing).

    Single row per installation. The raw signed JWS is the trust anchor; decoded fields are stored
    for fast reads and are re-verified against the JWS on load. Contains NO business data.
    """
    __tablename__ = "license_cache"
    installation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    license_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entitlement_jws: Mapped[str | None] = mapped_column(Text, nullable=True)
    kid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subscription_state: Mapped[str] = mapped_column(String(16), default="SUSPENDED", nullable=False)
    seats_licensed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    product: Mapped[str] = mapped_column(String(64), default="roofspan-office", nullable=False)
    min_supported_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)



# ---------- ABC Supply Integration (RoofSpan Office / Desktop only) ----------

class AbcIntegration(Base):
    """Singleton-style ABC Supply connection state + per-install config for this RoofSpan Office.

    Client secret and OAuth tokens are AES-GCM encrypted (core.encrypt_secret). Contains NO
    roofing business data — purchasing/order linkage lives on existing PO tables (later phases)."""
    __tablename__ = "abc_integrations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    environment: Mapped[str] = mapped_column(String(16), default="sandbox", nullable=False)  # sandbox|production
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_secret_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    redirect_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_public_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="not_connected", nullable=False)  # not_connected|connected|reconnect_required
    # user OAuth tokens (encrypted)
    access_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_scopes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # transient PKCE verifier + CSRF state during an in-flight authorization
    pkce_verifier_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_state: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # connected identity + selected defaults
    connected_identity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    default_ship_to_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_branch_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AbcAccountLink(Base):
    """Convenience cache of a selected ABC account hierarchy (sold-to/bill-to/ship-to + branches).

    ABC remains authoritative; this only speeds up repeated reads and stores non-retired ship-tos."""
    __tablename__ = "abc_account_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ship_to_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    ship_to_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bill_to_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bill_to_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sold_to_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sold_to_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    branches: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    home_branch_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AbcOrderSubmission(Base):
    """Durable ABC order submission record — the backbone of duplicate/idempotency/unknown-state handling.

    `submission_key` is unique (also sent to ABC as requestId). Only one confirmed submission may exist
    per purchase order. status: pending | confirmed | failed | unknown."""
    __tablename__ = "abc_order_submissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    submission_key: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    abc_confirmation_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abc_order_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abc_tracking_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delivery: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


# ---------- ABC Supply Notifications / Webhooks (Phase 4) ----------

class AbcWebhookRegistration(Base):
    """Central integration metadata for the single ABC webhook (secret encrypted). Allowed central
    exception: the public receiver must authenticate ABC before it knows which install owns the order."""
    __tablename__ = "abc_webhook_registrations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    environment: Mapped[str] = mapped_column(String(16), default="sandbox", nullable=False)
    webhook_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="not_registered", nullable=False)
    events: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AbcOrderRoute(Base):
    """Routing index (transport metadata only): maps ABC order/confirmation/PO number to a local install."""
    __tablename__ = "abc_order_routes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installation_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    abc_order_number: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    abc_confirmation_number: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    roofspan_po_number: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AbcWebhookDelivery(Base):
    """Durable transport queue for authenticated events awaiting delivery to a local install.
    Minimal encrypted payload only — NOT an authoritative business store. Bounded retry."""
    __tablename__ = "abc_webhook_deliveries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_key: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    installation_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    abc_order_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abc_confirmation_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    roofspan_po_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="received", nullable=False)  # received|queued|delivering|delivered|failed|dead_letter
    routing_status: Mapped[str] = mapped_column(String(16), default="matched", nullable=False)  # matched|unmatched
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AbcNotificationEvent(Base):
    """Local idempotency + audit of processed ABC events (per install). Unique event_key."""
    __tablename__ = "abc_notification_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_key: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    abc_order_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abc_confirmation_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True, nullable=True)
    abc_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="processed", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AbcInvoiceEvent(Base):
    """Local invoice-event linking metadata (NOT full AP). Associated with a local PO."""
    __tablename__ = "abc_invoice_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True, nullable=True)
    abc_invoice_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abc_invoice_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    abc_order_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abc_purchase_order_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_credit_memo: Mapped[bool] = mapped_column(Boolean, default=False)
    is_rebill: Mapped[bool] = mapped_column(Boolean, default=False)
    event_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    payload_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)


# ---------- ABC Supply Vendor Catalog (local cache of ABC master product data) ----------

class AbcCatalogItem(Base):
    """Local cache of an ABC Supply vendor product (master data). This is VENDOR data, NOT RoofSpan
    on-hand inventory. Availability at a branch is derived from `branch_numbers`; ABC does not expose
    physical quantity-on-hand, so this is never treated as stock. `material_id` links an imported item
    to a RoofSpan Material (the durable ABC↔RoofSpan mapping used for future pricing/ordering)."""
    __tablename__ = "abc_catalog_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    abc_item_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(600), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    family_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    family_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit_of_measure: Mapped[str | None] = mapped_column(String(32), nullable=True)
    uoms: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)  # active | inactive
    image_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    is_dimensional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    branch_numbers: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # branches item is purchasable from
    abc_last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    material_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id", ondelete="SET NULL"), nullable=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AbcCatalogSync(Base):
    """Singleton-style sync status for the ABC vendor catalog. One row tracks the last full/incremental
    sync so the UI can show 'Last synced' / 'Syncing' / 'Sync failed' without misleading percentages."""
    __tablename__ = "abc_catalog_sync"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(16), default="never_synced", nullable=False)  # never_synced|syncing|completed|failed
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_full_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # from the last run
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # total catalog rows locally
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
