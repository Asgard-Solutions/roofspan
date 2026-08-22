"""ABC Supply integration P4: notifications/webhooks (registration, routing, queue, events, invoices)

Revision ID: d4a7b2c8e1f6
Revises: c3f6a8b1d2e5
Create Date: 2026-06-18 00:00:00.000000

Additive-only. Central transport metadata (registration/routing/queue) + local event/invoice metadata.
No authoritative business records are duplicated centrally.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd4a7b2c8e1f6'
down_revision: Union[str, None] = 'c3f6a8b1d2e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('abc_webhook_registrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('environment', sa.String(length=16), nullable=False, server_default='sandbox'),
        sa.Column('webhook_id', sa.String(length=128), nullable=True),
        sa.Column('name', sa.String(length=128), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='not_registered'),
        sa.Column('events', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('secret_ciphertext', sa.Text(), nullable=True),
        sa.Column('registered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'))

    op.create_table('abc_order_routes',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('installation_id', sa.String(length=64), nullable=False),
        sa.Column('abc_order_number', sa.String(length=64), nullable=True),
        sa.Column('abc_confirmation_number', sa.String(length=64), nullable=True),
        sa.Column('roofspan_po_number', sa.String(length=64), nullable=True),
        sa.Column('purchase_order_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_abc_routes_install', 'abc_order_routes', ['installation_id'])
    op.create_index('ix_abc_routes_conf', 'abc_order_routes', ['abc_confirmation_number'])
    op.create_index('ix_abc_routes_ordernum', 'abc_order_routes', ['abc_order_number'])
    op.create_index('ix_abc_routes_po', 'abc_order_routes', ['roofspan_po_number'])

    op.create_table('abc_webhook_deliveries',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_key', sa.String(length=120), nullable=False),
        sa.Column('event_type', sa.String(length=32), nullable=False),
        sa.Column('installation_id', sa.String(length=64), nullable=True),
        sa.Column('abc_order_number', sa.String(length=64), nullable=True),
        sa.Column('abc_confirmation_number', sa.String(length=64), nullable=True),
        sa.Column('roofspan_po_number', sa.String(length=64), nullable=True),
        sa.Column('payload_ciphertext', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='received'),
        sa.Column('routing_status', sa.String(length=16), nullable=False, server_default='matched'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_abc_deliv_key', 'abc_webhook_deliveries', ['event_key'], unique=True)
    op.create_index('ix_abc_deliv_install', 'abc_webhook_deliveries', ['installation_id'])

    op.create_table('abc_notification_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(length=32), nullable=False),
        sa.Column('event_key', sa.String(length=120), nullable=False),
        sa.Column('abc_order_number', sa.String(length=64), nullable=True),
        sa.Column('abc_confirmation_number', sa.String(length=64), nullable=True),
        sa.Column('purchase_order_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('abc_status', sa.String(length=64), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='processed'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_abc_notif_key', 'abc_notification_events', ['event_key'], unique=True)
    op.create_index('ix_abc_notif_po', 'abc_notification_events', ['purchase_order_id'])

    op.create_table('abc_invoice_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('purchase_order_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('abc_invoice_number', sa.String(length=64), nullable=True),
        sa.Column('abc_invoice_date', sa.String(length=32), nullable=True),
        sa.Column('abc_order_number', sa.String(length=64), nullable=True),
        sa.Column('abc_purchase_order_number', sa.String(length=64), nullable=True),
        sa.Column('is_credit_memo', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_rebill', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('event_received_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('payload_fingerprint', sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_abc_invoice_po', 'abc_invoice_events', ['purchase_order_id'])


def downgrade() -> None:
    for t in ['abc_invoice_events', 'abc_notification_events', 'abc_webhook_deliveries', 'abc_order_routes', 'abc_webhook_registrations']:
        op.drop_table(t)
