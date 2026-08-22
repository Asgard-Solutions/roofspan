"""job material automation: operational plan linkage on job_materials (additive)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06
"""
from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_materials", sa.Column("unit", sa.String(32), nullable=True))
    op.add_column("job_materials", sa.Column("source_quote_id", UUID(as_uuid=True), nullable=True))
    op.add_column("job_materials", sa.Column("source_quote_line_id", UUID(as_uuid=True), nullable=True))
    op.add_column("job_materials", sa.Column("assembly_id", UUID(as_uuid=True), nullable=True))
    op.add_column("job_materials", sa.Column("assembly_name", sa.String(255), nullable=True))
    op.create_index("ix_job_materials_source_line", "job_materials", ["source_quote_line_id"])


def downgrade() -> None:
    op.drop_index("ix_job_materials_source_line", table_name="job_materials")
    for c in ("assembly_name", "assembly_id", "source_quote_line_id", "source_quote_id", "unit"):
        op.drop_column("job_materials", c)
