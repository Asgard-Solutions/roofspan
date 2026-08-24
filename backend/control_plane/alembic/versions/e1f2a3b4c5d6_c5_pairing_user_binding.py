"""C5: bind Mobile pairing tokens + devices to a specific Office user (expected_user).

Additive-only. expected_user_id is the Office (local) user UUID as a string; the Control Plane never
stores the employee directory or any credential — this is a binding/label only.

Revision ID: e1f2a3b4c5d6
Revises: b2d7e1f4a9c6
"""
from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "b2d7e1f4a9c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pairing_tokens", sa.Column("expected_user_id", sa.String(length=64), nullable=True))
    op.add_column("pairing_tokens", sa.Column("expected_user_label", sa.String(length=160), nullable=True))
    op.add_column("mobile_devices", sa.Column("expected_user_id", sa.String(length=64), nullable=True))
    op.add_column("mobile_devices", sa.Column("expected_user_label", sa.String(length=160), nullable=True))
    op.create_index("ix_mobile_devices_expected_user_id", "mobile_devices", ["expected_user_id"])


def downgrade() -> None:
    op.drop_index("ix_mobile_devices_expected_user_id", table_name="mobile_devices")
    op.drop_column("mobile_devices", "expected_user_label")
    op.drop_column("mobile_devices", "expected_user_id")
    op.drop_column("pairing_tokens", "expected_user_label")
    op.drop_column("pairing_tokens", "expected_user_id")
