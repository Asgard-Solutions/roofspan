"""Supplier Framework hardening — DB invariant: one active preferred SupplierMaterial per material.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-25 00:00:00.000000

Migration-safe. Before creating a PostgreSQL PARTIAL UNIQUE INDEX enforcing at most one
(is_preferred AND active) mapping per material, it first resolves any existing duplicates WITHOUT
deleting data: for each material it retains the earliest-created preferred mapping and unsets the
rest. A NOTICE reports how many rows were corrected.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Resolve duplicates deterministically (keep earliest created_at, then id). No deletes.
    op.execute("""
    DO $$
    DECLARE corrected integer;
    BEGIN
        WITH ranked AS (
            SELECT id, row_number() OVER (PARTITION BY material_id ORDER BY created_at ASC, id ASC) AS rn
            FROM supplier_materials
            WHERE is_preferred = true AND active = true
        )
        UPDATE supplier_materials sm
        SET is_preferred = false, updated_at = now()
        FROM ranked r
        WHERE sm.id = r.id AND r.rn > 1;
        GET DIAGNOSTICS corrected = ROW_COUNT;
        IF corrected > 0 THEN
            RAISE NOTICE 'preferred-supplier invariant: corrected % duplicate preferred mapping(s)', corrected;
        END IF;
    END $$;
    """)
    # 2) Enforce at the database level.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_supplier_materials_one_active_preferred
        ON supplier_materials (material_id)
        WHERE is_preferred = true AND active = true;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_supplier_materials_one_active_preferred;")
