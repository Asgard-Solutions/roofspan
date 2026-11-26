"""Lead follow-ups, scheduled inspections, one shared lead status list.

Lead statuses become New / Contacted / Qualified / Won / Lost (+ archived, Field soft-archive):
working -> contacted, interested -> qualified, converted -> won.

Revision ID: b1f0c2d3e4a5
Revises: a9c8e7d6f5b4
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b1f0c2d3e4a5"
down_revision = "a9c8e7d6f5b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_follow_ups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="call"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_lead_follow_ups_lead_id", "lead_follow_ups", ["lead_id"])
    op.create_index("ix_lead_follow_ups_due_at", "lead_follow_ups", ["due_at"])
    op.create_index("ix_lead_follow_ups_status", "lead_follow_ups", ["status"])
    op.add_column("inspections", sa.Column("status", sa.String(length=16), nullable=False, server_default="completed"))
    op.create_index("ix_inspections_status", "inspections", ["status"])
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE leads SET status='contacted' WHERE status='working'"))
    conn.execute(sa.text("UPDATE leads SET status='qualified' WHERE status='interested'"))
    conn.execute(sa.text("UPDATE leads SET status='won' WHERE status='converted'"))


def downgrade() -> None:
    op.drop_index("ix_inspections_status", table_name="inspections")
    op.drop_column("inspections", "status")
    op.drop_table("lead_follow_ups")
