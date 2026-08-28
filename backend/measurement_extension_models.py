"""Additive persistence for roof-measurement completion fields.

The original Increment A tables remain unchanged. These fields are revision-scoped so historical
measurement snapshots stay immutable and backward compatible while Field/Office receive one unified
measurement document from the service layer.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


def _now():
    return datetime.now(timezone.utc)


class MeasurementRevisionExtension(Base):
    __tablename__ = "measurement_revision_extensions"

    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("measurement_revisions.id", ondelete="CASCADE"), primary_key=True
    )
    # structure UUID string -> include/exclude from estimate/takeoff scope. Missing entries mean True.
    structure_scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    existing_condition: Mapped[str | None] = mapped_column(String(64), nullable=True)
    drip_edge_lf: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
