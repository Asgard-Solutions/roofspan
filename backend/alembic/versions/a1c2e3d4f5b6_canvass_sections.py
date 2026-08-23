"""canvass sections + section property membership

Revision ID: a1c2e3d4f5b6
Revises: f7a8b9c0d1e2
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "a1c2e3d4f5b6"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "canvass_sections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("territory_id", UUID(as_uuid=True), sa.ForeignKey("territories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("color", sa.String(16), nullable=False, server_default="#2563EB"),
        sa.Column("geometry", JSONB, nullable=False),
        sa.Column("assigned_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_canvass_sections_territory_id", "canvass_sections", ["territory_id"])
    op.create_index("ix_canvass_sections_assigned_user_id", "canvass_sections", ["assigned_user_id"])
    op.create_index("ix_canvass_sections_active", "canvass_sections", ["active"])

    op.create_table(
        "canvass_section_properties",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("section_id", UUID(as_uuid=True), sa.ForeignKey("canvass_sections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_id", UUID(as_uuid=True), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("section_id", "property_id", name="uq_canvass_section_property"),
    )
    op.create_index("ix_canvass_section_properties_section_id", "canvass_section_properties", ["section_id"])
    op.create_index("ix_canvass_section_properties_property_id", "canvass_section_properties", ["property_id"])


def downgrade():
    op.drop_index("ix_canvass_section_properties_property_id", table_name="canvass_section_properties")
    op.drop_index("ix_canvass_section_properties_section_id", table_name="canvass_section_properties")
    op.drop_table("canvass_section_properties")
    op.drop_index("ix_canvass_sections_active", table_name="canvass_sections")
    op.drop_index("ix_canvass_sections_assigned_user_id", table_name="canvass_sections")
    op.drop_index("ix_canvass_sections_territory_id", table_name="canvass_sections")
    op.drop_table("canvass_sections")
