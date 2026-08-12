"""First-install local PostgreSQL + deployed-config bootstrap for RoofSpan Office.

Runs ONCE during installation (WiX custom action `RoofSpanBootstrap`, sequenced BEFORE StartServices), so
RoofSpanBackend never starts before its database credentials exist. It:
  1. generates a unique, random local DB application password (never committed/logged),
  2. creates/configures the least-privilege `roofspan` role + `roofspan` database (via the bundled
     PostgreSQL superuser password passed by the bundle),
  3. renders the shipped roofspan.env TEMPLATE into the DEPLOYED
     C:\\ProgramData\\RoofSpan\\config\\roofspan.env with the real local DATABASE_URL.
Idempotent / upgrade-safe: if a deployed config already exists it is PRESERVED (creds not regenerated).
Native psql/role/db execution is HUMAN REQUIRED; the pure logic below is unit-tested in-container.
"""
from __future__ import annotations

import os
import secrets
import subprocess

PLACEHOLDER = "__GENERATED_AT_FIRST_RUN__"
DEFAULT_TEMPLATE = r"C:\Program Files\RoofSpan Office\config-templates\roofspan.env"
DEFAULT_DEPLOYED = r"C:\ProgramData\RoofSpan\config\roofspan.env"
DB_NAME = "roofspan"
DB_ROLE = "roofspan"


def generate_db_password(nbytes: int = 32) -> str:
    """Random, unique-per-installation local DB password (URL-safe, no shell-hostile chars)."""
    return secrets.token_urlsafe(nbytes)


def render_deployed_env(template_text: str, db_password: str) -> str:
    rendered = template_text.replace(PLACEHOLDER, db_password)
    if PLACEHOLDER in rendered:
        raise ValueError("template placeholder was not fully substituted")
    return rendered


def write_deployed_config(template_path: str, deployed_path: str, db_password: str) -> str:
    """Fresh install: render template -> deployed config with the real DATABASE_URL. Upgrade/repair: keep
    the existing deployed config (preserve credentials). Returns the deployed path."""
    if os.path.isfile(deployed_path):
        return deployed_path  # preserve customer creds across upgrade/repair
    with open(template_path, "r", encoding="utf-8") as f:
        rendered = render_deployed_env(f.read(), db_password)
    os.makedirs(os.path.dirname(deployed_path), exist_ok=True)
    with open(deployed_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    try:
        os.chmod(deployed_path, 0o600)
    except OSError:
        pass
    return deployed_path


def _psql(super_password: str, sql: str, dbname: str = "postgres") -> None:
    env = {**os.environ, "PGPASSWORD": super_password}
    subprocess.run(["psql", "-h", "127.0.0.1", "-U", "postgres", "-d", dbname, "-v", "ON_ERROR_STOP=1",
                    "-c", sql], check=True, env=env)


def provision_database(super_password: str, db_password: str) -> None:  # pragma: no cover (native)
    """Create the least-privilege role + database if absent. HUMAN REQUIRED on Windows."""
    _psql(super_password, f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{DB_ROLE}') "
                          f"THEN CREATE ROLE {DB_ROLE} LOGIN PASSWORD '{db_password}'; END IF; END $$;")
    _psql(super_password, f"ALTER ROLE {DB_ROLE} WITH PASSWORD '{db_password}';")
    exists = subprocess.run(["psql", "-h", "127.0.0.1", "-U", "postgres", "-tAc",
                             f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}'"],
                            env={**os.environ, "PGPASSWORD": super_password}, capture_output=True, text=True)
    if exists.stdout.strip() != "1":
        _psql(super_password, f"CREATE DATABASE {DB_NAME} OWNER {DB_ROLE};")


def main() -> int:  # pragma: no cover (native install-time)
    template = os.environ.get("ROOFSPAN_CONFIG_TEMPLATE", DEFAULT_TEMPLATE)
    deployed = os.environ.get("ROOFSPAN_DEPLOYED_CONFIG", DEFAULT_DEPLOYED)
    super_pw = os.environ.get("ROOFSPAN_PG_SUPERPASSWORD", "")
    if os.path.isfile(deployed):
        return 0  # upgrade/repair: preserve existing creds + config
    db_pw = generate_db_password()
    if super_pw:
        provision_database(super_pw, db_pw)
    write_deployed_config(template, deployed, db_pw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
