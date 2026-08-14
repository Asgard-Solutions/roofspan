"""add zip_code to territories (for ZIP-derived territories + direct RentCast zip pulls)

Revision ID: a1b2c3d4e5f6
Revises: 9f2a7c4b1d33
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "9f2a7c4b1d33"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("territories", sa.Column("zip_code", sa.String(length=16), nullable=True))


def downgrade():
    op.drop_column("territories", "zip_code")
