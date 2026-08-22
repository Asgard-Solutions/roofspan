"""actual job costing (batch 1): MWAC cost basis columns

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-06

Additive-only. Adds Moving Weighted Average Cost basis to materials and immutable per-transaction
cost snapshots to the inventory ledger. All new money columns are NUMERIC(14,4) and NULLABLE — no
zero-cost basis is ever invented for existing rows (historical stock without cost history stays NULL
and is surfaced as "Missing Cost Basis").
"""
from typing import Union
from alembic import op
import sqlalchemy as sa

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("materials", sa.Column("avg_cost", sa.Numeric(14, 4), nullable=True))
    op.add_column("inventory_txns", sa.Column("unit_cost", sa.Numeric(14, 4), nullable=True))
    op.add_column("inventory_txns", sa.Column("extended_cost", sa.Numeric(14, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("inventory_txns", "extended_cost")
    op.drop_column("inventory_txns", "unit_cost")
    op.drop_column("materials", "avg_cost")
