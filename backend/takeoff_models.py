"""Increment B/C persistence for versioned roof takeoffs.

These models are intentionally separate from physical measurement models. A takeoff binds an
immutable measurement revision to an immutable template revision and snapshots every generated
estimate-line assumption for auditability.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, Integer, Float, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


def _now():
    return datetime.now(timezone.utc)


class TakeoffTemplate(Base):
    __tablename__ = "takeoff_templates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class TakeoffTemplateRevision(Base):
    __tablename__ = "takeoff_template_revisions"
    __table_args__ = (UniqueConstraint("template_id", "revision_number", name="uq_takeoff_template_revision"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("takeoff_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    default_waste_percent: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TakeoffRule(Base):
    __tablename__ = "takeoff_rules"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("takeoff_template_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    quantity_factor: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    apply_waste: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    assembly_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assembly_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assembly_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assembly_waste_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage_per_package: Mapped[float | None] = mapped_column(Float, nullable=True)
    assembly_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class EstimateTakeoff(Base):
    __tablename__ = "estimate_takeoffs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    estimate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("estimates.id", ondelete="CASCADE"), nullable=False, index=True)
    measurement_revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("measurement_revisions.id", ondelete="RESTRICT"), nullable=False, index=True)
    template_revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("takeoff_template_revisions.id", ondelete="RESTRICT"), nullable=False, index=True)
    measurement_revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    template_revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    company_default_waste_percent: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    template_waste_percent: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    estimate_waste_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    structure_waste_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    drip_edge_override_lf: Mapped[float | None] = mapped_column(Float, nullable=True)
    generated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EstimateTakeoffLine(Base):
    __tablename__ = "estimate_takeoff_lines"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    takeoff_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("estimate_takeoffs.id", ondelete="CASCADE"), nullable=False, index=True)
    estimate_line_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("estimate_line_items.id", ondelete="SET NULL"), nullable=True, index=True)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    metric_key: Mapped[str] = mapped_column(String(80), nullable=False)
    raw_metric_value: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    measured_quantity: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    applied_waste_percent: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    calculated_quantity: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    order_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
