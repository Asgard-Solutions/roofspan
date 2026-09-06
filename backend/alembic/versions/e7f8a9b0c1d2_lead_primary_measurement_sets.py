"""Align measurement-set uniqueness with lead-primary business identity.

Lead-scoped sets may legitimately share a property or inspection with another lead. Property and
inspection uniqueness therefore apply only to progressively broader fallback identities.

Historical data is never split automatically: the previous canonical-set migration did not retain enough
provenance to reconstruct any pre-merge ownership safely. This migration emits report-only diagnostics for
candidate/mismatched relationships so operators can review them without destructive guessing.

Revision ID: e7f8a9b0c1d2
Revises: d5e6f7a8b9c0
"""
from alembic import op
import sqlalchemy as sa

revision = "e7f8a9b0c1d2"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def _count(conn, sql: str) -> int:
    return int(conn.execute(sa.text(sql)).scalar() or 0)


def upgrade() -> None:
    conn = op.get_bind()

    # Report only. A property with multiple active leads but one set is a possible artifact of the old
    # broad-property merge; it is not proof, so we never manufacture or split records automatically.
    potential_cross_lead_merge_candidates = _count(conn, """
        SELECT count(*) FROM (
            SELECT l.property_id
            FROM leads l
            LEFT JOIN measurement_sets ms ON ms.property_id = l.property_id
            WHERE l.property_id IS NOT NULL AND l.status <> 'archived'
            GROUP BY l.property_id
            HAVING count(DISTINCT l.id) > 1 AND count(DISTINCT ms.id) = 1
        ) candidates
    """)
    lead_property_mismatches = _count(conn, """
        SELECT count(*)
        FROM measurement_sets ms
        JOIN leads l ON l.id = ms.lead_id
        WHERE ms.property_id IS NOT NULL
          AND l.property_id IS NOT NULL
          AND ms.property_id <> l.property_id
    """)
    inspection_lead_mismatches = _count(conn, """
        SELECT count(*)
        FROM measurement_sets ms
        JOIN inspections i ON i.id = ms.inspection_id
        WHERE ms.lead_id IS NOT NULL
          AND i.lead_id IS NOT NULL
          AND ms.lead_id <> i.lead_id
    """)

    # The lead index from a2b3c4d5e6f7 already expresses the primary identity and remains unchanged.
    op.drop_index("uq_measurement_sets_inspection", table_name="measurement_sets")
    op.drop_index("uq_measurement_sets_property", table_name="measurement_sets")

    op.create_index(
        "uq_measurement_sets_inspection_fallback",
        "measurement_sets",
        ["inspection_id"],
        unique=True,
        postgresql_where=sa.text("lead_id IS NULL AND inspection_id IS NOT NULL"),
    )
    op.create_index(
        "uq_measurement_sets_property_fallback",
        "measurement_sets",
        ["property_id"],
        unique=True,
        postgresql_where=sa.text(
            "lead_id IS NULL AND inspection_id IS NULL AND property_id IS NOT NULL"
        ),
    )

    print(
        "[lead-primary measurement-set constraints] "
        f"potential_cross_lead_merge_candidates={potential_cross_lead_merge_candidates} "
        f"lead_property_mismatches={lead_property_mismatches} "
        f"inspection_lead_mismatches={inspection_lead_mismatches} "
        "data_split=0"
    )


def downgrade() -> None:
    conn = op.get_bind()
    property_duplicates = conn.execute(sa.text("""
        SELECT property_id, count(*)
        FROM measurement_sets
        WHERE property_id IS NOT NULL
        GROUP BY property_id
        HAVING count(*) > 1
        ORDER BY count(*) DESC, property_id
        LIMIT 10
    """)).fetchall()
    inspection_duplicates = conn.execute(sa.text("""
        SELECT inspection_id, count(*)
        FROM measurement_sets
        WHERE inspection_id IS NOT NULL
        GROUP BY inspection_id
        HAVING count(*) > 1
        ORDER BY count(*) DESC, inspection_id
        LIMIT 10
    """)).fetchall()
    if property_duplicates or inspection_duplicates:
        raise RuntimeError(
            "Cannot downgrade lead-primary measurement-set constraints: current rows are valid under "
            "the hierarchy but violate the former broad property/inspection uniqueness. Resolve or "
            "archive the duplicate identities before retrying. "
            f"property_conflicts={len(property_duplicates)} "
            f"inspection_conflicts={len(inspection_duplicates)}"
        )

    op.drop_index("uq_measurement_sets_property_fallback", table_name="measurement_sets")
    op.drop_index("uq_measurement_sets_inspection_fallback", table_name="measurement_sets")
    op.create_index(
        "uq_measurement_sets_property",
        "measurement_sets",
        ["property_id"],
        unique=True,
        postgresql_where=sa.text("property_id IS NOT NULL"),
    )
    op.create_index(
        "uq_measurement_sets_inspection",
        "measurement_sets",
        ["inspection_id"],
        unique=True,
        postgresql_where=sa.text("inspection_id IS NOT NULL"),
    )
