"""P1-3: token_version JWT invalidation (change-password via the app) + local Owner recovery tool logic,
against a FRESH isolated DB. Run in isolation:
    cd /app/backend && python -m pytest tests/test_token_recovery.py -o addopts="" -v
"""
import os
import sys
import uuid
import asyncio
import subprocess

_ISOLATED = os.environ.get("RS_ISOLATED") == "1"
_DB = os.environ.get("DATABASE_URL", "postgresql+asyncpg://roofspan:roofspan_local_pwd@127.0.0.1:5432/roofspan")
_base = _DB.rsplit("/", 1)[0]
_FRESH = f"roofspan_tok_{uuid.uuid4().hex[:8]}"
# Import-time env (throwaway DB) MUST only take effect inside the isolated child process (see
# _run_isolated) so it never rebinds the DB engine for the rest of the suite.
if _ISOLATED:
    os.environ["DATABASE_URL"] = f"{_base}/{_FRESH}"
    os.environ["CONTROL_PLANE_DATABASE_URL"] = f"{_base}/{_FRESH}_cp"
    os.environ["LICENSING_MODE"] = "dev"
    os.environ["BILLING_MODE"] = "mock"
    os.environ["ROOFSPAN_OWNER_SEED"] = "disabled"
    os.environ["ROOFSPAN_CONFIG_DIR"] = "/nonexistent-config"  # recovery tool must not find a stale .env

import psycopg  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "windows")))
from winbuild import owner_recovery as rec  # noqa: E402

_admin = "postgresql://roofspan:roofspan_local_pwd@127.0.0.1:5432/postgres"


def _run_isolated(nodeid: str) -> bool:
    """Run this DB-provisioning integration test in its OWN process so its import-time env (throwaway
    DB) takes effect and cannot contaminate — or be contaminated by — the rest of the suite. Returns
    True in the parent (child already ran + asserted); False inside the isolated child."""
    if _ISOLATED:
        return False
    r = subprocess.run(
        [sys.executable, "-m", "pytest", nodeid, "-o", "addopts=", "-q", "-p", "no:cacheprovider"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env={**os.environ, "RS_ISOLATED": "1"},
    )
    assert r.returncode == 0, f"isolated subprocess failed for {nodeid}"
    return True


def _drop(n):
    with psycopg.connect(_admin, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)')


def _mk(n):
    with psycopg.connect(_admin, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)'); c.execute(f'CREATE DATABASE "{n}"')


# ---- elevation (pure) ----

def test_is_elevated_requires_admin_or_override():
    os.environ.pop("ROOFSPAN_RECOVERY_ASSUME_ADMIN", None)
    assert rec.is_elevated() is False           # non-Windows, no override
    os.environ["ROOFSPAN_RECOVERY_ASSUME_ADMIN"] = "1"
    assert rec.is_elevated() is True
    os.environ.pop("ROOFSPAN_RECOVERY_ASSUME_ADMIN", None)


def test_main_rejects_when_not_elevated():
    os.environ.pop("ROOFSPAN_RECOVERY_ASSUME_ADMIN", None)
    assert rec.main() == 1                        # exits before any DB/prompt


def test_validate_password_rules():
    import pytest
    with pytest.raises(ValueError):
        rec.validate_password("abc12345", "different")
    with pytest.raises(ValueError):
        rec.validate_password("short", "short")
    rec.validate_password("goodpassword", "goodpassword")  # ok


# ---- DB-backed flow ----

async def _flow():
    from server import app
    await app.router.startup()
    from db import SessionLocal
    from models import User, AuditLog
    from core import verify_password
    from sqlalchemy import select, func

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # bootstrap owner (setup is allowlisted pre-init) -> token
        body = {"company": {"name": "Acme", "email": "o@acme.com"},
                "owner": {"full_name": "Jane", "email": "jane@acme.com",
                          "password": "OwnerPass123", "confirm_password": "OwnerPass123"}}
        r = await client.post("/api/setup/bootstrap", json=body)
        assert r.status_code == 201, r.text
        tok1 = r.json()["access_token"]
        h1 = {"Authorization": f"Bearer {tok1}"}
        assert (await client.get("/api/auth/me", headers=h1)).status_code == 200

        # change-password -> old token invalid, returned fresh token valid
        r = await client.post("/api/auth/change-password", headers=h1,
                              json={"current_password": "OwnerPass123", "new_password": "NewOwnerPass123"})
        assert r.status_code == 200, r.text
        tok2 = r.json()["access_token"]
        assert (await client.get("/api/auth/me", headers=h1)).status_code == 401  # OLD token rejected
        assert (await client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok2}"})).status_code == 200

        # ---- Owner recovery tool logic (direct, same DB) ----
        async with SessionLocal() as s:
            owners = await rec.find_owners(s)
            assert len(owners) == 1 and owners[0].role == "owner"
            owner = owners[0]
            v_before = owner.token_version
            # a non-owner must be refused by the recovery tool
            other = User(email="office@acme.com", full_name="Off", role="office",
                         password_hash=owners[0].password_hash, is_active=True)
            s.add(other); await s.flush()
            import pytest
            with pytest.raises(ValueError):
                await rec.reset_owner_password(s, other, "SomePass123")
            # reset the Owner
            await rec.reset_owner_password(s, owner, "RecoveredPass123")

        async with SessionLocal() as s:
            owner = (await s.execute(select(User).where(User.role == "owner"))).scalar_one()
            assert owner.token_version == v_before + 1              # sessions invalidated
            assert verify_password("RecoveredPass123", owner.password_hash)   # new works
            assert not verify_password("NewOwnerPass123", owner.password_hash)  # old fails
            audits = (await s.execute(select(AuditLog).where(AuditLog.action == "owner.recovery"))).scalars().all()
            assert len(audits) == 1
            assert "password" not in str(audits[0].detail).lower()  # no secret in audit detail

        # recovered owner can log in with the new password; the pre-recovery token is dead
        assert (await client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok2}"})).status_code == 401
        r = await client.post("/api/auth/login", json={"email": "jane@acme.com", "password": "RecoveredPass123"})
        assert r.status_code == 200
        assert (await client.get("/api/auth/me",
                headers={"Authorization": f"Bearer {r.json()['access_token']}"})).status_code == 200

    await app.router.shutdown()


def test_token_version_and_owner_recovery_flow():
    if _run_isolated("tests/test_token_recovery.py::test_token_version_and_owner_recovery_flow"):
        return
    _mk(_FRESH); _mk(f"{_FRESH}_cp")
    try:
        asyncio.run(_flow())
    finally:
        _drop(_FRESH); _drop(f"{_FRESH}_cp")
