"""estimating modernization: line cost model, assemblies, price books, quote packages

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06

Additive-only. Preserves all existing estimates/quotes. Backfills:
  estimate_line_items.selling_unit_price = unit_price, measured_quantity = quantity.
Seeds one neutral default price book ("Standard", 0% markup).
"""
from typing import Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def _col(table, *cols):
    for c in cols:
        op.add_column(table, c)


def upgrade() -> None:
    # ---- estimate_line_items: catalog + cost + waste + markup + snapshot + assembly ----
    _col("estimate_line_items",
         sa.Column("material_id", UUID(as_uuid=True), sa.ForeignKey("materials.id", ondelete="SET NULL"), nullable=True),
         sa.Column("supplier_material_id", UUID(as_uuid=True), sa.ForeignKey("supplier_materials.id", ondelete="SET NULL"), nullable=True),
         sa.Column("line_kind", sa.String(24), nullable=False, server_default="custom"),
         sa.Column("base_cost", sa.Float(), nullable=False, server_default="0"),
         sa.Column("material_cost", sa.Float(), nullable=False, server_default="0"),
         sa.Column("labor_cost", sa.Float(), nullable=False, server_default="0"),
         sa.Column("equipment_cost", sa.Float(), nullable=False, server_default="0"),
         sa.Column("subcontract_cost", sa.Float(), nullable=False, server_default="0"),
         sa.Column("measured_quantity", sa.Float(), nullable=False, server_default="0"),
         sa.Column("waste_percent", sa.Float(), nullable=False, server_default="0"),
         sa.Column("order_quantity", sa.Float(), nullable=True),
         sa.Column("purchase_unit", sa.String(32), nullable=True),
         sa.Column("conversion_factor", sa.Float(), nullable=True),
         sa.Column("markup_percent", sa.Float(), nullable=False, server_default="0"),
         sa.Column("selling_unit_price", sa.Float(), nullable=False, server_default="0"),
         sa.Column("cost_source_supplier_id", UUID(as_uuid=True), nullable=True),
         sa.Column("cost_source_supplier_name", sa.String(255), nullable=True),
         sa.Column("supplier_item_number", sa.String(64), nullable=True),
         sa.Column("cost_source", sa.String(24), nullable=True),
         sa.Column("cost_snapshot_at", sa.DateTime(timezone=True), nullable=True),
         sa.Column("assembly_id", UUID(as_uuid=True), nullable=True),
         sa.Column("assembly_version", sa.Integer(), nullable=True),
         sa.Column("assembly_name", sa.String(255), nullable=True))
    op.create_index("ix_estimate_line_items_material_id", "estimate_line_items", ["material_id"])
    # backfill legacy lines: selling price = unit_price, measured = quantity, material_cost stays 0
    op.execute("UPDATE estimate_line_items SET selling_unit_price = unit_price WHERE selling_unit_price = 0")
    op.execute("UPDATE estimate_line_items SET measured_quantity = quantity WHERE measured_quantity = 0")

    # ---- quotes: packages ----
    _col("quotes",
         sa.Column("multi_package", sa.Boolean(), nullable=False, server_default=sa.false()),
         sa.Column("accepted_package_id", UUID(as_uuid=True), nullable=True))

    # ---- quote_packages ----
    op.create_table(
        "quote_packages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("quote_id", UUID(as_uuid=True), sa.ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(64), nullable=False, server_default=""),
        sa.Column("tier", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subtotal", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tax", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )

    # ---- quote_line_items: package + internal cost snapshot ----
    _col("quote_line_items",
         sa.Column("package_id", UUID(as_uuid=True), sa.ForeignKey("quote_packages.id", ondelete="CASCADE"), nullable=True),
         sa.Column("material_id", UUID(as_uuid=True), nullable=True),
         sa.Column("total_unit_cost", sa.Float(), nullable=False, server_default="0"),
         sa.Column("markup_percent", sa.Float(), nullable=False, server_default="0"))
    op.create_index("ix_quote_line_items_package_id", "quote_line_items", ["package_id"])

    # ---- assemblies ----
    op.create_table(
        "assemblies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("unit_basis", sa.String(32), nullable=False, server_default="SQ"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_assemblies_name", "assemblies", ["name"])
    op.create_table(
        "assembly_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("assembly_id", UUID(as_uuid=True), sa.ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("material_id", UUID(as_uuid=True), sa.ForeignKey("materials.id", ondelete="SET NULL"), nullable=True),
        sa.Column("description", sa.String(400), nullable=False, server_default=""),
        sa.Column("quantity_factor", sa.Float(), nullable=False, server_default="1"),
        sa.Column("unit", sa.String(32), nullable=False, server_default="ea"),
        sa.Column("waste_override", sa.Float(), nullable=True),
        sa.Column("is_labor", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )

    # ---- price_books ----
    op.create_table(
        "price_books",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("uq_price_books_one_default", "price_books", ["is_default"],
                    unique=True, postgresql_where=sa.text("is_default AND active"))
    op.create_table(
        "price_book_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("price_book_id", UUID(as_uuid=True), sa.ForeignKey("price_books.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("target_type", sa.String(24), nullable=False, server_default="material"),
        sa.Column("material_id", UUID(as_uuid=True), sa.ForeignKey("materials.id", ondelete="CASCADE"), nullable=True),
        sa.Column("assembly_id", UUID(as_uuid=True), sa.ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=True),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("rule_type", sa.String(16), nullable=False, server_default="markup"),
        sa.Column("fixed_price", sa.Float(), nullable=True),
        sa.Column("markup_percent", sa.Float(), nullable=True),
        sa.Column("margin_percent", sa.Float(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    # seed one neutral default price book
    op.execute(sa.text(
        "INSERT INTO price_books (id, name, description, active, is_default, created_at, updated_at) "
        "VALUES (CAST(:id AS uuid), 'Standard', 'Default price book', true, true, now(), now())"
    ).bindparams(id=str(uuid.uuid4())))


def downgrade() -> None:
    op.drop_table("price_book_entries")
    op.drop_index("uq_price_books_one_default", table_name="price_books")
    op.drop_table("price_books")
    op.drop_table("assembly_items")
    op.drop_index("ix_assemblies_name", table_name="assemblies")
    op.drop_table("assemblies")
    op.drop_index("ix_quote_line_items_package_id", table_name="quote_line_items")
    for c in ("markup_percent", "total_unit_cost", "material_id", "package_id"):
        op.drop_column("quote_line_items", c)
    op.drop_table("quote_packages")
    for c in ("accepted_package_id", "multi_package"):
        op.drop_column("quotes", c)
    op.drop_index("ix_estimate_line_items_material_id", table_name="estimate_line_items")
    for c in ("assembly_name", "assembly_version", "assembly_id", "cost_snapshot_at", "cost_source",
              "supplier_item_number", "cost_source_supplier_name", "cost_source_supplier_id",
              "selling_unit_price", "markup_percent", "conversion_factor", "purchase_unit",
              "order_quantity", "waste_percent", "measured_quantity", "subcontract_cost",
              "equipment_cost", "labor_cost", "material_cost", "base_cost", "line_kind",
              "supplier_material_id", "material_id"):
        op.drop_column("estimate_line_items", c)
