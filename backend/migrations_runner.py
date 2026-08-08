import os
import logging
from urllib.parse import urlparse, unquote

import psycopg
from psycopg import sql
from alembic.config import Config
from alembic import command

logger = logging.getLogger("roofspan")


def _parse_url() -> dict:
    raw = os.environ["DATABASE_URL"]
    # strip SQLAlchemy driver suffixes so urlparse sees a plain postgres URL
    clean = raw.replace("+asyncpg", "").replace("+psycopg", "")
    p = urlparse(clean)
    return {
        "host": p.hostname,
        "port": p.port or 5432,
        "user": unquote(p.username) if p.username else None,
        "password": unquote(p.password) if p.password else None,
        "dbname": (p.path or "/").lstrip("/"),
    }


def ensure_database() -> None:
    """Fail loudly (fast) if PostgreSQL is unreachable, and self-heal a missing database.

    - If the target database is reachable -> return.
    - If it is missing but the role can reach the server -> CREATE it (role needs CREATEDB).
    - If the server/role is unreachable -> raise an actionable error instead of hanging.
    """
    cfg = _parse_url()
    dbname = cfg["dbname"]
    conn_args = dict(host=cfg["host"], port=cfg["port"], user=cfg["user"], password=cfg["password"], connect_timeout=5)

    try:
        with psycopg.connect(dbname=dbname, **conn_args):
            return
    except psycopg.OperationalError as e:
        msg = str(e)
        missing_db = ("does not exist" in msg) and (f'"{dbname}"' in msg or "database" in msg.lower())
        if not missing_db:
            raise RuntimeError(
                f"Cannot connect to PostgreSQL at {cfg['host']}:{cfg['port']} as role '{cfg['user']}'. "
                f"Ensure the server is running and the role exists (see /app/OPERATIONS.md bootstrap). "
                f"Original error: {msg}"
            ) from e

    logger.warning("Database '%s' is missing; creating it now.", dbname)
    try:
        with psycopg.connect(dbname="postgres", autocommit=True, **conn_args) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
        logger.info("Created database '%s'.", dbname)
    except psycopg.Error as e:
        raise RuntimeError(
            f"Database '{dbname}' is missing and could not be auto-created. The role '{cfg['user']}' must have "
            f"CREATEDB, or run the one-time bootstrap in /app/OPERATIONS.md. Original error: {e}"
        ) from e


def run_migrations() -> None:
    """Bring the database schema to the latest Alembic revision.

    Single authoritative schema path used at startup: it self-heals a missing database, then
    builds a fresh database from full history or applies forward migrations non-destructively.
    Fails loudly if a migration cannot be applied.
    """
    ensure_database()
    root = os.path.dirname(os.path.abspath(__file__))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    command.upgrade(cfg, "head")
    logger.info("Alembic migrations applied (head)")
