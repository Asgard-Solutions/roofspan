"""add canvassing routes and route_stops

Revision ID: c1d2e3f4a5b6
Revises: a1b2c3d4e5f6
Create Date: 2026-06-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'routes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('territory_id', sa.UUID(), nullable=True),
        sa.Column('assigned_user_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('stop_count', sa.Integer(), nullable=False),
        sa.Column('est_miles', sa.Float(), nullable=False),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['territory_id'], ['territories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['assigned_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_routes_assigned_user_id'), 'routes', ['assigned_user_id'], unique=False)
    op.create_index(op.f('ix_routes_territory_id'), 'routes', ['territory_id'], unique=False)

    op.create_table(
        'route_stops',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('route_id', sa.UUID(), nullable=False),
        sa.Column('property_id', sa.UUID(), nullable=True),
        sa.Column('sort', sa.Integer(), nullable=False),
        sa.Column('address', sa.String(length=400), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['route_id'], ['routes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_route_stops_route_id'), 'route_stops', ['route_id'], unique=False)
    op.create_index(op.f('ix_route_stops_property_id'), 'route_stops', ['property_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_route_stops_property_id'), table_name='route_stops')
    op.drop_index(op.f('ix_route_stops_route_id'), table_name='route_stops')
    op.drop_table('route_stops')
    op.drop_index(op.f('ix_routes_territory_id'), table_name='routes')
    op.drop_index(op.f('ix_routes_assigned_user_id'), table_name='routes')
    op.drop_table('routes')
