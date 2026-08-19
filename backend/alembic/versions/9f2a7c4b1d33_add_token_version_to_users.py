"""add token_version to users (JWT invalidation on password change/reset/recovery)

Revision ID: 9f2a7c4b1d33
Revises: 7d664e2b745d
Create Date: 2026-06-01

"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "9f2a7c4b1d33"
down_revision: Union[str, None] = "7d664e2b745d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing users get a safe default of 1 (their currently-issued tokens lack the claim -> one re-login).
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
