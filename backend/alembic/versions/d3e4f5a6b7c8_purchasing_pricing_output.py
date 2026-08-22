"""purchasing/pricing/output completion: PO status history + estimate price-book snapshot

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-06

Additive-only. New `po_status_history` table (real status events; seeds ONE current-state baseline
event per existing PO, source='imported'). Estimate gains `price_book_id`; estimate lines gain the
applied price-book rule snapshot columns.
"""
from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "po_status_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("purchase_order_id", UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("normalized_status", sa.String(32), nullable=False),
        sa.Column("provider_status", sa.String(48), nullable=True),
        sa.Column("source", sa.String(24), nullable=False, server_default="roofspan"),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column("estimates", sa.Column("price_book_id", UUID(as_uuid=True), sa.ForeignKey("price_books.id", ondelete="SET NULL"), nullable=True))
    op.add_column("estimate_line_items", sa.Column("applied_price_book_id", UUID(as_uuid=True), nullable=True))
    op.add_column("estimate_line_items", sa.Column("applied_price_rule_type", sa.String(16), nullable=True))
    op.add_column("estimate_line_items", sa.Column("applied_price_rule_value", sa.Float(), nullable=True))

    # Seed a single current-state baseline event per existing PO (source='imported' — NOT backdated).
    op.execute(sa.text(
        "INSERT INTO po_status_history (id, purchase_order_id, normalized_status, provider_status, source, note, created_at) "
        "SELECT gen_random_uuid(), p.id, COALESCE(p.status,'draft'), p.abc_order_status, 'imported', "
        "'Imported current-state baseline', now() FROM purchase_orders p"
    ))


def downgrade() -> None:
    op.drop_column("estimate_line_items", "applied_price_rule_value")
    op.drop_column("estimate_line_items", "applied_price_rule_type")
    op.drop_column("estimate_line_items", "applied_price_book_id")
    op.drop_column("estimates", "price_book_id")
    op.drop_table("po_status_history")
