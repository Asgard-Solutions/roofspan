"""P1-4b: production trust-boundary tests for initial-onboarding billing.

Proves the customer-installed Office backend NEVER instantiates the Stripe provider and NEVER needs
STRIPE_SECRET_KEY: in production (LICENSING_MODE=http) /api/setup/checkout goes through the central
Control Plane client, raw provider errors are not leaked to the customer, and /dev/pay is DEV-only.

Run in isolation (binds the app to a throwaway DB):
    cd /app/backend && python -m pytest tests/test_setup_billing_boundary.py -v -o addopts=""
"""
import os
import uuid
import asyncio

_DB = os.environ.get("DATABASE_URL", "postgresql+asyncpg://roofspan:roofspan_local_pwd@127.0.0.1:5432/roofspan")
_base = _DB.rsplit("/", 1)[0]
_FRESH = f"roofspan_p14b_{uuid.uuid4().hex[:8]}"
os.environ["DATABASE_URL"] = f"{_base}/{_FRESH}"
os.environ["CONTROL_PLANE_DATABASE_URL"] = f"{_base}/{_FRESH}_cp"
os.environ["LICENSING_MODE"] = "http"                       # PRODUCTION-style client
os.environ["LICENSING_CONTROL_PLANE_URL"] = "https://cp.roofspan.io/api/control-plane"
os.environ["ROOFSPAN_OWNER_SEED"] = "disabled"
os.environ.pop("STRIPE_SECRET_KEY", None)                   # local backend must NOT require this
os.environ.pop("STRIPE_WEBHOOK_SECRET", None)

import psycopg  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402

_admin_dsn = "postgresql://roofspan:roofspan_local_pwd@127.0.0.1:5432/postgres"


def _create_db(name):
    with psycopg.connect(_admin_dsn, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{name}"')


def _drop_db(name):
    with psycopg.connect(_admin_dsn, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


async def _bootstrap_owner(client):
    body = {
        "company": {"name": "Acme Roofing", "email": "office@acme.com", "phone": "555", "address": "1 Main"},
        "owner": {"full_name": "Jane Owner", "email": "jane@acme.com",
                  "password": "OwnerPass123", "confirm_password": "OwnerPass123"},
    }
    r = await client.post("/api/setup/bootstrap", json=body)
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _flow():
    import logging as _lg
    _lg.getLogger("roofspan.setup").setLevel(_lg.CRITICAL)   # keep test output clean
    import licensing.control_plane as lic_cp
    from control_plane import billing as cp_billing
    from server import app

    # Poison the local Stripe provider: if the LOCAL backend ever tries to construct it, fail loudly.
    def _forbidden(self, *a, **k):
        raise AssertionError("LOCAL backend must NOT instantiate StripeBillingProvider")
    cp_billing.StripeBillingProvider.__init__ = _forbidden  # type: ignore

    # Stub the central Control Plane client so no network/identity is needed. This is exactly the
    # boundary: the local backend only relays through the client.
    calls = {"activate": 0, "checkout": 0}

    async def _fake_activate(self, db, *, company_name=None, requested_seats=None):
        calls["activate"] += 1
        calls["company_name"] = company_name
        calls["requested_seats"] = requested_seats
        # New boundary: the client returns the CP-assigned identity + entitlement; local persistence is
        # done by licensing.service.persist_activation (adopts ids, marks activated, caches entitlement).
        return {"installation_id": "inst-123", "company_id": "co-abc", "license_id": "lic-1",
                "entitlement_jws": None, "signing_public_keys": {}}

    async def _fake_checkout(self, db, *, company_id, installation_id=None, seats=None):
        calls["checkout"] += 1
        assert installation_id and isinstance(installation_id, str)   # installation-authenticated
        assert seats == 5                              # initial minimum
        return {"checkout_url": "https://checkout.stripe.com/c/pay/cs_test_123",
                "company_id": company_id, "seats": 5, "monthly_price_usd": 245}

    lic_cp.HttpControlPlaneClient.activate = _fake_activate            # type: ignore
    lic_cp.HttpControlPlaneClient.create_initial_checkout = _fake_checkout  # type: ignore

    await app.router.startup()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        auth = await _bootstrap_owner(client)

        # Production checkout: goes through the central client; returns the hosted URL. No STRIPE_SECRET_KEY,
        # no local StripeBillingProvider.
        r = await client.post("/api/setup/checkout", headers=auth)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["checkout_url"].startswith("https://checkout.stripe.com/"), j
        assert j["seats"] == 5 and j["monthly_price_usd"] == 245
        assert calls["checkout"] == 1
        # Activation happened exactly once, with the REAL company name + initial 5 seats.
        assert calls["activate"] == 1
        assert calls["company_name"] == "Acme Roofing" and calls["requested_seats"] == 5

        # Idempotent: a second click reuses the pending checkout (no second central call).
        r2 = await client.post("/api/setup/checkout", headers=auth)
        assert r2.status_code == 200 and r2.json()["checkout_url"] == j["checkout_url"]
        assert calls["checkout"] == 1, "repeated checkout must reuse the pending session"

        # /dev/pay is DEV-only -> forbidden in production (LICENSING_MODE=http).
        assert (await client.post("/api/setup/dev/pay", headers=auth)).status_code == 403

        # Customer-safe error: force the central call to raise a Stripe-flavoured exception; the UI must
        # get a generic message with NO secret/exception text.
        async def _boom(self, db, *, company_id, installation_id=None, seats=None):
            raise RuntimeError("Stripe is not configured (STRIPE_SECRET_KEY missing)")
        lic_cp.HttpControlPlaneClient.create_initial_checkout = _boom  # type: ignore
        # Clear the pending checkout so the call is re-attempted.
        import onboarding
        from db import SessionLocal
        async with SessionLocal() as db:
            rec = await onboarding.get_record(db)
            await onboarding.set_record(db, {**rec, "state": onboarding.OWNER_CREATED,
                                             "checkout_url": None})
        r = await client.post("/api/setup/checkout", headers=auth)
        assert r.status_code == 502, r.text
        detail = r.json()["detail"]
        assert detail == "Unable to start subscription checkout. Please try again in a moment."
        assert "STRIPE" not in detail.upper() and "SECRET" not in detail.upper()

    await app.router.shutdown()


def test_production_billing_boundary():
    _create_db(_FRESH)
    _create_db(f"{_FRESH}_cp")
    try:
        asyncio.run(_flow())
    finally:
        _drop_db(_FRESH)
        _drop_db(f"{_FRESH}_cp")


def test_setup_module_does_not_import_stripe_provider_at_module_scope():
    # The local setup router must not statically import the Stripe billing provider.
    src = open(os.path.join(os.path.dirname(__file__), "..", "routers", "setup.py")).read()
    assert "StripeBillingProvider" not in src
    assert "from control_plane import billing" not in src   # no direct local provider usage
    assert 'str(e)[:200]' not in src                        # no raw exception leakage to the UI
