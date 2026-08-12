"""P0 first-run onboarding E2E against a FRESH, isolated database (deterministic).

Run in isolation so the app engine binds to the throwaway DB:
    cd /app/backend && python -m pytest tests/test_onboarding.py -v -o addopts=""

Exercises the required P0 sequence: fresh/uninitialized -> bootstrap company+Owner -> restricted
pre-payment session (business blocked) -> initial 5-seat mock checkout -> restart-safe pending ->
mock payment success -> ACTIVE with EXACTLY 5 seats (Owner=1, 4 available) -> users 2..5 ok, 6th
blocked -> +1 seat -> 6th ok.
"""
import os
import uuid
import asyncio

# ---- Bind the app to a throwaway database BEFORE importing anything app-related ----
_DB = os.environ.get("DATABASE_URL", "postgresql+asyncpg://roofspan:roofspan_local_pwd@127.0.0.1:5432/roofspan")
_base = _DB.rsplit("/", 1)[0]
_FRESH = f"roofspan_onb_{uuid.uuid4().hex[:8]}"
os.environ["DATABASE_URL"] = f"{_base}/{_FRESH}"
os.environ["CONTROL_PLANE_DATABASE_URL"] = f"{_base}/{_FRESH}_cp"
os.environ["LICENSING_MODE"] = "dev"
os.environ["BILLING_MODE"] = "mock"
os.environ["ROOFSPAN_OWNER_SEED"] = "disabled"  # truly fresh: no seeded owner

import psycopg  # noqa: E402

_admin_dsn = "postgresql://roofspan:roofspan_local_pwd@127.0.0.1:5432/postgres"


def _create_db(name: str):
    with psycopg.connect(_admin_dsn, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{name}"')


def _drop_db(name: str):
    with psycopg.connect(_admin_dsn, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


from httpx import AsyncClient, ASGITransport  # noqa: E402


async def _flow():
    from server import app
    await app.router.startup()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1) Fresh install -> setup required
        r = await client.get("/api/setup/status")
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "setup_required"
        assert r.json()["owner_exists"] is False

        # 2) Business routes blocked before initialization (guard runs before routing)
        r = await client.get("/api/leads")
        assert r.status_code == 403 and r.json()["code"] == "setup_required", r.text

        # 3) Bootstrap company + Owner
        body = {
            "company": {"name": "Acme Roofing", "email": "office@acme.com", "phone": "555", "address": "1 Main"},
            "owner": {"full_name": "Jane Owner", "email": "jane@acme.com",
                      "password": "OwnerPass123", "confirm_password": "OwnerPass123"},
        }
        r = await client.post("/api/setup/bootstrap", json=body)
        assert r.status_code == 201, r.text
        token = r.json()["access_token"]
        assert r.json()["user"]["role"] == "owner"
        auth = {"Authorization": f"Bearer {token}"}

        # 4) Repeat bootstrap refused
        assert (await client.post("/api/setup/bootstrap", json=body)).status_code == 409

        # 5) Restricted pre-payment session: authenticated Owner still blocked from business
        r = await client.get("/api/leads", headers=auth)
        assert r.status_code == 403 and r.json()["code"] == "setup_required"

        # 6) Start initial 5-seat checkout
        r = await client.post("/api/setup/checkout", headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["seats"] == 5 and r.json()["monthly_price_usd"] == 245
        assert r.json()["checkout_url"]

        # 7) Payment pending
        assert (await client.get("/api/setup/payment-status", headers=auth)).json()["state"] == "payment_required"

        # 8) Restart safety: durable state survives a startup cycle; no re-bootstrap
        await app.router.shutdown()
        await app.router.startup()
        assert (await client.get("/api/setup/status")).json()["state"] == "payment_required"
        assert (await client.post("/api/setup/bootstrap", json=body)).status_code == 409
        r = await client.post("/api/auth/login", json={"email": "jane@acme.com", "password": "OwnerPass123"})
        assert r.status_code == 200
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 9) Simulate successful payment (mock)
        assert (await client.post("/api/setup/dev/pay", headers=auth)).status_code == 200
        r = await client.get("/api/setup/payment-status", headers=auth)
        assert r.json()["state"] == "initialized", r.text

        # 10) Activated with EXACTLY 5 seats: Owner=1 active, 4 available
        sub = (await client.get("/api/subscription", headers=auth)).json()
        assert sub["seats_licensed"] == 5, sub
        assert sub["active_users"] == 1 and sub["available_seats"] == 4

        # 11) Business now unlocked
        assert (await client.get("/api/leads", headers=auth)).status_code == 200

        # 12) Seat acceptance: users 2..5 ok, 6th blocked
        for i in range(2, 6):
            r = await client.post("/api/users", headers=auth, json={
                "email": f"user{i}@acme.com", "full_name": f"User {i}", "password": "UserPass123", "role": "sales"})
            assert r.status_code == 201, (i, r.text)
        r = await client.post("/api/users", headers=auth, json={
            "email": "user6@acme.com", "full_name": "User 6", "password": "UserPass123", "role": "sales"})
        assert r.status_code == 422, r.text  # seat limit

        # 13) +1 seat (mock/dev), then 6th user succeeds
        r = await client.post("/api/dev/licensing/set-state", headers=auth,
                              json={"state": "ACTIVE", "seats_licensed": 6})
        assert r.status_code == 200, r.text
        r = await client.post("/api/users", headers=auth, json={
            "email": "user6@acme.com", "full_name": "User 6", "password": "UserPass123", "role": "sales"})
        assert r.status_code == 201, r.text

        sub = (await client.get("/api/subscription", headers=auth)).json()
        assert sub["seats_licensed"] == 6 and sub["active_users"] == 6 and sub["available_seats"] == 0

    await app.router.shutdown()


def test_full_onboarding_flow():
    _create_db(_FRESH)
    _create_db(f"{_FRESH}_cp")
    try:
        asyncio.run(_flow())
    finally:
        _drop_db(_FRESH)
        _drop_db(f"{_FRESH}_cp")
