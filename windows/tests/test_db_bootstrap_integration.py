r"""REAL PostgreSQL integration test for the first-install DB bootstrap.

This executes the ACTUAL windows/winbuild/db_bootstrap._ensure_role_and_db() against a live PostgreSQL
(NOT a mock) and proves the fresh CREATE-ROLE branch and the existing-role/no-config ALTER-ROLE branch.

It runs only when ROOFSPAN_TEST_PG_DSN points at a reachable superuser connection, e.g.:
    ROOFSPAN_TEST_PG_DSN="postgresql://postgres:superpw123@127.0.0.1:5433/postgres"
(The windows-latest services-install-smoke job proves the full clean-install path end to end; this test
is the isolated, driver-real proof and also runs in the container CI where a Postgres is provided.)
"""
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

WINBUILD = Path(__file__).resolve().parents[1] / "winbuild"
sys.path.insert(0, str(WINBUILD))

import db_bootstrap as boot  # noqa: E402

DSN = os.environ.get("ROOFSPAN_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set ROOFSPAN_TEST_PG_DSN to run the real Postgres bootstrap test")


class _Logger:
    def info(self, *a, **k):
        pass


def _super_conn_kwargs():
    u = urlparse(DSN)
    return dict(user=u.username, password=u.password, host=u.hostname, port=u.port or 5432, database="postgres")


async def _run(coro):
    return await coro


def _reset(asyncpg):
    async def go():
        conn = await asyncpg.connect(**_super_conn_kwargs())
        try:
            await conn.execute("DROP DATABASE IF EXISTS roofspan")
            await conn.execute("DROP ROLE IF EXISTS roofspan")
        finally:
            await conn.close()
    asyncio.get_event_loop().run_until_complete(go())


def _inspect(asyncpg):
    async def go():
        conn = await asyncpg.connect(**_super_conn_kwargs())
        try:
            row = await conn.fetchrow(
                "SELECT rolcanlogin, rolsuper FROM pg_roles WHERE rolname='roofspan'")
            owner = await conn.fetchval(
                "SELECT pg_catalog.pg_get_userbyid(datdba) FROM pg_database WHERE datname='roofspan'")
            return row, owner
        finally:
            await conn.close()
    return asyncio.get_event_loop().run_until_complete(go())


def _can_login(asyncpg, password):
    async def go():
        kw = _super_conn_kwargs()
        conn = await asyncpg.connect(user="roofspan", password=password, host=kw["host"],
                                     port=kw["port"], database="roofspan")
        try:
            return await conn.fetchval("SELECT current_user")
        finally:
            await conn.close()
    return asyncio.get_event_loop().run_until_complete(go())


def test_fresh_create_then_existing_alter_branch():
    import asyncpg

    u = urlparse(DSN)
    boot.PG_HOST = u.hostname
    boot.PG_PORT = u.port or 5432
    super_pw = u.password
    _reset(asyncpg)

    # ---- CREATE ROLE branch (fresh: no role, no db) ----
    pw1 = boot.generate_db_password(exclude=super_pw)
    asyncio.get_event_loop().run_until_complete(boot._ensure_role_and_db(super_pw, pw1, _Logger()))
    row, owner = _inspect(asyncpg)
    assert row is not None, "role roofspan must exist"
    assert row["rolcanlogin"] is True, "roofspan must be a LOGIN role"
    assert row["rolsuper"] is False, "roofspan must NOT be a superuser"
    assert owner == "roofspan", "database roofspan must be owned by roofspan"
    assert _can_login(asyncpg, pw1) == "roofspan", "generated password must authenticate"

    # ---- ALTER ROLE branch (role already exists, no valid config -> new password set) ----
    pw2 = boot.generate_db_password(exclude=pw1)
    assert pw2 != pw1
    asyncio.get_event_loop().run_until_complete(boot._ensure_role_and_db(super_pw, pw2, _Logger()))
    row2, owner2 = _inspect(asyncpg)
    assert row2["rolcanlogin"] is True and row2["rolsuper"] is False
    assert owner2 == "roofspan"
    assert _can_login(asyncpg, pw2) == "roofspan", "ALTER ROLE must set the new generated password"

    _reset(asyncpg)
