"""C6: company recovery + one active installation per identity key.

- companies: phone, address, match_key (normalized name+phone+address), recovery code (hash for lookup,
  AES-GCM copy so RoofSpan staff can read it back for a customer).
- installations: rows sharing an identity key are collapsed (newest ACTIVE kept, older ones REPLACED),
  then a partial unique index makes a second ACTIVE row for the same key impossible.

Revision ID: f3a9c1d2b7e4
Revises: e1f2a3b4c5d6
"""
from alembic import op
import sqlalchemy as sa

revision = "f3a9c1d2b7e4"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("phone", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("companies", sa.Column("address", sa.String(length=500), nullable=False, server_default=""))
    op.add_column("companies", sa.Column("match_key", sa.String(length=64), nullable=True))
    op.add_column("companies", sa.Column("recovery_code_hash", sa.String(length=64), nullable=True))
    op.add_column("companies", sa.Column("recovery_code_enc", sa.Text(), nullable=True))
    # match_key is new (NULL for every existing company), so this cannot collide with existing data.
    op.execute("CREATE UNIQUE INDEX uq_companies_active_match_key ON companies (match_key) "
               "WHERE status = 'ACTIVE' AND match_key IS NOT NULL")
    op.create_index("uq_companies_recovery_code_hash", "companies", ["recovery_code_hash"], unique=True)

    op.execute("""
        WITH ranked AS (
            SELECT id, row_number() OVER (
                PARTITION BY public_key_pem
                ORDER BY (status = 'ACTIVE') DESC, created_at DESC NULLS LAST, id DESC) AS rn
            FROM installations)
        UPDATE installations SET status = 'REPLACED'
        WHERE status = 'ACTIVE' AND id IN (SELECT id FROM ranked WHERE rn > 1)
    """)
    op.execute("CREATE UNIQUE INDEX uq_installations_active_public_key "
               "ON installations (md5(public_key_pem)) WHERE status = 'ACTIVE'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_installations_active_public_key")
    op.drop_index("uq_companies_recovery_code_hash", table_name="companies")
    op.execute("DROP INDEX IF EXISTS uq_companies_active_match_key")
    for col in ("recovery_code_enc", "recovery_code_hash", "match_key", "address", "phone"):
        op.drop_column("companies", col)
