"""First-run setup wizard — isolated happy-path against a scratch database.

Proves on an EMPTY database: status reports needs_setup=true, initialize creates the first owner
(role=owner) + company profile and returns a working session, the returned token authenticates, and a
SECOND initialize is refused (fail-closed). Uses a throwaway Postgres DB so the live owner is untouched.
"""
import os
import uuid
import asyncio

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import make_url, text

os.environ.setdefault("LICENSING_MODE", "dev")


def _scratch_url(base: str, name: str) -> str:
    return str(make_url(base).set(database=name))


def test_first_run_setup_happy_path():
    asyncio.run(_run())


async def _run():
    base = os.environ["DATABASE_URL"]
    admin_url = _scratch_url(base, "postgres")
    db_name = f"roofspan_setup_test_{uuid.uuid4().hex[:8]}"

    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin.dispose()

    scratch_url = _scratch_url(base, db_name)
    engine = create_async_engine(scratch_url)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        from db import Base, get_db
        from models import User, AppConfig, RefreshToken, AuditLog  # noqa: F401
        import server

        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[User.__table__, AppConfig.__table__, RefreshToken.__table__, AuditLog.__table__],
            )

        async def _override():
            async with Session() as s:
                yield s

        server.app.dependency_overrides[get_db] = _override
        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/setup/status")
            assert r.status_code == 200 and r.json()["needs_setup"] is True

            body = {
                "company": {"name": "Scratch Roofing Co.", "phone": "555", "email": "office@x.com",
                            "address": "1 A St", "license_number": "TX-1"},
                "owner_full_name": "First Owner",
                "owner_email": "First.Owner@Example.com",
                "owner_password": "SuperSecret123",
            }
            r = await client.post("/api/setup/initialize", json=body)
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["user"]["role"] == "owner"
            assert data["user"]["email"] == "first.owner@example.com"  # normalized lowercase
            assert data["access_token"]

            # status now flips to false
            r = await client.get("/api/setup/status")
            assert r.json()["needs_setup"] is False

            # returned token authenticates
            r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
            assert r.status_code == 200 and r.json()["email"] == "first.owner@example.com"

            # second initialize refused (fail-closed)
            r = await client.post("/api/setup/initialize", json=body)
            assert r.status_code == 409, r.text

            # company profile persisted
            async with Session() as s:
                row = (await s.execute(AppConfig.__table__.select().where(AppConfig.key == "company_profile"))).first()
                assert row is not None and row._mapping["value"]["name"] == "Scratch Roofing Co."
        server.app.dependency_overrides.pop(get_db, None)
    finally:
        await engine.dispose()
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as c:
            await c.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :n AND pid <> pg_backend_pid()"
            ), {"n": db_name})
            await c.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        await admin.dispose()
