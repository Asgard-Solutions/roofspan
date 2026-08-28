"""Roof sketch persistence (Plan 1 Task 2).

One versioned canonical sketch JSON document per (measurement revision, structure). The relational
measurement facets/edges/penetrations remain authoritative; sketch-derived values stay proposals.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


def _now():
    return datetime.now(timezone.utc)


class MeasurementSketchDocument(Base):
    __tablename__ = "measurement_sketch_documents"
    __table_args__ = (
        UniqueConstraint("revision_id", "structure_id", name="uq_measurement_sketch_revision_structure"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("measurement_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    structure_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("measurement_structures.id", ondelete="CASCADE"), nullable=False, index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    document_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # optimistic concurrency token
    edit_mode: Mapped[str] = mapped_column(String(24), default="connected_graph", nullable=False)
    document: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
