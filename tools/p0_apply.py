#!/usr/bin/env python3
"""Apply and verify P0-6: lead-primary measurement-set database constraints."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
NEW_REVISION = "e7f8a9b0c1d2"
OLD_REVISION = "d5e6f7a8b9c0"


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def run(*cmd: str, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd or ROOT, check=True)


def run_capture(*cmd: str, cwd: Path | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd or ROOT, text=True, capture_output=True, check=True)
    output = (result.stdout or "") + (result.stderr or "")
    print(output, flush=True)
    return output


def run_expected_failure(*cmd: str, cwd: Path | None = None) -> None:
    result = subprocess.run(cmd, cwd=cwd or ROOT, text=True, capture_output=True)
    print(result.stdout, flush=True)
    print(result.stderr, flush=True)
    if result.returncode == 0:
        raise RuntimeError("Regression test unexpectedly passed before the P0-6 migration")


# Bring the disposable database to the current pre-P0-6 head first. The new semantics test below must
# fail under the broad uq_measurement_sets_property index, proving the regression before implementation.
run("alembic", "-c", "alembic.ini", "upgrade", "head", cwd=BACKEND)

write(
    "backend/tests/test_measurement_set_constraint_migration.py",
    r'''"""Real-PostgreSQL contract for lead-primary measurement-set identity.

The migration hierarchy is:
  * lead_id is the primary business key when present;
  * inspection_id is unique only for lead-less fallback sets;
  * property_id is unique only for sets with neither a lead nor an inspection.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import errors

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
MIGRATION = BACKEND / "alembic" / "versions" / "e7f8a9b0c1d2_lead_primary_measurement_sets.py"
NEW_REVISION = "e7f8a9b0c1d2"
OLD_REVISION = "d5e6f7a8b9c0"


def _dsn() -> str:
    raw = os.environ["DATABASE_URL"]
    return raw.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
def db():
    connection = psycopg.connect(_dsn())
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _property(conn, label: str = "property"):
    value = uuid.uuid4()
    conn.execute(
        """INSERT INTO properties
           (id, source, formatted_address, address_line1, city, state, zip_code,
            do_not_knock, created_at, updated_at)
           VALUES (%s, 'test', %s, %s, 'Oklahoma City', 'OK', '73101', false, now(), now())""",
        (value, f"{label}-{value}", f"{label}-{value}"),
    )
    return value


def _lead(conn, property_id, label: str = "lead"):
    value = uuid.uuid4()
    conn.execute(
        """INSERT INTO leads (id, property_id, name, status, created_at, updated_at)
           VALUES (%s, %s, %s, 'new', now(), now())""",
        (value, property_id, f"{label}-{value}"),
    )
    return value


def _inspection(conn, property_id=None, lead_id=None):
    value = uuid.uuid4()
    conn.execute(
        """INSERT INTO inspections (id, lead_id, property_id, created_at, updated_at)
           VALUES (%s, %s, %s, now(), now())""",
        (value, lead_id, property_id),
    )
    return value


def _measurement_set(conn, *, lead_id=None, property_id=None, inspection_id=None, value=None):
    value = value or uuid.uuid4()
    conn.execute(
        """INSERT INTO measurement_sets
           (id, inspection_id, property_id, lead_id, created_at, updated_at)
           VALUES (%s, %s, %s, %s, now(), now())""",
        (value, inspection_id, property_id, lead_id),
    )
    return value


def _index_definitions(conn):
    rows = conn.execute(
        """SELECT indexname, indexdef FROM pg_indexes
           WHERE schemaname = current_schema() AND tablename = 'measurement_sets'"""
    ).fetchall()
    return {name: definition.lower() for name, definition in rows}


def test_hierarchical_partial_indexes_exist(db):
    indexes = _index_definitions(db)
    assert "uq_measurement_sets_lead" in indexes
    assert "uq_measurement_sets_inspection_fallback" in indexes
    assert "uq_measurement_sets_property_fallback" in indexes
    assert "uq_measurement_sets_inspection" not in indexes
    assert "uq_measurement_sets_property" not in indexes

    lead = indexes["uq_measurement_sets_lead"]
    inspection = indexes["uq_measurement_sets_inspection_fallback"]
    prop = indexes["uq_measurement_sets_property_fallback"]
    assert "unique index" in lead and "(lead_id)" in lead and "lead_id is not null" in lead
    assert "unique index" in inspection and "(inspection_id)" in inspection
    assert "lead_id is null" in inspection and "inspection_id is not null" in inspection
    assert "unique index" in prop and "(property_id)" in prop
    assert "lead_id is null" in prop and "inspection_id is null" in prop and "property_id is not null" in prop


def test_distinct_leads_same_property_are_allowed(db):
    property_id = _property(db, "shared-property")
    lead_a = _lead(db, property_id, "lead-a")
    lead_b = _lead(db, property_id, "lead-b")
    _measurement_set(db, lead_id=lead_a, property_id=property_id)
    _measurement_set(db, lead_id=lead_b, property_id=property_id)
    count = db.execute(
        "SELECT count(*) FROM measurement_sets WHERE property_id = %s", (property_id,)
    ).fetchone()[0]
    assert count == 2


def test_duplicate_lead_id_is_still_rejected(db):
    property_id = _property(db, "lead-unique")
    lead_id = _lead(db, property_id)
    _measurement_set(db, lead_id=lead_id, property_id=property_id)
    with pytest.raises(errors.UniqueViolation):
        _measurement_set(db, lead_id=lead_id, property_id=property_id)


def test_duplicate_inspection_is_rejected_only_in_leadless_fallback(db):
    property_id = _property(db, "inspection-fallback")
    inspection_id = _inspection(db, property_id=property_id)
    _measurement_set(db, inspection_id=inspection_id, property_id=property_id)
    with pytest.raises(errors.UniqueViolation):
        _measurement_set(db, inspection_id=inspection_id, property_id=property_id)


