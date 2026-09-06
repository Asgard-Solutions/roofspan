"""Real-PostgreSQL contract for lead-primary measurement-set identity.

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
