"""Real PostgreSQL release gate for both Control Plane storage modes and damaged legacy repair.

Run explicitly with:
    CP_RUN_INTEGRATION=1 ROOFSPAN_TEST_PG_DSN=postgresql://postgres:.../postgres \
      pytest -q backend/tests/test_control_plane_migrations_live.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

import psycopg
import pytest
from psycopg import sql

pytestmark = pytest.mark.skipif(
    os.environ.get("CP_RUN_INTEGRATION") != "1",
    reason="real Control Plane PostgreSQL integration test is explicitly gated",
)

BACKEND = Path(__file__).resolve().parents[1]
ADMIN_DSN = os.environ.get("ROOFSPAN_TEST_PG_DSN", "")
HEAD = "e1f2a3b4c5d6"
REQUIRED_TABLES = {
    "companies", "cp_audit_logs", "entitlement_issuances", "request_nonces", "signing_keys",
    "version_policy", "installations", "licenses", "subscriptions", "billing_events",
    "mobile_devices", "pairing_tokens", "alembic_version",
}


def _dsn(database: str, user: str, password: str, *, async_driver: bool = False) -> str:
    parsed = urlparse(ADMIN_DSN)
    scheme = "postgresql+asyncpg" if async_driver else "postgresql"
    netloc = f"{quote(user)}:{quote(password)}@{parsed.hostname}:{parsed.port or 5432}"
    return urlunparse((scheme, netloc, f"/{database}", "", "", ""))


class PgSandbox:
    def __init__(self):
        token = uuid.uuid4().hex[:10]
        self.role = f"rscp_{token}"
        self.password = f"Pw{uuid.uuid4().hex}9"
        self.business_db = f"rso_{token}"
        self.cp_db = f"rscpdb_{token}"

    def create(self):
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB").format(
                    sql.Identifier(self.role), sql.Literal(self.password)
                )
            )
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(self.business_db), sql.Identifier(self.role)
                )
            )
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(self.cp_db), sql.Identifier(self.role)
                )
            )
        return self

    def cleanup(self):
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            for db in (self.business_db, self.cp_db):
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid <> pg_backend_pid()",
                    (db,),
                )
                conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db)))
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(self.role)))

    def env(self, mode: str, tmp_path: Path) -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(BACKEND)
        env["DATABASE_URL"] = _dsn(self.business_db, self.role, self.password, async_driver=True)
        target_db = self.cp_db if mode == "database" else self.business_db
        env["CONTROL_PLANE_DATABASE_URL"] = _dsn(target_db, self.role, self.password, async_driver=True)
        if mode == "schema":
            env["CONTROL_PLANE_SCHEMA"] = "roofspan_control_plane"
        else:
            env.pop("CONTROL_PLANE_SCHEMA", None)
        env.update({
            "CP_ENV": "dev",
            "ENTITLEMENT_SIGNER": "local",
            "BILLING_MODE": "mock",
            "CP_DEV_SIGNING_KEYS_DIR": str(tmp_path / f"keys-{mode}"),
            "CP_DEV_BOOTSTRAP_SECRET": "dev-bootstrap-roofspan",
            "CP_DEV_ADMIN_SECRET": "dev-admin-roofspan",
        })
        return env


@pytest.fixture()
def pgbox():
    if not ADMIN_DSN:
        pytest.skip("ROOFSPAN_TEST_PG_DSN is not configured")
    box = PgSandbox().create()
    try:
        yield box
    finally:
        box.cleanup()


MIGRATE_PROBE = r'''
import json
from control_plane.migrations_runner import ControlPlaneMigrationError, run_cp_migrations
try:
    print(json.dumps({"ok": True, "report": run_cp_migrations()}, sort_keys=True))
except ControlPlaneMigrationError as exc:
    print(json.dumps({"ok": False, "code": exc.code, "report": exc.report.to_dict()}, sort_keys=True))
    raise SystemExit(2)
'''

ACTIVATE_PAIR_PROBE = r'''
import asyncio
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from control_plane.bootstrap import init_control_plane
from control_plane.db import SessionLocal
from control_plane import service

async def main():
    status = await init_control_plane()
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")
    async with SessionLocal() as db:
        activation = await service.activate(
            db,
            company_name="Release Gate Roofing",
            requested_seats=5,
            public_key_pem=public,
            software_version="1.0.0",
            bootstrap_credential="dev-bootstrap-roofspan",
        )
        pairing = await service.create_pairing(
            db,
            installation_id=activation["installation_id"],
            expected_user_id="00000000-0000-0000-0000-000000000123",
            expected_user_label="Release Gate User",
        )
        resolved = await service.resolve_pairing(db, token=pairing["token"], label="Release Gate Device")
    print(json.dumps({
        "ready": status["ready"],
        "revision": status["current_revision"],
        "installation_id": activation["installation_id"],
        "pairing_user": resolved["expected_user_id"],
        "device_id": resolved["device_id"],
    }, sort_keys=True))

asyncio.run(main())
'''


def _run(code: str, env: dict[str, str], *, expect: int = 0) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
        timeout=90,
    )
    assert result.returncode == expect, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    lines = [line for line in result.stdout.splitlines() if line.strip().startswith("{")]
    assert lines, f"no JSON result; stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return json.loads(lines[-1])


def _connect(box: PgSandbox, database: str):
    return psycopg.connect(_dsn(database, box.role, box.password))


def _schema_tables(box: PgSandbox, database: str, schema: str) -> set[str]:
    with _connect(box, database) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
            (schema,),
        ).fetchall()
    return {row[0] for row in rows}


def _revision(box: PgSandbox, database: str, schema: str) -> str:
    with _connect(box, database) as conn:
        return conn.execute(
            sql.SQL("SELECT version_num FROM {}.alembic_version").format(sql.Identifier(schema))
        ).fetchone()[0]


@pytest.mark.parametrize("mode", ["database", "schema"])
def test_full_migration_activation_and_user_bound_pairing(pgbox, tmp_path, mode):
    env = pgbox.env(mode, tmp_path)
    result = _run(ACTIVATE_PAIR_PROBE, env)
    assert result["ready"] is True
    assert result["revision"] == HEAD
    assert result["installation_id"]
    assert result["device_id"]
    assert result["pairing_user"] == "00000000-0000-0000-0000-000000000123"

    database = pgbox.cp_db if mode == "database" else pgbox.business_db
    schema = "public" if mode == "database" else "roofspan_control_plane"
    assert REQUIRED_TABLES <= _schema_tables(pgbox, database, schema)
    assert _revision(pgbox, database, schema) == HEAD
    if mode == "schema":
        # No CP table may be created in the business/public schema by the fallback migration path.
        assert not ({"companies", "installations", "pairing_tokens", "mobile_devices"} &
                    _schema_tables(pgbox, pgbox.business_db, "public"))


def test_head_stamped_but_empty_legacy_schema_is_archived_and_rebuilt(pgbox, tmp_path):
    env = pgbox.env("schema", tmp_path)
    with _connect(pgbox, pgbox.business_db) as conn:
        conn.execute("CREATE SCHEMA roofspan_control_plane AUTHORIZATION CURRENT_USER")
        conn.execute("CREATE TABLE roofspan_control_plane.alembic_version (version_num varchar(32) PRIMARY KEY)")
        conn.execute("INSERT INTO roofspan_control_plane.alembic_version VALUES (%s)", (HEAD,))
        conn.commit()

    result = _run(MIGRATE_PROBE, env)
    report = result["report"]
    assert result["ok"] is True
    assert report["repair_action"] == "archived_zero_data_storage_and_rebuilt"
    assert report["archived_schema"].startswith("roofspan_control_plane_broken_")
    assert REQUIRED_TABLES <= _schema_tables(pgbox, pgbox.business_db, "roofspan_control_plane")
    assert _revision(pgbox, pgbox.business_db, "roofspan_control_plane") == HEAD
    with _connect(pgbox, pgbox.business_db) as conn:
        schemas = {r[0] for r in conn.execute("SELECT schema_name FROM information_schema.schemata").fetchall()}
    assert report["archived_schema"] in schemas


def test_complete_unversioned_schema_with_data_is_adopted_without_data_loss(pgbox, tmp_path):
    env = pgbox.env("schema", tmp_path)
    assert _run(MIGRATE_PROBE, env)["ok"] is True
    with _connect(pgbox, pgbox.business_db) as conn:
        conn.execute(
            "INSERT INTO roofspan_control_plane.companies (id, name, status, created_at) "
            "VALUES (%s, %s, %s, now())",
            (uuid.uuid4(), "Preserve Me", "ACTIVE"),
        )
        conn.execute("DROP TABLE roofspan_control_plane.alembic_version")
        conn.commit()

    result = _run(MIGRATE_PROBE, env)
    assert result["report"]["repair_action"] == "adopted_unversioned_storage"
    with _connect(pgbox, pgbox.business_db) as conn:
        count = conn.execute(
            "SELECT count(*) FROM roofspan_control_plane.companies WHERE name='Preserve Me'"
        ).fetchone()[0]
    assert count == 1
    assert _revision(pgbox, pgbox.business_db, "roofspan_control_plane") == HEAD


def test_inconsistent_schema_with_customer_data_fails_closed_and_preserves_rows(pgbox, tmp_path):
    env = pgbox.env("schema", tmp_path)
    company_id = uuid.uuid4()
    with _connect(pgbox, pgbox.business_db) as conn:
        conn.execute("CREATE SCHEMA roofspan_control_plane AUTHORIZATION CURRENT_USER")
        conn.execute("CREATE TABLE roofspan_control_plane.alembic_version (version_num varchar(32) PRIMARY KEY)")
        conn.execute("INSERT INTO roofspan_control_plane.alembic_version VALUES (%s)", (HEAD,))
        conn.execute("CREATE TABLE roofspan_control_plane.companies (id uuid PRIMARY KEY, name text NOT NULL)")
        conn.execute(
            "INSERT INTO roofspan_control_plane.companies (id, name) VALUES (%s, %s)",
            (company_id, "Do Not Delete"),
        )
        conn.commit()

    result = _run(MIGRATE_PROBE, env, expect=2)
    assert result["ok"] is False
    assert result["code"] == "manual_repair_required"
    with _connect(pgbox, pgbox.business_db) as conn:
        row = conn.execute(
            "SELECT name FROM roofspan_control_plane.companies WHERE id=%s", (company_id,)
        ).fetchone()
    assert row == ("Do Not Delete",)


def test_repeat_startup_is_idempotent_and_reuses_signing_key(pgbox, tmp_path):
    env = pgbox.env("schema", tmp_path)
    first = _run(ACTIVATE_PAIR_PROBE, env)
    assert first["ready"] is True
    with _connect(pgbox, pgbox.business_db) as conn:
        key_count_before = conn.execute(
            "SELECT count(*) FROM roofspan_control_plane.signing_keys"
        ).fetchone()[0]
    second = _run(MIGRATE_PROBE, env)
    assert second["report"]["state_before"] == "complete"
    assert second["report"]["repair_action"] is None
    with _connect(pgbox, pgbox.business_db) as conn:
        key_count_after = conn.execute(
            "SELECT count(*) FROM roofspan_control_plane.signing_keys"
        ).fetchone()[0]
    assert key_count_after == key_count_before