def test_duplicate_property_is_rejected_only_in_bare_property_fallback(db):
    property_id = _property(db, "property-fallback")
    _measurement_set(db, property_id=property_id)
    with pytest.raises(errors.UniqueViolation):
        _measurement_set(db, property_id=property_id)


def test_lead_specific_and_property_fallback_sets_can_coexist(db):
    property_id = _property(db, "hierarchy")
    lead_id = _lead(db, property_id)
    _measurement_set(db, lead_id=lead_id, property_id=property_id)
    _measurement_set(db, property_id=property_id)
    assert db.execute(
        "SELECT count(*) FROM measurement_sets WHERE property_id = %s", (property_id,)
    ).fetchone()[0] == 2


def test_migration_is_report_only_for_suspicious_historical_relationships():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "potential_cross_lead_merge_candidates" in source
    assert "lead_property_mismatches" in source
    assert "inspection_lead_mismatches" in source
    assert "data_split=0" in source
    assert "uq_measurement_sets_inspection_fallback" in source
    assert "uq_measurement_sets_property_fallback" in source


def test_z_downgrade_refuses_to_reintroduce_broad_indexes_when_data_would_be_rejected():
    """Downgrade must fail before DDL when currently-valid lead-specific rows share a property."""
    property_id = uuid.uuid4()
    lead_a = uuid.uuid4()
    lead_b = uuid.uuid4()
    set_a = uuid.uuid4()
    set_b = uuid.uuid4()
    env = os.environ.copy()

    connection = psycopg.connect(_dsn(), autocommit=True)
    try:
        connection.execute(
            """INSERT INTO properties
               (id, source, formatted_address, address_line1, city, state, zip_code,
                do_not_knock, created_at, updated_at)
               VALUES (%s, 'test', %s, %s, 'Oklahoma City', 'OK', '73101', false, now(), now())""",
            (property_id, f"downgrade-{property_id}", f"downgrade-{property_id}"),
        )
        for lead_id, label in ((lead_a, "A"), (lead_b, "B")):
            connection.execute(
                """INSERT INTO leads (id, property_id, name, status, created_at, updated_at)
                   VALUES (%s, %s, %s, 'new', now(), now())""",
                (lead_id, property_id, f"downgrade-{label}"),
            )
        for set_id, lead_id in ((set_a, lead_a), (set_b, lead_b)):
            connection.execute(
                """INSERT INTO measurement_sets
                   (id, property_id, lead_id, created_at, updated_at)
                   VALUES (%s, %s, %s, now(), now())""",
                (set_id, property_id, lead_id),
            )

        refused = subprocess.run(
            ["alembic", "-c", "alembic.ini", "downgrade", OLD_REVISION],
            cwd=BACKEND, env=env, text=True, capture_output=True,
        )
        combined = (refused.stdout or "") + (refused.stderr or "")
        assert refused.returncode != 0, combined
        assert "Cannot downgrade lead-primary measurement-set constraints" in combined
        current = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert current == NEW_REVISION
    finally:
        connection.execute("DELETE FROM measurement_sets WHERE id IN (%s, %s)", (set_a, set_b))
        connection.execute("DELETE FROM leads WHERE id IN (%s, %s)", (lead_a, lead_b))
        connection.execute("DELETE FROM properties WHERE id = %s", (property_id,))
        connection.close()

    # Once incompatible rows are removed, both downgrade and re-upgrade must work cleanly.
    down = subprocess.run(
        ["alembic", "-c", "alembic.ini", "downgrade", OLD_REVISION],
        cwd=BACKEND, env=env, text=True, capture_output=True,
    )
    assert down.returncode == 0, (down.stdout or "") + (down.stderr or "")
    up = subprocess.run(
        ["alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND, env=env, text=True, capture_output=True,
    )
    assert up.returncode == 0, (up.stdout or "") + (up.stderr or "")
''',
)

run_expected_failure(
    "pytest", "-q",
    "backend/tests/test_measurement_set_constraint_migration.py::test_distinct_leads_same_property_are_allowed",
)

# ---------------------------------------------------------------------------
# GREEN: the forward migration replaces only the broad property/inspection
# indexes. The lead key stays globally unique; fallbacks become hierarchical.
# No historical rows are split without trustworthy provenance.
# ---------------------------------------------------------------------------
write(
    f"backend/alembic/versions/{NEW_REVISION}_lead_primary_measurement_sets.py",
    r'''"""Align measurement-set uniqueness with lead-primary business identity.

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
''',
)

run("alembic", "-c", "alembic.ini", "upgrade", "head", cwd=BACKEND)
run("pytest", "-q", "backend/tests/test_measurement_set_constraint_migration.py")

heads = run_capture("alembic", "-c", "alembic.ini", "heads", cwd=BACKEND)
head_lines = [line for line in heads.splitlines() if "(head)" in line]
if len(head_lines) != 1 or NEW_REVISION not in head_lines[0]:
    raise RuntimeError(f"Expected one Alembic head at {NEW_REVISION}, got: {head_lines}")

# Existing measurement lifecycle/outbox contracts still run on the corrected schema.
run(
    "pytest", "-q",
    "backend/tests/test_measurement_sketch_service.py",
    "backend/tests/test_office_outbox.py",
    "backend/tests/test_measurement_lifecycle_regression.py",
)
run(
    "python", "-m", "py_compile",
    f"backend/alembic/versions/{NEW_REVISION}_lead_primary_measurement_sets.py",
    "backend/services/measurements.py",
)

Path("/tmp/p0_commit_message").write_text(
    "fix: align measurement set constraints with lead identity\n",
    encoding="utf-8",
)
