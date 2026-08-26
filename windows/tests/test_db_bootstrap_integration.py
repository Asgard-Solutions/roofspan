r"""REAL PostgreSQL integration test for the first-install DB bootstrap.

This executes the ACTUAL windows/winbuild/db_bootstrap._ensure_role_and_db() against a live PostgreSQL
(NOT a mock) and proves the fresh CREATE-ROLE branch and the existing-role/no-config ALTER-ROLE branch.
It validates both databases now owned by the least-privilege RoofSpan role.
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
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="set ROOFSPAN_TEST_PG_DSN to run the real Postgres bootstrap test",
)


class _Logger:
    def info(self, *args, **kwargs):
        pass


def _super_conn_kwargs():
    parsed = urlparse(DSN)
    return dict(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database="postgres",
    )


def _reset(asyncpg):
    async def go():
        conn = await asyncpg.connect(**_super_conn_kwargs())
        try:
            # Drop every DB owned by the test role before dropping the role. The Control Plane bootstrap
            # added a second database, so deleting only `roofspan` leaves a dependent owner object.
            for database in (boot.CP_DB, boot.APP_DB):
                await conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=$1 AND pid <> pg_backend_pid()",
                    database,
                )
                await conn.execute(f'DROP DATABASE IF EXISTS "{database}"')
            await conn.execute(f'DROP ROLE IF EXISTS "{boot.APP_ROLE}"')
        finally:
            await conn.close()

    asyncio.get_event_loop().run_until_complete(go())


def _inspect(asyncpg):
    async def go():
        conn = await asyncpg.connect(**_super_conn_kwargs())
        try:
            row = await conn.fetchrow(
                "SELECT rolcanlogin, rolsuper, rolcreatedb FROM pg_roles WHERE rolname=$1",
                boot.APP_ROLE,
            )
            owners = {}
            for database in (boot.APP_DB, boot.CP_DB):
                owners[database] = await conn.fetchval(
                    "SELECT pg_catalog.pg_get_userbyid(datdba) FROM pg_database WHERE datname=$1",
                    database,
                )
            return row, owners
        finally:
            await conn.close()

    return asyncio.get_event_loop().run_until_complete(go())


def _can_login(asyncpg, password, database):
    async def go():
        kwargs = _super_conn_kwargs()
        conn = await asyncpg.connect(
            user=boot.APP_ROLE,
            password=password,
            host=kwargs["host"],
            port=kwargs["port"],
            database=database,
        )
        try:
            return await conn.fetchval("SELECT current_user")
        finally:
            await conn.close()

    return asyncio.get_event_loop().run_until_complete(go())


def _assert_bootstrap_state(asyncpg, password):
    role, owners = _inspect(asyncpg)
    assert role is not None, "role roofspan must exist"
    assert role["rolcanlogin"] is True, "roofspan must be a LOGIN role"
    assert role["rolsuper"] is False, "roofspan must NOT be a superuser"
    assert role["rolcreatedb"] is False, "roofspan must NOT have CREATEDB"
    assert owners == {
        boot.APP_DB: boot.APP_ROLE,
        boot.CP_DB: boot.APP_ROLE,
    }
    assert _can_login(asyncpg, password, boot.APP_DB) == boot.APP_ROLE
    assert _can_login(asyncpg, password, boot.CP_DB) == boot.APP_ROLE


def test_fresh_create_then_existing_alter_branch():
    import asyncpg

    parsed = urlparse(DSN)
    boot.PG_HOST = parsed.hostname
    boot.PG_PORT = parsed.port or 5432
    super_password = parsed.password
    _reset(asyncpg)

    try:
        # CREATE ROLE + both DBs on a fresh installation.
        password1 = boot.generate_db_password(exclude=super_password)
        asyncio.get_event_loop().run_until_complete(
            boot._ensure_role_and_db(super_password, password1, _Logger())
        )
        _assert_bootstrap_state(asyncpg, password1)

        # Existing role/DB branch rotates only the requested bootstrap credential and preserves both DBs.
        password2 = boot.generate_db_password(exclude=password1)
        assert password2 != password1
        asyncio.get_event_loop().run_until_complete(
            boot._ensure_role_and_db(super_password, password2, _Logger())
        )
        _assert_bootstrap_state(asyncpg, password2)
    finally:
        _reset(asyncpg)
