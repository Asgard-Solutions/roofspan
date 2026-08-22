"""ABC Supply integration P3: PO order fields + abc_order_submissions

Revision ID: c3f6a8b1d2e5
Revises: b2d5e7c9a1f3
Create Date: 2026-06-17 00:00:00.000000

Additive-only. Generic (non-ABC) purchase orders, receiving and inventory are unaffected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c3f6a8b1d2e5'
down_revision: Union[str, None] = 'b2d5e7c9a1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('purchase_orders', sa.Column('external_order_number', sa.String(length=64), nullable=True))
    op.add_column('purchase_orders', sa.Column('external_confirmation_number', sa.String(length=64), nullable=True))
    op.add_column('purchase_orders', sa.Column('external_tracking_id', sa.String(length=64), nullable=True))
    op.add_column('purchase_orders', sa.Column('abc_order_status', sa.String(length=48), nullable=True))
    op.add_column('purchase_orders', sa.Column('abc_normalized_status', sa.String(length=24), nullable=True))
    op.add_column('purchase_orders', sa.Column('abc_submitted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('purchase_orders', sa.Column('abc_last_sync_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'abc_order_submissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('purchase_order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('submission_key', sa.String(length=80), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('abc_confirmation_number', sa.String(length=64), nullable=True),
        sa.Column('abc_order_number', sa.String(length=64), nullable=True),
        sa.Column('abc_tracking_id', sa.String(length=64), nullable=True),
        sa.Column('request_fingerprint', sa.String(length=128), nullable=True),
        sa.Column('delivery', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_abc_order_submissions_po', 'abc_order_submissions', ['purchase_order_id'])
    op.create_index('ix_abc_order_submissions_key', 'abc_order_submissions', ['submission_key'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_abc_order_submissions_key', table_name='abc_order_submissions')
    op.drop_index('ix_abc_order_submissions_po', table_name='abc_order_submissions')
    op.drop_table('abc_order_submissions')
    for col in ['abc_last_sync_at', 'abc_submitted_at', 'abc_normalized_status', 'abc_order_status',
                'external_tracking_id', 'external_confirmation_number', 'external_order_number']:
        op.drop_column('purchase_orders', col)
