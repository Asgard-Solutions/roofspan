"""material crud: standard_cost + default_sell_price planning values

Revision ID: e6f7a8b9c0d1
Revises: d3e4f5a6b7c8
Create Date: 2026-06

Additive-only. Adds two manual planning money columns to materials:
- standard_cost: manual/default/fallback unit cost (NOT MWAC; never overwrites avg_cost).
- default_sell_price: default customer sell price (independent of supplier costs).
Both NUMERIC(14,4) and NULLABLE — no value is invented for existing rows, and neither alters any
historical estimate/quote/PO/job snapshot.
"""
from typing import Union
from alembic import op
import sqlalchemy as sa

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("materials", sa.Column("standard_cost", sa.Numeric(14, 4), nullable=True))
    op.add_column("materials", sa.Column("default_sell_price", sa.Numeric(14, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("materials", "default_sell_price")
    op.drop_column("materials", "standard_cost")
