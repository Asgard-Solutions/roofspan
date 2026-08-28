"""measurement sketches (Plan 1)

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-06-02

Additive: one versioned canonical sketch document per (measurement revision, structure).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "measurement_sketch_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("revision_id", UUID(as_uuid=True), sa.ForeignKey("measurement_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("structure_id", UUID(as_uuid=True), sa.ForeignKey("measurement_structures.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("document_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("edit_mode", sa.String(length=24), nullable=False, server_default="connected_graph"),
        sa.Column("document", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("revision_id", "structure_id", name="uq_measurement_sketch_revision_structure"),
    )
    op.create_index("ix_measurement_sketch_documents_revision_id", "measurement_sketch_documents", ["revision_id"])
    op.create_index("ix_measurement_sketch_documents_structure_id", "measurement_sketch_documents", ["structure_id"])


def downgrade() -> None:
    op.drop_table("measurement_sketch_documents")
