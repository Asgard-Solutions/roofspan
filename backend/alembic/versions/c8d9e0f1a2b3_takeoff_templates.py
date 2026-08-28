"""versioned takeoff templates and estimate takeoff provenance

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-08-27

Additive-only Increment B/C schema. Physical measurement tables remain unchanged. A database trigger
locks the latest takeoff's measurement snapshot when its quote is accepted, so every acceptance path
preserves the exact physical measurement revision used for the estimate.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "takeoff_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_takeoff_templates_name", "takeoff_templates", ["name"])
    op.create_index("ix_takeoff_templates_active", "takeoff_templates", ["active"])

    op.create_table(
        "takeoff_template_revisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("takeoff_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("default_waste_percent", sa.Float(), nullable=False, server_default="10"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("template_id", "revision_number", name="uq_takeoff_template_revision"),
    )
    op.create_index("ix_takeoff_template_revisions_template_id", "takeoff_template_revisions", ["template_id"])

    op.create_table(
        "takeoff_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("template_revision_id", UUID(as_uuid=True), sa.ForeignKey("takeoff_template_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("metric_key", sa.String(80), nullable=False),
        sa.Column("quantity_factor", sa.Float(), nullable=False, server_default="1"),
        sa.Column("apply_waste", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("assembly_id", UUID(as_uuid=True), nullable=True),
        sa.Column("assembly_version", sa.Integer(), nullable=True),
        sa.Column("assembly_name", sa.String(255), nullable=True),
        sa.Column("assembly_waste_percent", sa.Float(), nullable=True),
        sa.Column("coverage_per_package", sa.Float(), nullable=True),
        sa.Column("assembly_snapshot", JSONB(), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_takeoff_rules_template_revision_id", "takeoff_rules", ["template_revision_id"])
    op.create_index("ix_takeoff_rules_metric_key", "takeoff_rules", ["metric_key"])

    op.create_table(
        "estimate_takeoffs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("estimate_id", UUID(as_uuid=True), sa.ForeignKey("estimates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("measurement_revision_id", UUID(as_uuid=True), sa.ForeignKey("measurement_revisions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("template_revision_id", UUID(as_uuid=True), sa.ForeignKey("takeoff_template_revisions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("measurement_revision_number", sa.Integer(), nullable=False),
        sa.Column("template_revision_number", sa.Integer(), nullable=False),
        sa.Column("company_default_waste_percent", sa.Float(), nullable=False, server_default="10"),
        sa.Column("template_waste_percent", sa.Float(), nullable=False, server_default="10"),
        sa.Column("estimate_waste_override", sa.Float(), nullable=True),
        sa.Column("structure_waste_overrides", JSONB(), nullable=True),
        sa.Column("drip_edge_override_lf", sa.Float(), nullable=True),
        sa.Column("generated_by", sa.String(255), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_estimate_takeoffs_estimate_id", "estimate_takeoffs", ["estimate_id"])
    op.create_index("ix_estimate_takeoffs_measurement_revision_id", "estimate_takeoffs", ["measurement_revision_id"])
    op.create_index("ix_estimate_takeoffs_template_revision_id", "estimate_takeoffs", ["template_revision_id"])

    op.create_table(
        "estimate_takeoff_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("takeoff_id", UUID(as_uuid=True), sa.ForeignKey("estimate_takeoffs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("estimate_line_item_id", UUID(as_uuid=True), sa.ForeignKey("estimate_line_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rule_id", UUID(as_uuid=True), nullable=True),
        sa.Column("metric_key", sa.String(80), nullable=False),
        sa.Column("raw_metric_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("measured_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("applied_waste_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("calculated_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("order_quantity", sa.Float(), nullable=True),
        sa.Column("provenance", JSONB(), nullable=True),
    )
    op.create_index("ix_estimate_takeoff_lines_takeoff_id", "estimate_takeoff_lines", ["takeoff_id"])
    op.create_index("ix_estimate_takeoff_lines_estimate_line_item_id", "estimate_takeoff_lines", ["estimate_line_item_id"])

    op.execute("""
        CREATE OR REPLACE FUNCTION roofspan_lock_takeoff_measurement_on_quote_accept()
        RETURNS trigger AS $$
        DECLARE selected_revision uuid;
        BEGIN
            IF NEW.status = 'accepted' AND (OLD.status IS DISTINCT FROM NEW.status) AND NEW.estimate_id IS NOT NULL THEN
                SELECT et.measurement_revision_id INTO selected_revision
                FROM estimate_takeoffs et
                WHERE et.estimate_id = NEW.estimate_id
                ORDER BY et.generated_at DESC, et.id DESC
                LIMIT 1;

                IF selected_revision IS NOT NULL THEN
                    UPDATE measurement_revisions
                    SET status = 'locked', is_immutable = TRUE,
                        locked_by = COALESCE(NEW.accepted_by, 'quote-acceptance'),
                        locked_at = COALESCE(NEW.accepted_at, now()), updated_at = now()
                    WHERE id = selected_revision AND is_immutable = FALSE;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_lock_takeoff_measurement_on_quote_accept
        AFTER UPDATE OF status ON quotes
        FOR EACH ROW EXECUTE FUNCTION roofspan_lock_takeoff_measurement_on_quote_accept();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_lock_takeoff_measurement_on_quote_accept ON quotes")
    op.execute("DROP FUNCTION IF EXISTS roofspan_lock_takeoff_measurement_on_quote_accept()")
    op.drop_table("estimate_takeoff_lines")
    op.drop_table("estimate_takeoffs")
    op.drop_table("takeoff_rules")
    op.drop_table("takeoff_template_revisions")
    op.drop_table("takeoff_templates")
