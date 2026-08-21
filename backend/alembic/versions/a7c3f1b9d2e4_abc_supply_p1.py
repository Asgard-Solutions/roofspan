"""ABC Supply integration P1: abc_integrations + abc_account_links

Revision ID: a7c3f1b9d2e4
Revises: 7d664e2b745d
Create Date: 2026-06-15 00:00:00.000000

Additive-only. Creates ABC Supply connection/config storage (Desktop only). No changes to
existing business tables; existing suppliers/purchase orders/receiving remain intact.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a7c3f1b9d2e4'
down_revision: Union[str, None] = '7d664e2b745d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'abc_integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('environment', sa.String(length=16), nullable=False, server_default='sandbox'),
        sa.Column('client_id', sa.String(length=255), nullable=True),
        sa.Column('client_secret_ciphertext', sa.Text(), nullable=True),
        sa.Column('client_secret_last4', sa.String(length=8), nullable=True),
        sa.Column('redirect_uri', sa.String(length=500), nullable=True),
        sa.Column('webhook_public_url', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='not_connected'),
        sa.Column('access_token_ciphertext', sa.Text(), nullable=True),
        sa.Column('refresh_token_ciphertext', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('token_scopes', sa.String(length=500), nullable=True),
        sa.Column('pkce_verifier_ciphertext', sa.Text(), nullable=True),
        sa.Column('oauth_state', sa.String(length=128), nullable=True),
        sa.Column('connected_identity', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('default_ship_to_number', sa.String(length=64), nullable=True),
        sa.Column('default_branch_number', sa.String(length=64), nullable=True),
        sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_connected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_by', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_abc_integrations_oauth_state', 'abc_integrations', ['oauth_state'])

    op.create_table(
        'abc_account_links',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('ship_to_number', sa.String(length=64), nullable=False),
        sa.Column('ship_to_name', sa.String(length=255), nullable=True),
        sa.Column('bill_to_number', sa.String(length=64), nullable=True),
        sa.Column('bill_to_name', sa.String(length=255), nullable=True),
        sa.Column('sold_to_number', sa.String(length=64), nullable=True),
        sa.Column('sold_to_name', sa.String(length=255), nullable=True),
        sa.Column('address', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('branches', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('home_branch_number', sa.String(length=64), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_abc_account_links_ship_to_number', 'abc_account_links', ['ship_to_number'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_abc_account_links_ship_to_number', table_name='abc_account_links')
    op.drop_table('abc_account_links')
    op.drop_index('ix_abc_integrations_oauth_state', table_name='abc_integrations')
    op.drop_table('abc_integrations')
