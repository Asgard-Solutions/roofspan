"""c3 stripe provider_subscription_id

Revision ID: a1c4f9d2e7b3
Revises: 8d6a0d7b8949
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c4f9d2e7b3'
down_revision: Union[str, None] = '8d6a0d7b8949'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('subscriptions', sa.Column('provider_subscription_id', sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column('subscriptions', 'provider_subscription_id')
