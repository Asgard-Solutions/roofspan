"""Protect measurement revision numbering: renumber any tied (set_id, revision_number) collisions left by a
prior canonical-set merge, then enforce uniqueness on (set_id, revision_number).

Revision numbers are the primary sort key for both backend listing and Field's pickCurrent(); tied numbers
made the "current" revision depend on DB return order. This migration deterministically renumbers every
set that has a collision (chronological: created_at, then id — supersedes_revision_id references revision
IDs and is preserved), then adds a UNIQUE constraint so it can never recur. Emits a migration report.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""
from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # 1) Find every set that currently has a tied revision_number.
    dup_set_ids = [r[0] for r in conn.execute(sa.text(
        "SELECT DISTINCT set_id FROM measurement_revisions "
        "GROUP BY set_id, revision_number HAVING COUNT(*) > 1"
    )).fetchall()]
    sets_fixed = 0
    revisions_renumbered = 0
    for set_id in dup_set_ids:
        rows = conn.execute(sa.text(
            "SELECT id, revision_number FROM measurement_revisions WHERE set_id = :s ORDER BY created_at ASC, id ASC"
        ), {"s": set_id}).fetchall()
        changed_here = 0
        for i, (rid, num) in enumerate(rows, start=1):
            if num != i:
                conn.execute(sa.text("UPDATE measurement_revisions SET revision_number = :n WHERE id = :id"), {"n": i, "id": rid})
                changed_here += 1
        if changed_here:
            sets_fixed += 1
            revisions_renumbered += changed_here
    # 2) Detect any set whose lead/property/inspection links look inconsistent (report-only, non-fatal).
    rel_conflicts = conn.execute(sa.text(
        "SELECT COUNT(*) FROM ("
        "  SELECT lead_id FROM measurement_sets WHERE lead_id IS NOT NULL GROUP BY lead_id HAVING COUNT(*) > 1"
        ") q"
    )).scalar() or 0
    # 3) Enforce uniqueness so tied revision numbers can never recur inside a set.
    op.create_unique_constraint("uq_measurement_revisions_set_number", "measurement_revisions", ["set_id", "revision_number"])
    # Migration report (surfaced in alembic output).
    print(
        "[canonical-set revision-number protection] "
        f"sets_merged_or_scanned_with_collisions={len(dup_set_ids)} "
        f"sets_fixed={sets_fixed} revisions_renumbered={revisions_renumbered} "
        f"remaining_lead_relationship_conflicts={rel_conflicts}"
    )


def downgrade() -> None:
    op.drop_constraint("uq_measurement_revisions_set_number", "measurement_revisions", type_="unique")
