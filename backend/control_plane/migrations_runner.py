"""Control Plane schema management via Alembic (replaces create_all as the authoritative path).

Handles three cases safely:
  - Fresh empty DB           -> upgrade to head (build full schema from history).
  - Existing pre-Alembic DB  -> stamp baseline (adopt current schema), then upgrade to head.
  - Already-managed DB       -> upgrade to head.

Kept separate from the business DB migrations. Startup validates readiness through this runner.
"""
import os
import time
import logging
from urllib.parse import urlparse, unquote

import psycopg
from psycopg import sql
from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory

from control_plane.config import CONTROL_PLANE_DATABASE_URL

logger = logging.getLogger("roofspan")
_ROOT = os.path.dirname(os.path.abspath(__file__))

# Bound every psycopg connection so a stuck server/network can never hang startup forever. lock_timeout
# guards accidental table/row locks (NOT advisory locks - those are handled by the try/deadline loop
# below); statement_timeout is generous so it never aborts a legitimately long migration.
_CONN_OPTIONS = "-c lock_timeout=30000 -c statement_timeout=120000 -c idle_in_transaction_session_timeout=120000"


def _conn_args() -> tuple[dict, str]:
    url = CONTROL_PLANE_DATABASE_URL.replace("+asyncpg", "").replace("+psycopg", "")
    p = urlparse(url)
    dbname = (p.path or "/").lstrip("/")
    return dict(host=p.hostname, port=p.port or 5432, user=unquote(p.username or ""),
                password=unquote(p.password or ""), connect_timeout=10, options=_CONN_OPTIONS), dbname


def ensure_database() -> None:
    args, dbname = _conn_args()
    try:
        with psycopg.connect(dbname=dbname, **args):
            return
    except psycopg.OperationalError as e:
        if "does not exist" not in str(e):
            raise RuntimeError(f"Control Plane DB unreachable: {e}") from e
    with psycopg.connect(dbname="postgres", autocommit=True, **args) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    logger.info("Created Control Plane database '%s'", dbname)


def _table_exists(name: str) -> bool:
    args, dbname = _conn_args()
    with psycopg.connect(dbname=dbname, **args) as conn:
        row = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)",
            (name,),
        ).fetchone()
        return bool(row and row[0])


def _config() -> Config:
    cfg = Config(os.path.join(_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_ROOT, "alembic"))
    return cfg


_MIGRATION_LOCK_KEY = 918273  # serialize concurrent CP migration runs (e.g., hot-reload workers)
# Bounded wait for the migration advisory lock. Advisory locks ignore lock_timeout, so we poll
# pg_try_advisory_lock() until a deadline instead of pg_advisory_lock() (which waits forever - the
# Railway startup hang, where a killed unhealthy container's backend still held the lock).
_LOCK_DEADLINE_S = int(os.environ.get("CP_MIGRATION_LOCK_TIMEOUT_S", "30"))


def _acquire_migration_lock(conn) -> None:
    deadline = time.monotonic() + _LOCK_DEADLINE_S
    logger.info("CP DB init: acquiring migration lock")
    while True:
        got = conn.execute("SELECT pg_try_advisory_lock(%s)", (_MIGRATION_LOCK_KEY,)).fetchone()
        if got and got[0]:
            logger.info("CP DB init: migration lock acquired")
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Control Plane migration lock not acquired within {_LOCK_DEADLINE_S}s; another "
                "migration/instance may be stuck holding it. Startup aborted (will be retried).")
        time.sleep(1)


def run_cp_migrations() -> None:
    logger.info("CP DB init: checking database connectivity")
    ensure_database()
    logger.info("CP DB init: database reachable")
    cfg = _config()
    args, dbname = _conn_args()
    # Serialize across processes so concurrent startups can't double-stamp/interleave.
    with psycopg.connect(dbname=dbname, autocommit=True, **args) as lock_conn:
        _acquire_migration_lock(lock_conn)
        try:
            logger.info("CP DB init: inspecting schema")
            if not _table_exists("alembic_version"):
                script = ScriptDirectory.from_config(cfg)
                if _table_exists("billing_events"):
                    logger.info("Adopting existing Control Plane DB at head")
                    command.stamp(cfg, "head")
                elif _table_exists("installations"):
                    base_rev = script.get_bases()[0]
                    logger.info("Adopting existing Control Plane DB at baseline %s", base_rev)
                    command.stamp(cfg, base_rev)
            logger.info("CP DB init: running Alembic upgrade")
            command.upgrade(cfg, "head")
            logger.info("CP DB init: Alembic upgrade complete")
        finally:
            lock_conn.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_KEY,))
            logger.info("CP DB init: migration lock released")
    logger.info("CP DB init: bootstrap complete")
    logger.info("Control Plane migrations applied (head)")
