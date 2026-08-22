"""Inventory Core 2.0 — Slice 1: master material fields, generic SupplierMaterial mapping, ABC backfill.

Revision ID: a1b2c3d4e5f6
Revises: f1a9c4b7d3e2
Create Date: 2026-06-24 00:00:00.000000

Additive + data backfill. Adds supplier-independent master fields to `materials`, a generic
`supplier_materials` mapping table, and an `integration_provider` column on `suppliers`. Backfills:
- an "ABC Supply" supplier row (if missing)
- a preferred ABC SupplierMaterial row for every material already linked to ABC (abc_item_number set)
No existing data is removed; legacy Material.abc_* columns are retained for backward compatibility.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f1a9c4b7d3e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- master material fields ----
    op.add_column('materials', sa.Column('manufacturer', sa.String(length=255), nullable=True))
    op.add_column('materials', sa.Column('brand', sa.String(length=255), nullable=True))
    op.add_column('materials', sa.Column('product_family', sa.String(length=255), nullable=True))
    op.add_column('materials', sa.Column('subcategory', sa.String(length=128), nullable=True))
    op.add_column('materials', sa.Column('color', sa.String(length=128), nullable=True))
    op.add_column('materials', sa.Column('size_variant', sa.String(length=128), nullable=True))
    op.add_column('materials', sa.Column('purchase_unit', sa.String(length=32), nullable=True))
    op.add_column('materials', sa.Column('conversion_factor', sa.Float(), nullable=False, server_default='1'))
    op.add_column('materials', sa.Column('coverage_amount', sa.Float(), nullable=True))
    op.add_column('materials', sa.Column('coverage_unit', sa.String(length=32), nullable=True))
    op.add_column('materials', sa.Column('weight', sa.Float(), nullable=True))
    op.add_column('materials', sa.Column('upc', sa.String(length=64), nullable=True))
    op.add_column('materials', sa.Column('manufacturer_part_number', sa.String(length=128), nullable=True))
    op.add_column('materials', sa.Column('taxable', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('materials', sa.Column('image_url', sa.String(length=600), nullable=True))

    op.add_column('suppliers', sa.Column('integration_provider', sa.String(length=32), nullable=True))

    # ---- supplier_materials ----
    op.create_table(
        'supplier_materials',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('material_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('supplier_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('integration_provider', sa.String(length=32), nullable=True),
        sa.Column('external_item_id', sa.String(length=128), nullable=True),
        sa.Column('supplier_item_number', sa.String(length=64), nullable=True),
        sa.Column('supplier_description', sa.String(length=600), nullable=True),
        sa.Column('supplier_uom', sa.String(length=32), nullable=True),
        sa.Column('conversion_factor', sa.Float(), nullable=False, server_default='1'),
        sa.Column('manufacturer_part_number', sa.String(length=128), nullable=True),
        sa.Column('branch_context', sa.String(length=64), nullable=True),
        sa.Column('current_cost', sa.Float(), nullable=True),
        sa.Column('price_status', sa.String(length=24), nullable=True),
        sa.Column('price_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('availability_status', sa.String(length=24), nullable=True),
        sa.Column('availability_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lead_time_days', sa.Integer(), nullable=True),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_preferred', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['material_id'], ['materials.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_supplier_materials_material_id', 'supplier_materials', ['material_id'])
    op.create_index('ix_supplier_materials_supplier_id', 'supplier_materials', ['supplier_id'])

    # ---- backfill ABC supplier + mappings ----
    op.execute("""
        INSERT INTO suppliers (id, name, active, integration_provider, created_at)
        SELECT gen_random_uuid(), 'ABC Supply', true, 'abc_supply', now()
        WHERE NOT EXISTS (SELECT 1 FROM suppliers WHERE name = 'ABC Supply');
    """)
    op.execute("UPDATE suppliers SET integration_provider = 'abc_supply' WHERE name = 'ABC Supply' AND integration_provider IS NULL;")
    op.execute("""
        INSERT INTO supplier_materials
            (id, material_id, supplier_id, integration_provider, external_item_id, supplier_item_number,
             supplier_description, supplier_uom, conversion_factor, current_cost, availability_status,
             meta, is_preferred, active, created_at, updated_at)
        SELECT gen_random_uuid(), m.id,
               (SELECT id FROM suppliers WHERE name = 'ABC Supply' LIMIT 1),
               'abc_supply', m.abc_item_number, m.abc_item_number,
               m.description, m.abc_uom, 1, NULL, NULL,
               m.abc_metadata, true, true, now(), now()
        FROM materials m
        WHERE m.abc_item_number IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM supplier_materials sm
              WHERE sm.material_id = m.id AND sm.integration_provider = 'abc_supply'
          );
    """)


def downgrade() -> None:
    op.drop_index('ix_supplier_materials_supplier_id', table_name='supplier_materials')
    op.drop_index('ix_supplier_materials_material_id', table_name='supplier_materials')
    op.drop_table('supplier_materials')
    op.drop_column('suppliers', 'integration_provider')
    for col in ('image_url', 'taxable', 'manufacturer_part_number', 'upc', 'weight', 'coverage_unit',
                'coverage_amount', 'conversion_factor', 'purchase_unit', 'size_variant', 'color',
                'subcategory', 'product_family', 'brand', 'manufacturer'):
        op.drop_column('materials', col)
