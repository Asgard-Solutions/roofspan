"""roof measurement snapshot-revision model (Increment A)

Revision ID: b7c8d9e0f1a2
Revises: f2a3b4c5d6e7
Create Date: 2026-06-02

Adds the Roof Measurement model: MeasurementSet -> MeasurementRevision(n) ->
Structures / Facets / Edges / Penetrations / Summary. Each revision is an immutable snapshot once
verified/locked. Additive-only; no existing data is touched.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "b7c8d9e0f1a2"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "measurement_sets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("inspection_id", UUID(as_uuid=True), sa.ForeignKey("inspections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("property_id", UUID(as_uuid=True), sa.ForeignKey("properties.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_measurement_sets_inspection_id", "measurement_sets", ["inspection_id"])
    op.create_index("ix_measurement_sets_property_id", "measurement_sets", ["property_id"])
    op.create_index("ix_measurement_sets_lead_id", "measurement_sets", ["lead_id"])

    op.create_table(
        "measurement_revisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("set_id", UUID(as_uuid=True), sa.ForeignKey("measurement_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("supersedes_revision_id", UUID(as_uuid=True), nullable=True),
        sa.Column("is_immutable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="field"),
        sa.Column("provider", sa.String(length=255), nullable=True),
        sa.Column("report_id", sa.String(length=255), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reported_area_sqft", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("field_complete_by", sa.String(length=255), nullable=True),
        sa.Column("field_complete_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", sa.String(length=255), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_measurement_revisions_set_id", "measurement_revisions", ["set_id"])
    op.create_index("ix_measurement_revisions_status", "measurement_revisions", ["status"])

    op.create_table(
        "measurement_structures",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("revision_id", UUID(as_uuid=True), sa.ForeignKey("measurement_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("structure_type", sa.String(length=32), nullable=False, server_default="main_house"),
        sa.Column("stories", sa.Float(), nullable=True),
        sa.Column("approx_height_ft", sa.Float(), nullable=True),
        sa.Column("attachment", sa.String(length=16), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_measurement_structures_revision_id", "measurement_structures", ["revision_id"])

    op.create_table(
        "measurement_facets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("revision_id", UUID(as_uuid=True), sa.ForeignKey("measurement_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("structure_id", UUID(as_uuid=True), sa.ForeignKey("measurement_structures.id", ondelete="SET NULL"), nullable=True),
        sa.Column("facet_label", sa.String(length=24), nullable=False, server_default=""),
        sa.Column("pitch_rise", sa.Float(), nullable=True),
        sa.Column("area_sqft", sa.Float(), nullable=False, server_default="0"),
        sa.Column("width_ft", sa.Float(), nullable=True),
        sa.Column("length_ft", sa.Float(), nullable=True),
        sa.Column("orientation_azimuth", sa.Float(), nullable=True),
        sa.Column("roof_material", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("geometry", JSONB(), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_measurement_facets_revision_id", "measurement_facets", ["revision_id"])
    op.create_index("ix_measurement_facets_structure_id", "measurement_facets", ["structure_id"])

    op.create_table(
        "measurement_edges",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("revision_id", UUID(as_uuid=True), sa.ForeignKey("measurement_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("edge_type", sa.String(length=24), nullable=False, server_default="eave"),
        sa.Column("length_ft", sa.Float(), nullable=False, server_default="0"),
        sa.Column("facet_id", UUID(as_uuid=True), sa.ForeignKey("measurement_facets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("facet_id_secondary", UUID(as_uuid=True), sa.ForeignKey("measurement_facets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("label", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_measurement_edges_revision_id", "measurement_edges", ["revision_id"])

    op.create_table(
        "measurement_penetrations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("revision_id", UUID(as_uuid=True), sa.ForeignKey("measurement_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("facet_id", UUID(as_uuid=True), sa.ForeignKey("measurement_facets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pen_type", sa.String(length=24), nullable=False, server_default="pipe_boot"),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("diameter_in", sa.Float(), nullable=True),
        sa.Column("width_in", sa.Float(), nullable=True),
        sa.Column("length_in", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_measurement_penetrations_revision_id", "measurement_penetrations", ["revision_id"])

    op.create_table(
        "measurement_summaries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("revision_id", UUID(as_uuid=True), sa.ForeignKey("measurement_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("existing_covering_type", sa.String(length=64), nullable=True),
        sa.Column("existing_layers", sa.Integer(), nullable=True),
        sa.Column("existing_underlayment", sa.String(length=64), nullable=True),
        sa.Column("tearoff_notes", sa.Text(), nullable=True),
        sa.Column("deck_type", sa.String(length=64), nullable=True),
        sa.Column("deck_thickness_in", sa.Float(), nullable=True),
        sa.Column("damaged_deck_sf", sa.Float(), nullable=True),
        sa.Column("replacement_sheets", sa.Integer(), nullable=True),
        sa.Column("full_redeck", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("decking_notes", sa.Text(), nullable=True),
        sa.Column("ridge_vent_lf", sa.Float(), nullable=True),
        sa.Column("intake_soffit_vent_lf", sa.Float(), nullable=True),
        sa.Column("ventilation_notes", sa.Text(), nullable=True),
        sa.Column("gutter_lf", sa.Float(), nullable=True),
        sa.Column("gutter_size", sa.String(length=32), nullable=True),
        sa.Column("gutter_type", sa.String(length=32), nullable=True),
        sa.Column("downspout_count", sa.Integer(), nullable=True),
        sa.Column("downspout_lf", sa.Float(), nullable=True),
        sa.Column("gutter_guard_lf", sa.Float(), nullable=True),
        sa.Column("gutter_notes", sa.Text(), nullable=True),
        sa.Column("stories", sa.Float(), nullable=True),
        sa.Column("steep_access", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("high_access", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("long_carry", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("restricted_access", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("landscaping_protection", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("conditions_notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_measurement_summaries_revision_id", "measurement_summaries", ["revision_id"], unique=True)


def downgrade() -> None:
    for t in ["measurement_summaries", "measurement_penetrations", "measurement_edges",
              "measurement_facets", "measurement_structures", "measurement_revisions", "measurement_sets"]:
        op.drop_table(t)
