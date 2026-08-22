"""advanced inventory operations: locations, per-location balances, location-aware ledger

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06

Additive + safe backfill: seeds a default 'Main Warehouse' location and moves every material's
existing quantity_on_hand into a balance at that location (company totals unchanged).
"""
from typing import Union
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_locations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(24), nullable=False, server_default="warehouse"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("address", sa.String(400), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "inventory_balances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("material_id", UUID(as_uuid=True), sa.ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("location_id", UUID(as_uuid=True), sa.ForeignKey("inventory_locations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("quantity_on_hand", sa.Float(), nullable=False, server_default="0"),
        sa.UniqueConstraint("material_id", "location_id", name="uq_inventory_balance_material_location"),
    )
    op.add_column("inventory_txns", sa.Column("source_location_id", UUID(as_uuid=True), sa.ForeignKey("inventory_locations.id", ondelete="SET NULL"), nullable=True))
    op.add_column("inventory_txns", sa.Column("destination_location_id", UUID(as_uuid=True), sa.ForeignKey("inventory_locations.id", ondelete="SET NULL"), nullable=True))

    # seed default location
    loc_id = str(uuid.uuid4())
    op.execute(sa.text(
        "INSERT INTO inventory_locations (id, name, type, active, is_default, created_at, updated_at) "
        "VALUES (CAST(:id AS uuid), 'Main Warehouse', 'warehouse', true, true, now(), now())"
    ).bindparams(id=loc_id))
    # backfill balances from existing material.quantity_on_hand (preserve totals)
    op.execute(sa.text(
        "INSERT INTO inventory_balances (id, material_id, location_id, quantity_on_hand) "
        "SELECT gen_random_uuid(), m.id, CAST(:loc AS uuid), m.quantity_on_hand "
        "FROM materials m WHERE m.quantity_on_hand IS NOT NULL"
    ).bindparams(loc=loc_id))


def downgrade() -> None:
    op.drop_column("inventory_txns", "destination_location_id")
    op.drop_column("inventory_txns", "source_location_id")
    op.drop_table("inventory_balances")
    op.drop_table("inventory_locations")
