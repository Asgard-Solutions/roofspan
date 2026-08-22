"""ABC Supply vendor catalog: local catalog cache, sync status, and Material ABC identity columns.

Revision ID: f1a9c4b7d3e2
Revises: d4a7b2c8e1f6
Create Date: 2026-06-22 00:00:00.000000

Additive-only. Adds the ABC vendor-catalog cache (abc_catalog_items), a singleton sync-status row
(abc_catalog_sync), and nullable vendor/ABC identity columns on the existing materials table. No
existing data is modified or removed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f1a9c4b7d3e2'
down_revision: Union[str, None] = 'd4a7b2c8e1f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'abc_catalog_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('abc_item_number', sa.String(length=64), nullable=False),
        sa.Column('description', sa.String(length=600), nullable=True),
        sa.Column('manufacturer', sa.String(length=255), nullable=True),
        sa.Column('brand', sa.String(length=255), nullable=True),
        sa.Column('category', sa.String(length=255), nullable=True),
        sa.Column('family_id', sa.String(length=64), nullable=True),
        sa.Column('family_name', sa.String(length=255), nullable=True),
        sa.Column('unit_of_measure', sa.String(length=32), nullable=True),
        sa.Column('uoms', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='active'),
        sa.Column('image_url', sa.String(length=600), nullable=True),
        sa.Column('is_dimensional', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('branch_numbers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('abc_last_modified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('raw_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('material_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['material_id'], ['materials.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_abc_catalog_items_abc_item_number', 'abc_catalog_items', ['abc_item_number'], unique=True)
    op.create_index('ix_abc_catalog_items_manufacturer', 'abc_catalog_items', ['manufacturer'])
    op.create_index('ix_abc_catalog_items_category', 'abc_catalog_items', ['category'])
    op.create_index('ix_abc_catalog_items_status', 'abc_catalog_items', ['status'])
    op.create_index('ix_abc_catalog_items_material_id', 'abc_catalog_items', ['material_id'])

    op.create_table(
        'abc_catalog_sync',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='never_synced'),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_full_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('items_synced', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_by', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )

    op.add_column('materials', sa.Column('vendor', sa.String(length=64), nullable=True))
    op.add_column('materials', sa.Column('abc_item_number', sa.String(length=64), nullable=True))
    op.add_column('materials', sa.Column('abc_catalog_item_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('materials', sa.Column('abc_uom', sa.String(length=32), nullable=True))
    op.add_column('materials', sa.Column('abc_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index('ix_materials_abc_item_number', 'materials', ['abc_item_number'])


def downgrade() -> None:
    op.drop_index('ix_materials_abc_item_number', table_name='materials')
    op.drop_column('materials', 'abc_metadata')
    op.drop_column('materials', 'abc_uom')
    op.drop_column('materials', 'abc_catalog_item_id')
    op.drop_column('materials', 'abc_item_number')
    op.drop_column('materials', 'vendor')
    op.drop_table('abc_catalog_sync')
    op.drop_index('ix_abc_catalog_items_material_id', table_name='abc_catalog_items')
    op.drop_index('ix_abc_catalog_items_status', table_name='abc_catalog_items')
    op.drop_index('ix_abc_catalog_items_category', table_name='abc_catalog_items')
    op.drop_index('ix_abc_catalog_items_manufacturer', table_name='abc_catalog_items')
    op.drop_index('ix_abc_catalog_items_abc_item_number', table_name='abc_catalog_items')
    op.drop_table('abc_catalog_items')
