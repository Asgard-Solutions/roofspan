"""actual job costing (batch 2): manual actual-cost entries + immutable job cost snapshots

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-06

Additive-only. New tables `actual_cost_entries` (manual non-material costs) and `job_cost_snapshots`
(immutable estimated-vs-actual snapshot at job completion). All money columns NUMERIC.
"""
from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "actual_cost_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("description", sa.String(400), nullable=False, server_default=""),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=True),
        sa.Column("unit_rate", sa.Numeric(14, 4), nullable=True),
        sa.Column("incurred_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "job_cost_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("job_number", sa.String(32), nullable=True),
        sa.Column("trigger", sa.String(24), nullable=False, server_default="completion"),
        sa.Column("baseline_status", sa.String(24), nullable=True),
        sa.Column("costing_status", sa.String(32), nullable=True),
        sa.Column("revenue", sa.Numeric(14, 4), nullable=True),
        sa.Column("estimated_total_cost", sa.Numeric(14, 4), nullable=True),
        sa.Column("actual_total_cost", sa.Numeric(14, 4), nullable=True),
        sa.Column("estimated_gross_profit", sa.Numeric(14, 4), nullable=True),
        sa.Column("actual_gross_profit", sa.Numeric(14, 4), nullable=True),
        sa.Column("actual_gross_margin_percent", sa.Numeric(9, 4), nullable=True),
        sa.Column("total_variance", sa.Numeric(14, 4), nullable=True),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("job_cost_snapshots")
    op.drop_table("actual_cost_entries")
