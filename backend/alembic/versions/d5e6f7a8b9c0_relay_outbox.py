"""Durable transactional outbox for Office->Field measurement invalidations (relay_outbox_events).

Each measurement/sketch write enqueues a lightweight invalidation IN THE SAME TRANSACTION; the loopback
Relay Connector leases undelivered rows (lease/ack/retry), forwards a `measurement_changed` frame up the
tunnel, and acks after the Relay confirms acceptance. Stable event id, at-least-once delivery.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "relay_outbox_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=True),
        sa.Column("measurement_set_id", UUID(as_uuid=True), nullable=True),
        sa.Column("revision_id", UUID(as_uuid=True), nullable=True),
        sa.Column("structure_id", sa.String(length=64), nullable=True),
        sa.Column("sketch_document_version", sa.Integer(), nullable=True),
        sa.Column("updated_at_watermark", sa.String(length=48), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    # Fast scan for the leaser: undelivered rows in creation order.
    op.create_index(
        "ix_relay_outbox_undelivered", "relay_outbox_events", ["created_at"],
        postgresql_where=sa.text("delivered_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_relay_outbox_undelivered", table_name="relay_outbox_events")
    op.drop_table("relay_outbox_events")
