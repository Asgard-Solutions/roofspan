"""price book entries: supplier/manufacturer/category targeting

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-06

Additive-only. Lets a Price Book entry target a supplier, a manufacturer, a category (in addition to
the existing material/assembly/labor targets, and a blank default). No historical estimate/quote line
is touched — these entries only drive the estimate editor and the newly-computed material Price.
"""
from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("price_book_entries", sa.Column("supplier_id", UUID(as_uuid=True), nullable=True))
    op.add_column("price_book_entries", sa.Column("manufacturer", sa.String(255), nullable=True))
    op.add_column("price_book_entries", sa.Column("category", sa.String(64), nullable=True))
    op.create_foreign_key("fk_pbe_supplier", "price_book_entries", "suppliers",
                          ["supplier_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    op.drop_constraint("fk_pbe_supplier", "price_book_entries", type_="foreignkey")
    op.drop_column("price_book_entries", "category")
    op.drop_column("price_book_entries", "manufacturer")
    op.drop_column("price_book_entries", "supplier_id")
