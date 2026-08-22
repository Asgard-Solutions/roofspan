"""Inventory Core 2.0 — Slice 2: inventory_txns job_id + location (structured ledger).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-24 01:00:00.000000

Additive-only. Adds optional job reference and location to inventory transactions so structured
transaction types (job_reservation/job_issue/etc.) can reference a job and a stock location.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('inventory_txns', sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('inventory_txns', sa.Column('location', sa.String(length=128), nullable=True))
    op.create_index('ix_inventory_txns_job_id', 'inventory_txns', ['job_id'])


def downgrade() -> None:
    op.drop_index('ix_inventory_txns_job_id', table_name='inventory_txns')
    op.drop_column('inventory_txns', 'location')
    op.drop_column('inventory_txns', 'job_id')
