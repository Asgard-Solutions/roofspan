"""phase C0 licensing: license_cache table

Revision ID: 7d664e2b745d
Revises: 53c1a6663c52
Create Date: 2026-06-01 00:00:00.000000

Additive-only: adds the local entitlement cache. No changes to existing business tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d664e2b745d'
down_revision: Union[str, None] = '53c1a6663c52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'license_cache',
        sa.Column('installation_id', sa.String(length=64), nullable=False),
        sa.Column('company_id', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('license_id', sa.String(length=64), nullable=True),
        sa.Column('entitlement_jws', sa.Text(), nullable=True),
        sa.Column('kid', sa.String(length=64), nullable=True),
        sa.Column('subscription_state', sa.String(length=16), nullable=False, server_default='SUSPENDED'),
        sa.Column('seats_licensed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('product', sa.String(length=64), nullable=False, server_default='roofspan-office'),
        sa.Column('min_supported_version', sa.String(length=32), nullable=True),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('refresh_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('grace_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_check_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_check_ok', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('last_error', sa.String(length=500), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('installation_id'),
    )


def downgrade() -> None:
    op.drop_table('license_cache')
