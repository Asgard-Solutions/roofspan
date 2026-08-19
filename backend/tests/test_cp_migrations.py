"""Railway CP database URL parsing + bounded migration-lock behavior tests.

URL tests are pure parsing (no Railway DNS). Lock tests are BEHAVIORAL against the local Postgres.
Run: cd /app/backend && python -m pytest tests/test_cp_migrations.py -o addopts='' -q
"""
import os

import psycopg
import pytest

# Bound the migration lock quickly for the contention test BEFORE importing the module.
os.environ["CP_MIGRATION_LOCK_TIMEOUT_S"] = "3"

import control_plane.config as cfg
import control_plane.migrations_runner as mr


RAILWAY_URL = "postgresql://user:p%40ss%2Fword@postgres.railway.internal:5432/railway"


def test_async_url_normalization_railway_form():
    assert cfg._normalize_async(RAILWAY_URL) == \
        "postgresql+asyncpg://user:p%40ss%2Fword@postgres.railway.internal:5432/railway"
    assert cfg._normalize_async("postgres://u:p@h:5432/db") == "postgresql+asyncpg://u:p@h:5432/db"


def test_alembic_sync_url_uses_psycopg_driver():
    # Mirror env.py._sync_url(): normalize then swap to the psycopg (sync) driver.
    sync = cfg._normalize_async(RAILWAY_URL).replace("+asyncpg", "+psycopg")
    assert sync.startswith("postgresql+psycopg://")
    assert "postgres.railway.internal:5432/railway" in sync


def test_raw_psycopg_args_parse_railway_url_with_encoded_password(monkeypatch):
    monkeypatch.setattr(mr, "CONTROL_PLANE_DATABASE_URL",
                        "postgresql+asyncpg://user:p%40ss%2Fword@postgres.railway.internal:5432/railway")
    args, dbname = mr._conn_args()
    assert dbname == "railway"
    assert args["host"] == "postgres.railway.internal"
    assert args["port"] == 5432
    assert args["user"] == "user"
    assert args["password"] == "p@ss/word"      # URL-decoded
    assert args["connect_timeout"] == 10
    assert "statement_timeout" in args["options"] and "lock_timeout" in args["options"]


# ---- behavioral lock tests (local Postgres) ----
_LOCAL = dict(host="127.0.0.1", port=5432, user="roofspan", password="roofspan_local_pwd", dbname="roofspan")


def _conn():
    return psycopg.connect(autocommit=True, connect_timeout=5, **_LOCAL)


def test_migration_lock_is_bounded_and_raises_on_contention():
    holder = _conn()
    holder.execute("SELECT pg_advisory_lock(%s)", (mr._MIGRATION_LOCK_KEY,))
    try:
        import time
        waiter = _conn()
        t0 = time.monotonic()
        with pytest.raises(RuntimeError, match="migration lock not acquired"):
            mr._acquire_migration_lock(waiter)     # deadline = 3s (env above)
        elapsed = time.monotonic() - t0
        assert 3 <= elapsed < 15, f"lock wait must be bounded, took {elapsed:.1f}s"
        waiter.close()
    finally:
        holder.execute("SELECT pg_advisory_unlock(%s)", (mr._MIGRATION_LOCK_KEY,))
        holder.close()


def test_migration_lock_acquires_and_releases_when_free():
    c = _conn()
    try:
        mr._acquire_migration_lock(c)              # should succeed immediately
        # verify it is actually held by this session
        held = c.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()").fetchone()
        assert held[0] >= 1
        c.execute("SELECT pg_advisory_unlock(%s)", (mr._MIGRATION_LOCK_KEY,))
        after = c.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()").fetchone()
        assert after[0] == 0                       # released cleanly
    finally:
        c.close()
