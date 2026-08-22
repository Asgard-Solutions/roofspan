"""Supplier Framework — expand suppliers + supplier_price_history.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-26 00:00:00.000000

Additive-only. Expands `suppliers` with contact/terms/integration metadata (all nullable) and adds an
immutable `supplier_price_history` table. Backfills integration_status='manual' for non-ABC suppliers
and 'connected' hint left NULL for ABC (status derived at runtime).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for col, type_ in (
        ('integration_status', sa.String(length=24)), ('supplier_type', sa.String(length=48)),
        ('account_number', sa.String(length=64)), ('sales_rep', sa.String(length=255)),
        ('ordering_email', sa.String(length=255)), ('website', sa.String(length=255)),
        ('payment_terms', sa.String(length=128)), ('default_branch', sa.String(length=64)),
        ('delivery_terms', sa.String(length=128)), ('freight_notes', sa.Text()), ('tax_notes', sa.Text()),
    ):
        op.add_column('suppliers', sa.Column(col, type_, nullable=True))
    op.add_column('suppliers', sa.Column('minimum_order', sa.Float(), nullable=True))
    op.add_column('suppliers', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')))

    op.execute("UPDATE suppliers SET integration_status = 'manual', supplier_type = COALESCE(supplier_type,'manual') WHERE integration_provider IS NULL;")
    op.execute("UPDATE suppliers SET supplier_type = COALESCE(supplier_type,'distributor') WHERE integration_provider = 'abc_supply';")

    op.create_table(
        'supplier_price_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('supplier_material_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('supplier_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('material_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('branch_context', sa.String(length=64), nullable=True),
        sa.Column('cost', sa.Float(), nullable=True),
        sa.Column('source', sa.String(length=24), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['supplier_material_id'], ['supplier_materials.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_supplier_price_history_sm', 'supplier_price_history', ['supplier_material_id'])
    op.create_index('ix_supplier_price_history_material', 'supplier_price_history', ['material_id'])


def downgrade() -> None:
    op.drop_index('ix_supplier_price_history_material', table_name='supplier_price_history')
    op.drop_index('ix_supplier_price_history_sm', table_name='supplier_price_history')
    op.drop_table('supplier_price_history')
    for col in ('updated_at', 'minimum_order', 'tax_notes', 'freight_notes', 'delivery_terms', 'default_branch',
                'payment_terms', 'website', 'ordering_email', 'sales_rep', 'account_number', 'supplier_type',
                'integration_status'):
        op.drop_column('suppliers', col)
