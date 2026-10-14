"""Real-PostgreSQL proof that the matrix's migration fault injection does exactly what the scenarios claim.

The SQL is extracted verbatim from Invoke-MatrixScenario.ps1 (Enable-MigrationFault), so it cannot drift.
Needs ROOFSPAN_UPGRADE_TEST_PG="host:port:superpassword" (a disposable server; the matrix plan job provides one).
"""
import os
import re
import secrets
from pathlib import Path

import pytest

PG = os.environ.get("ROOFSPAN_UPGRADE_TEST_PG", "")
pytestmark = pytest.mark.skipif(not PG, reason="ENV: ROOFSPAN_UPGRADE_TEST_PG is not set (no disposable PostgreSQL)")
SRC = (Path(__file__).resolve().parent / "matrix" / "Invoke-MatrixScenario.ps1").read_text(encoding="utf-8")


def _fault_sql(mode: str, role: str, heads: list) -> str:
    body = SRC.split("function Enable-MigrationFault", 1)[1]
    tpl = re.search(r'\$sql = @"\n(.*?)\n"@', body, re.S).group(1)
    arr = "ARRAY[" + ",".join(f"'{h}'" for h in heads) + "]::text[]"
    return (tpl.replace("`$f`$", "$f$").replace("$role", role).replace("$first", "true" if mode == "first" else "false")
            .replace("$heads", arr))


@pytest.fixture()
def db():
    psycopg = pytest.importorskip("psycopg")
    host, port, pw = PG.split(":", 2)
    name, role, rpw = f"rs_mx_{secrets.token_hex(4)}", f"rs_mx_app_{secrets.token_hex(3)}", secrets.token_hex(8)
    su = psycopg.connect(host=host, port=int(port), user="postgres", password=pw, dbname="postgres", autocommit=True)
    su.execute(f'CREATE ROLE "{role}" LOGIN PASSWORD \'{rpw}\'')
    su.execute(f'CREATE DATABASE "{name}" OWNER "{role}"')
    sdb = psycopg.connect(host=host, port=int(port), user="postgres", password=pw, dbname=name, autocommit=True)
    sdb.execute(f'ALTER SCHEMA public OWNER TO "{role}"')
    app = psycopg.connect(host=host, port=int(port), user=role, password=rpw, dbname=name)
    app.execute("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
    app.execute("INSERT INTO alembic_version VALUES ('base')")
    app.execute("CREATE TABLE customer (id int PRIMARY KEY)")
    app.execute("INSERT INTO customer SELECT generate_series(1, 10)")
    app.commit()
    yield {"su": sdb, "app": app, "role": role}
    app.close()
    sdb.close()
    su.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    su.execute(f'DROP ROLE IF EXISTS "{role}"')
    su.close()


def _migrate(app):
    """What Alembic does for two pending revisions on PostgreSQL: DDL + version write per revision, one transaction."""
    app.execute("CREATE TABLE rev1_table (id int)")
    app.execute("UPDATE alembic_version SET version_num='rev1' WHERE version_num='base'")
    app.execute("ALTER TABLE customer ADD COLUMN rev2_col text")
    app.execute("UPDATE alembic_version SET version_num='head2' WHERE version_num='rev1'")
    app.commit()


def _state(db):
    db["app"].rollback()
    rev = db["app"].execute("SELECT version_num FROM alembic_version").fetchone()[0]
    t = db["app"].execute("SELECT count(*) FROM pg_class WHERE relname='rev1_table'").fetchone()[0]
    n = db["app"].execute("SELECT count(*) FROM customer").fetchone()[0]
    return rev, t, n


def test_first_mode_fails_before_any_ddl_or_revision(db):
    db["su"].execute(_fault_sql("first", db["role"], ["head2"]))
    with pytest.raises(Exception, match=r"RS_MATRIX_INJECTED_MIGRATION_FAILURE ddl_before_failure=0 point=first-ddl"):
        _migrate(db["app"])
    assert _state(db) == ("base", 0, 10)


def test_final_head_mode_fails_only_after_schema_changes(db):
    db["su"].execute(_fault_sql("final-head", db["role"], ["head2"]))
    with pytest.raises(Exception, match=r"ddl_before_failure=2 point=head2"):
        _migrate(db["app"])
    assert _state(db) == ("base", 0, 10)


def test_fault_ignores_superuser_restores_and_unrelated_revisions(db):
    db["su"].execute(_fault_sql("final-head", db["role"], ["other_head"]))
    db["su"].execute("CREATE TABLE su_ok (id int)")
    _migrate(db["app"])
    assert _state(db)[0] == "head2"
