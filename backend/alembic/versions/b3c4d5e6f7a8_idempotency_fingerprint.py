"""Store a request-body fingerprint on idempotency records.

Reusing one Idempotency-Key with a DIFFERENT request body must never silently replay the old result as
though the new body were accepted (P0 measurement data-loss guard).

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
"""
from alembic import op
import sqlalchemy as sa

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("idempotency_keys", sa.Column("request_fingerprint", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("idempotency_keys", "request_fingerprint")
