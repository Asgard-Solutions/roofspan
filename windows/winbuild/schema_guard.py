"""Schema compatibility guard for the Windows backend (both Alembic trees).

Service start never migrates an existing database:
  * brand-new empty database (no business revision, no tables)  -> first-start migration (fresh install)
  * revision unknown to this build (newer schema)                -> refuse to start
  * known revision older than this build's head                  -> refuse to start (run RoofSpanSetup.exe)
Migrations for an existing database run only via `roofspan-backend.exe --migrate` (the upgrade coordinator).
"""
from __future__ import annotations


class SchemaGuardError(RuntimeError):
    pass


def _business() -> dict:
    import migrations_runner as mr
    import psycopg
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    root = mr._alembic_root()
    import os
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    script = ScriptDirectory.from_config(cfg)
    known = {r.revision for r in script.walk_revisions()} | set(getattr(mr, "LEGACY_ORPHANED_REVISIONS", ()))
    try:
        with psycopg.connect(**mr._target_conn_args()) as conn:
            current = mr._current_alembic_revision(conn)
            tables = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
    except psycopg.OperationalError as e:
        if "does not exist" in str(e):
            current, tables = None, 0
        else:
            raise
    return {"current": current, "heads": list(script.get_heads()), "known": current in known,
            "fresh": current is None and tables == 0}


def _control_plane() -> dict:
    from alembic.script import ScriptDirectory
    from control_plane import migrations_runner as cp
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    script = ScriptDirectory.from_config(cp._config())
    known = {r.revision for r in script.walk_revisions()}
    try:
        engine = create_engine(cp._sync_url(), poolclass=NullPool, future=True)
        try:
            with engine.connect() as connection:
                current = cp._read_revision(connection, cp.target_schema())
        finally:
            engine.dispose()
    except Exception as e:  # CP database not created yet
        if "does not exist" not in str(e):
            raise
        current = None
    return {"current": current, "heads": [cp.get_migration_head()], "known": current in known,
            "fresh": current is None}


def status() -> dict:
    return {"business": _business(), "control_plane": _control_plane()}


def heads_only() -> dict:
    from alembic.script import ScriptDirectory
    from control_plane import migrations_runner as cp
    return {"control_plane": [cp.get_migration_head()],
            "control_plane_known": sorted(r.revision for r in ScriptDirectory.from_config(cp._config()).walk_revisions())}


def enforce(logger) -> str:
    """Called at service start. Returns 'fresh' (migrated an empty DB) or 'current'; raises otherwise."""
    st = status()
    biz, cpt = st["business"], st["control_plane"]
    if biz["fresh"]:
        from control_plane.migrations_runner import run_cp_migrations
        from migrations_runner import run_migrations
        logger.info("schema guard: brand-new database; running first-start migrations")
        run_migrations()
        run_cp_migrations()
        return "fresh"
    problems = []
    for name, t in (("business", biz), ("control_plane", cpt)):
        if t["current"] is not None and not t["known"]:
            problems.append(f"{name} schema revision {t['current']} is newer than this build supports")
        elif t["current"] not in t["heads"]:
            problems.append(f"{name} schema revision {t['current']} is not this build's head {','.join(t['heads'])}")
    if problems:
        raise SchemaGuardError("schema guard: refusing to start: " + "; ".join(problems) +
                               ". Run RoofSpanSetup.exe to upgrade (or restore) RoofSpan Office.")
    logger.info("schema guard: business=%s control_plane=%s (at head)", biz["current"], cpt["current"])
    return "current"


def migrate(logger) -> dict:
    from control_plane.migrations_runner import run_cp_migrations
    from migrations_runner import run_migrations
    logger.info("migrate: business schema")
    run_migrations()
    logger.info("migrate: control plane schema")
    run_cp_migrations()
    return status()
