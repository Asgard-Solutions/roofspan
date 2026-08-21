"""ABC Supply integration P2: PO line + PO header ABC metadata

Revision ID: b2d5e7c9a1f3
Revises: a7c3f1b9d2e4
Create Date: 2026-06-16 00:00:00.000000

Additive-only, all nullable. Generic (non-ABC) purchase orders and receiving are unaffected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b2d5e7c9a1f3'
down_revision: Union[str, None] = 'a7c3f1b9d2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('purchase_orders', sa.Column('integration_provider', sa.String(length=32), nullable=True))
    op.add_column('purchase_orders', sa.Column('abc_ship_to_number', sa.String(length=64), nullable=True))
    op.add_column('purchase_orders', sa.Column('abc_branch_number', sa.String(length=64), nullable=True))

    op.add_column('po_line_items', sa.Column('integration_provider', sa.String(length=32), nullable=True))
    op.add_column('po_line_items', sa.Column('abc_item_number', sa.String(length=64), nullable=True))
    op.add_column('po_line_items', sa.Column('abc_branch_number', sa.String(length=64), nullable=True))
    op.add_column('po_line_items', sa.Column('abc_ship_to_number', sa.String(length=64), nullable=True))
    op.add_column('po_line_items', sa.Column('abc_uom', sa.String(length=32), nullable=True))
    op.add_column('po_line_items', sa.Column('abc_variation', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('po_line_items', sa.Column('abc_price', sa.Float(), nullable=True))
    op.add_column('po_line_items', sa.Column('abc_price_status', sa.String(length=24), nullable=True))
    op.add_column('po_line_items', sa.Column('abc_price_timestamp', sa.DateTime(timezone=True), nullable=True))
    op.add_column('po_line_items', sa.Column('abc_product_description', sa.String(length=400), nullable=True))
    op.add_column('po_line_items', sa.Column('abc_product_family', sa.String(length=255), nullable=True))
    op.add_column('po_line_items', sa.Column('abc_product_image_url', sa.String(length=600), nullable=True))
    op.add_column('po_line_items', sa.Column('pricing_source', sa.String(length=16), nullable=True))


def downgrade() -> None:
    for col in ['pricing_source', 'abc_product_image_url', 'abc_product_family', 'abc_product_description',
                'abc_price_timestamp', 'abc_price_status', 'abc_price', 'abc_variation', 'abc_uom',
                'abc_ship_to_number', 'abc_branch_number', 'abc_item_number', 'integration_provider']:
        op.drop_column('po_line_items', col)
    for col in ['abc_branch_number', 'abc_ship_to_number', 'integration_provider']:
        op.drop_column('purchase_orders', col)
