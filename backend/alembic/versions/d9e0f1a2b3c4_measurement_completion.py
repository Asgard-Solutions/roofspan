"""roof measurement completion extension

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-08-27

Adds revision-scoped completion fields without rewriting the Increment A measurement tables.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "measurement_revision_extensions",
        sa.Column(
            "revision_id",
            UUID(as_uuid=True),
            sa.ForeignKey("measurement_revisions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("structure_scope", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("existing_condition", sa.String(64), nullable=True),
        sa.Column("drip_edge_lf", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("measurement_revision_extensions")
