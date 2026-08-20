import os
import sys
import logging
from urllib.parse import urlparse, unquote

import psycopg
from psycopg import sql
from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory

logger = logging.getLogger("roofspan")

# A released RoofSpan build wrote this revision into customer databases, but that migration file was
# later removed when the schema history was rebased to the current baseline. Never blindly stamp an
# arbitrary unknown revision: only explicitly-supported shipped legacy ids may be reconciled, and only
# after the live schema is fingerprinted against known migration milestones.
LEGACY_ORPHANED_REVISIONS = {"c1d2e3f4a5b6"}

REV_BASELINE = "61f7ea11c757"
REV_UNIQUE_MATERIAL = "7a95fb788bfd"
REV_PHOTOS = "e08723e6501e"
REV_ASSIGNED_USER = "53c1a6663c52"
REV_LICENSE_CACHE = "7d664e2b745d"

# These are deliberately high-signal tables from the current baseline. We require all of them before
# treating an orphaned Alembic revision as the old RoofSpan baseline; otherwise startup fails without
# mutating alembic_version or customer data.
BASELINE_SCHEMA_TABLES = {
    "app_config",
    "users",
    "customers",
    "properties",
    "materials",
    "leads",
    "jobs",
}


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


def _target_conn_args() -> dict:
    cfg = _parse_url()
    return dict(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        dbname=cfg["dbname"],
        connect_timeout=5,
    )


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


def _alembic_root() -> str:
    """Return the directory containing alembic.ini + alembic/ in source or PyInstaller ONEDIR."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _table_exists(conn, table: str) -> bool:
    return bool(conn.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",)).fetchone()[0])


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s AND column_name=%s
        )
        """,
        (table, column),
    ).fetchone()
    return bool(row[0])


def _materials_name_is_unique(conn) -> bool:
    # Accept either the current named constraint or an equivalent legacy unique index on materials(name).
    row = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_indexes
            WHERE schemaname='public'
              AND tablename='materials'
              AND indexdef ILIKE 'CREATE UNIQUE INDEX%%'
              AND regexp_replace(indexdef, '\\s+', ' ', 'g') ILIKE '%%(name)%%'
        )
        """
    ).fetchone()
    return bool(row[0])


def _current_alembic_revision(conn):
    if not _table_exists(conn, "alembic_version"):
        return None
    rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise RuntimeError(f"Expected exactly one alembic_version row, found {len(rows)}")
    return rows[0][0]


def _infer_legacy_revision_from_schema(conn) -> str:
    """Infer the highest current RoofSpan migration definitely represented by the live schema.

    This is intentionally conservative and monotonic: we only advance to a later migration when the
    schema marker for every earlier stage is also present. No business table or customer row is changed.
    """
    missing = sorted(t for t in BASELINE_SCHEMA_TABLES if not _table_exists(conn, t))
    if missing:
        raise RuntimeError(
            "Legacy RoofSpan migration revision cannot be reconciled safely because the database does "
            f"not match the released baseline; missing tables: {', '.join(missing)}"
        )

    revision = REV_BASELINE
    if not _materials_name_is_unique(conn):
        return revision

    revision = REV_UNIQUE_MATERIAL
    if not _table_exists(conn, "photos"):
        return revision

    revision = REV_PHOTOS
    if not (_column_exists(conn, "jobs", "assigned_user_id") and _column_exists(conn, "leads", "assigned_user_id")):
        return revision

    revision = REV_ASSIGNED_USER
    if not _table_exists(conn, "license_cache"):
        return revision

    return REV_LICENSE_CACHE


def _reconcile_orphaned_released_revision(script: ScriptDirectory) -> None:
    """Repair only explicitly-supported released revision ids whose migration file no longer exists.

    The old revision is replaced in alembic_version only after a schema fingerprint identifies the
    highest equivalent revision in the current chain. This preserves all tables/data and lets ordinary
    Alembic forward migrations apply anything that is genuinely missing.
    """
    known = {rev.revision for rev in script.walk_revisions()}
    with psycopg.connect(**_target_conn_args()) as conn:
        current = _current_alembic_revision(conn)
        if current is None or current in known:
            return
        if current not in LEGACY_ORPHANED_REVISIONS:
            raise RuntimeError(
                f"Database is stamped with unknown Alembic revision '{current}'. RoofSpan will not "
                "guess or rewrite migration history for an unrecognized database."
            )

        replacement = _infer_legacy_revision_from_schema(conn)
        logger.warning(
            "Detected released legacy Alembic revision %s; schema matches current revision %s. "
            "Repointing migration metadata only; customer tables/data are unchanged.",
            current,
            replacement,
        )
        with conn.transaction():
            updated = conn.execute(
                "UPDATE alembic_version SET version_num=%s WHERE version_num=%s",
                (replacement, current),
            ).rowcount
            if updated != 1:
                raise RuntimeError(
                    f"Failed to reconcile legacy Alembic revision '{current}': expected one metadata row, "
                    f"updated {updated}."
                )


def run_migrations() -> None:
    """Bring the database schema to the latest Alembic revision.

    Single authoritative schema path used at startup: it self-heals a missing database, reconciles only
    explicitly-supported released legacy migration ids, then builds a fresh database from full history or
    applies forward migrations non-destructively. Fails loudly if a migration cannot be applied.
    """
    ensure_database()
    root = _alembic_root()
    ini = os.path.join(root, "alembic.ini")
    script_location = os.path.join(root, "alembic")
    if not os.path.isfile(ini):
        raise RuntimeError(f"Alembic config is missing from the runtime bundle: {ini}")
    if not os.path.isdir(script_location):
        raise RuntimeError(f"Alembic migration directory is missing from the runtime bundle: {script_location}")

    cfg = Config(ini)
    cfg.set_main_option("script_location", script_location)
    # Programmatic startup owns process logging. alembic/env.py must not call fileConfig() and replace
    # the Windows service handlers while a migration is running.
    cfg.attributes["configure_logger"] = False

    # Force Alembic to load/validate the revision graph before upgrade and log only revision ids.
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    if not heads:
        raise RuntimeError("Alembic migration graph has no head revision")

    # Compatibility gate for databases created by previously released RoofSpan builds. This runs before
    # command.upgrade so Alembic never encounters an orphaned revision such as c1d2e3f4a5b6.
    _reconcile_orphaned_released_revision(script)

    logger.info("Alembic migration starting; head=%s", ",".join(heads))
    try:
        command.upgrade(cfg, "head")
    except Exception:
        logger.exception("Alembic migration failed")
        raise
    logger.info("Alembic migrations applied (head=%s)", ",".join(heads))
