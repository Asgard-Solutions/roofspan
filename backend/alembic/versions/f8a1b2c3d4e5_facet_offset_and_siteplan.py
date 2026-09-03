"""facet position_offset_ft + revision site_plan

Revision ID: f8a1b2c3d4e5
Revises: e0f1a2b3c4d5
Create Date: 2026-06

Adds:
- measurement_facets.position_offset_ft (optional distance along the host slope to pin a dormer/wing).
- measurement_revisions.site_plan (JSONB) storing the combined multi-structure site-plan layout offsets.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "f8a1b2c3d4e5"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("measurement_facets", sa.Column("position_offset_ft", sa.Float(), nullable=True))
    op.add_column("measurement_revisions", sa.Column("site_plan", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("measurement_revisions", "site_plan")
    op.drop_column("measurement_facets", "position_offset_ft")
