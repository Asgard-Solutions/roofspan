"""Crews as managed records; jobs.crew_id. Existing free-text jobs.assigned_to values become crews.

assigned_to is kept (synced to the crew name) so older clients keep showing the crew.

Revision ID: a9c8e7d6f5b4
Revises: e7f8a9b0c1d2
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a9c8e7d6f5b4"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("uq_crews_name_lower", "crews", [sa.text("lower(name)")], unique=True)
    op.add_column("jobs", sa.Column("crew_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_jobs_crew_id", "jobs", "crews", ["crew_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_jobs_crew_id", "jobs", ["crew_id"])
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO crews (id, name, active, created_at, updated_at)
        SELECT gen_random_uuid(), min(btrim(assigned_to)), true, now(), now()
        FROM jobs WHERE assigned_to IS NOT NULL AND btrim(assigned_to) <> ''
        GROUP BY lower(btrim(assigned_to))
    """))
    conn.execute(sa.text("""
        UPDATE jobs j SET crew_id = c.id FROM crews c
        WHERE j.assigned_to IS NOT NULL AND lower(btrim(j.assigned_to)) = lower(c.name)
    """))


def downgrade() -> None:
    op.drop_index("ix_jobs_crew_id", table_name="jobs")
    op.drop_constraint("fk_jobs_crew_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "crew_id")
    op.drop_index("uq_crews_name_lower", table_name="crews")
    op.drop_table("crews")
