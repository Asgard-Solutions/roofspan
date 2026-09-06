"""Canonical measurement set: merge duplicate active sets + enforce one set per lead/property/inspection.

Merges pre-existing duplicate measurement_sets that share a lead_id/property_id/inspection_id into a single
deterministic canonical set (earliest created_at, then id), repointing all measurement_revisions onto the
canonical set (revisions carry their own sketches, photos and audit history by revision_id, so those are
preserved automatically). Missing lead/property/inspection links are backfilled onto the canonical set from
the merged duplicates. Then partial-unique indexes prevent any new duplicate active set per identifier.

Revision ID: a2b3c4d5e6f7
Revises: f8a1b2c3d4e5
"""
from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "f8a1b2c3d4e5"
branch_labels = None
depends_on = None


def _merge_by(conn, key: str):
    dup_values = conn.execute(sa.text(
        f"SELECT {key} FROM measurement_sets WHERE {key} IS NOT NULL GROUP BY {key} HAVING COUNT(*) > 1"
    )).fetchall()
    for (val,) in dup_values:
        rows = conn.execute(sa.text(
            f"SELECT id, inspection_id, property_id, lead_id FROM measurement_sets "
            f"WHERE {key} = :v ORDER BY created_at ASC, id ASC"
        ), {"v": val}).fetchall()
        if len(rows) < 2:
            continue
        canonical = rows[0]
        canon_id = canonical[0]
        canon_insp, canon_prop, canon_lead = canonical[1], canonical[2], canonical[3]
        for dupe in rows[1:]:
            dupe_id, d_insp, d_prop, d_lead = dupe
            # Repoint every revision (sketches/photos/audit follow by revision_id — preserved).
            conn.execute(sa.text("UPDATE measurement_revisions SET set_id = :c WHERE set_id = :d"),
                         {"c": canon_id, "d": dupe_id})
            # Backfill any link the canonical set is missing from the duplicate.
            if canon_insp is None and d_insp is not None:
                conn.execute(sa.text("UPDATE measurement_sets SET inspection_id = :x WHERE id = :c"), {"x": d_insp, "c": canon_id})
                canon_insp = d_insp
            if canon_prop is None and d_prop is not None:
                conn.execute(sa.text("UPDATE measurement_sets SET property_id = :x WHERE id = :c"), {"x": d_prop, "c": canon_id})
                canon_prop = d_prop
            if canon_lead is None and d_lead is not None:
                conn.execute(sa.text("UPDATE measurement_sets SET lead_id = :x WHERE id = :c"), {"x": d_lead, "c": canon_id})
                canon_lead = d_lead
            conn.execute(sa.text("DELETE FROM measurement_sets WHERE id = :d"), {"d": dupe_id})


def upgrade() -> None:
    conn = op.get_bind()
    # 1) Safely merge historical duplicates BEFORE the unique indexes are created.
    for key in ("lead_id", "property_id", "inspection_id"):
        _merge_by(conn, key)
    # 2) Enforce the business rule: at most one measurement set per identifier (partial unique indexes,
    #    NULLs allowed for the other identifiers).
    op.create_index("uq_measurement_sets_lead", "measurement_sets", ["lead_id"], unique=True,
                    postgresql_where=sa.text("lead_id IS NOT NULL"))
    op.create_index("uq_measurement_sets_property", "measurement_sets", ["property_id"], unique=True,
                    postgresql_where=sa.text("property_id IS NOT NULL"))
    op.create_index("uq_measurement_sets_inspection", "measurement_sets", ["inspection_id"], unique=True,
                    postgresql_where=sa.text("inspection_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_measurement_sets_inspection", table_name="measurement_sets")
    op.drop_index("uq_measurement_sets_property", table_name="measurement_sets")
    op.drop_index("uq_measurement_sets_lead", table_name="measurement_sets")
