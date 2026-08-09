"""c4 mobile_devices credential_hash

Revision ID: b2d7e1f4a9c6
Revises: a1c4f9d2e7b3
Create Date: 2026-06-10 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2d7e1f4a9c6'
down_revision: Union[str, None] = 'a1c4f9d2e7b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('mobile_devices', sa.Column('credential_hash', sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column('mobile_devices', 'credential_hash')
