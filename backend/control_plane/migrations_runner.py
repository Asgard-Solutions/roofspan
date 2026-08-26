"""Control Plane schema management via Alembic (replaces create_all as the authoritative path).

Handles fresh, pre-Alembic, and managed CP storage. By default CP uses its own database. Legacy Windows
installs that cannot create the dedicated database may use CONTROL_PLANE_SCHEMA inside the existing
RoofSpan database; in that mode this runner never attempts CREATE DATABASE and scopes all table checks
and Alembic version state to that schema.
"""
import os
import logging
from urllib.parse import urlparse, unquote

import psycopg
from psycopg import sql
from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory

from control_plane.config import CONTROL_PLANE_DATABASE_URL, CONTROL_PLANE_SCHEMA

logger = logging.getLogger("roofspan")
_ROOT = os.path.dirname(os.path.abspath(__file__))


def _conn_args() -> tuple[dict, str]:
    url = CONTROL_PLANE_DATABASE_URL.replace("+asyncpg", "").replace("+psycopg", "")
    p = urlparse(url)
    dbname = (p.path or "/").lstrip("/")
    return dict(host=p.hostname, port=p.port or 5432, user=unquote(p.username or ""),
                password=unquote(p.password or ""), connect_timeout=5), dbname


def ensure_database() -> None:
    args, dbname = _conn_args()
    try:
        with psycopg.connect(dbname=dbname, **args):
            return
    except psycopg.OperationalError as e:
        if CONTROL_PLANE_SCHEMA:
            raise RuntimeError(f"Control Plane DB unreachable: {e}") from e
        if "does not exist" not in str(e):
            raise RuntimeError(f"Control Plane DB unreachable: {e}") from e
    with psycopg.connect(dbname="postgres", autocommit=True, **args) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    logger.info("Created Control Plane database '%s'", dbname)


def _table_exists(name: str) -> bool:
    args, dbname = _conn_args()
    schema = CONTROL_PLANE_SCHEMA or "public"
    with psycopg.connect(dbname=dbname, **args) as conn:
        row = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s)",
            (schema, name),
        ).fetchone()
        return bool(row and row[0])


def _config() -> Config:
    cfg = Config(os.path.join(_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_ROOT, "alembic"))
    if CONTROL_PLANE_SCHEMA:
        cfg.set_main_option("version_table_schema", CONTROL_PLANE_SCHEMA)
    return cfg


_MIGRATION_LOCK_KEY = 918273


def run_cp_migrations() -> None:
    ensure_database()
    cfg = _config()
    args, dbname = _conn_args()
    with psycopg.connect(dbname=dbname, autocommit=True, **args) as lock_conn:
        lock_conn.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK_KEY,))
        try:
            if CONTROL_PLANE_SCHEMA:
                lock_conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION CURRENT_USER").format(
                    sql.Identifier(CONTROL_PLANE_SCHEMA)))
            if not _table_exists("alembic_version"):
                script = ScriptDirectory.from_config(cfg)
                if _table_exists("billing_events"):
                    logger.info("Adopting existing Control Plane storage at head")
                    command.stamp(cfg, "head")
                elif _table_exists("installations"):
                    base_rev = script.get_bases()[0]
                    logger.info("Adopting existing Control Plane storage at baseline %s", base_rev)
                    command.stamp(cfg, base_rev)
            command.upgrade(cfg, "head")
        finally:
            lock_conn.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_KEY,))
    logger.info("Control Plane migrations applied (head%s)",
                f", schema={CONTROL_PLANE_SCHEMA}" if CONTROL_PLANE_SCHEMA else "")
