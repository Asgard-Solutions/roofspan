"""Production first-run activation: an Office installation must register with the Control Plane and
adopt the CP-assigned identity BEFORE entitlement refresh or Stripe checkout.

Reproduces the live failure (locally-generated ids used for signed CP requests -> 404 "Unknown
installation") and proves the fix end to end WITHOUT any network (the CP client is stubbed).

Run in isolation (throwaway DB):
    cd /app/backend && python -m pytest tests/test_setup_activation.py -v -o addopts=""
"""
import os
import uuid
import asyncio
import sys
import subprocess
from datetime import datetime, timezone, timedelta

_ISOLATED = os.environ.get("RS_ISOLATED") == "1"
_DB = os.environ.get("DATABASE_URL", "postgresql+asyncpg://roofspan:roofspan_local_pwd@127.0.0.1:5432/roofspan")
_base = _DB.rsplit("/", 1)[0]
_FRESH = f"roofspan_act_{uuid.uuid4().hex[:8]}"
# Import-time env (throwaway DB + http licensing mode) MUST only take effect inside the isolated
# child process (see _run_isolated) so it never rebinds the DB engine / licensing mode for the rest
# of the suite. In the parent process the DB-provisioning test simply re-execs itself in isolation.
if _ISOLATED:
    os.environ["DATABASE_URL"] = f"{_base}/{_FRESH}"
    os.environ["CONTROL_PLANE_DATABASE_URL"] = f"{_base}/{_FRESH}_cp"
    os.environ["LICENSING_MODE"] = "http"
    os.environ["LICENSING_CONTROL_PLANE_URL"] = "https://cp.roofspan.io/api/control-plane"
    os.environ["ROOFSPAN_OWNER_SEED"] = "disabled"
    os.environ["INSTALLATION_KEYS_DIR"] = f"/tmp/rs_ident_{uuid.uuid4().hex[:8]}"

import psycopg  # noqa: E402

_admin_dsn = "postgresql://roofspan:roofspan_local_pwd@127.0.0.1:5432/postgres"


def _run_isolated(nodeid: str) -> bool:
    """Run a DB-provisioning integration test in its OWN process so its import-time env (throwaway DB
    + http licensing mode) takes effect and cannot contaminate — or be contaminated by — the rest of
    the suite. Returns True in the parent (child already ran + asserted); False inside the child."""
    if _ISOLATED:
        return False
    r = subprocess.run(
        [sys.executable, "-m", "pytest", nodeid, "-o", "addopts=", "-q", "-p", "no:cacheprovider"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env={**os.environ, "RS_ISOLATED": "1"},
    )
    assert r.returncode == 0, f"isolated subprocess failed for {nodeid}"
    return True


def _create_db(name):
    with psycopg.connect(_admin_dsn, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{name}"')


def _drop_db(name):
    with psycopg.connect(_admin_dsn, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _make_activation_data(installation_id, company_id, license_id, state="ACTIVE", seats=5):
    """Canned Control-Plane activation response with a REAL signed entitlement (dev signer) so the
    local persist path verifies it exactly like a production entitlement."""
    from licensing import keys as lkeys, entitlement as ent, config as lcfg
    kid, priv = lkeys.get_dev_signing_key()
    now = datetime.now(timezone.utc)
    claims = {
        "installation_id": installation_id, "company_id": company_id, "license_id": license_id,
        "subscription_state": state, "seats_licensed": seats, "product": lcfg.PRODUCT,
        "min_supported_version": lcfg.MIN_SUPPORTED_VERSION, "issued_at": now,
        "refresh_at": now + timedelta(hours=12), "grace_until": now + timedelta(days=7),
        "nonce": uuid.uuid4().hex,
    }
    token = ent.sign_entitlement(private_key=priv, kid=kid, claims=claims)
    with open(lkeys._pub_path, "rb") as f:
        pub_pem = f.read().decode()
    return {"installation_id": installation_id, "company_id": company_id, "license_id": license_id,
            "entitlement_jws": token, "signing_public_keys": {kid: pub_pem}}


async def _flow():
    from server import app
    from db import SessionLocal
    from models import AppConfig, LicenseCache
    import licensing.service as svc
    import licensing.control_plane as lic_cp
    from routers.setup import _ensure_installation_identity
    from sqlalchemy import select

    await app.router.startup()
    _orig = {
        "activate": lic_cp.HttpControlPlaneClient.activate,
        "fetch_entitlement": lic_cp.HttpControlPlaneClient.fetch_entitlement,
        "create_initial_checkout": lic_cp.HttpControlPlaneClient.create_initial_checkout,
    }
    try:
        # 1) FRESH production install: a provisional local identity may exist, but it is NOT activated.
        async with SessionLocal() as db:
            prov_iid, _ = await svc.get_installation(db)
            assert await svc.is_activated(db) is False
            # refresh must NOT hit the CP with the provisional id (that caused the 404).
            r = await svc.refresh(db, force=True)
            assert r["ok"] is False and "not activated" in r["error"]

        # Stub the central client's activate to return CP-authoritative ids + a real entitlement.
        calls = {"activate": 0}
        auth_data = _make_activation_data("cp-inst-1", "cp-co-1", "cp-lic-1")

        async def fake_activate(self, db, *, company_name=None, requested_seats=None):
            calls["activate"] += 1
            calls["company_name"] = company_name
            calls["requested_seats"] = requested_seats
            return auth_data

        lic_cp.HttpControlPlaneClient.activate = fake_activate  # type: ignore

        # seed the company name entered during bootstrap
        async with SessionLocal() as db:
            db.add(AppConfig(key="company_profile", value={"name": "Acme Roofing"}))
            await db.commit()

        client = lic_cp.get_client()

        # 2) Owner completes setup -> first-run activation.
        async with SessionLocal() as db:
            iid, cid = await _ensure_installation_identity(db, client)
        assert (iid, cid) == ("cp-inst-1", "cp-co-1")
        assert calls == {"activate": 1, "company_name": "Acme Roofing", "requested_seats": 5}

        # 3) Authoritative ids REPLACE the provisional local ids + activated marker set.
        async with SessionLocal() as db:
            row = (await db.execute(select(AppConfig).where(AppConfig.key == "installation"))).scalar_one()
            assert row.value["installation_id"] == "cp-inst-1" != prov_iid
            assert row.value["company_id"] == "cp-co-1"
            assert row.value["license_id"] == "cp-lic-1"
            assert row.value["activated"] is True
            assert await svc.is_activated(db) is True

        # 4) Returned license/entitlement state is cached + verifiable.
        async with SessionLocal() as db:
            lc = (await db.execute(select(LicenseCache))).scalar_one()
            assert lc.installation_id == "cp-inst-1" and lc.license_id == "cp-lic-1"
            assert lc.entitlement_jws == auth_data["entitlement_jws"]
            assert lc.subscription_state == "ACTIVE" and lc.seats_licensed == 5
            eff = await svc.get_effective(db)
            assert eff.effective_state == "ACTIVE"

        # 5) Retry does NOT duplicate activation (reuses the server-authoritative identity).
        async with SessionLocal() as db:
            iid2, cid2 = await _ensure_installation_identity(db, client)
        assert (iid2, cid2) == ("cp-inst-1", "cp-co-1")
        assert calls["activate"] == 1

        # 6) Entitlement refresh SUCCEEDS after activation and signs with the SERVER-issued id.
        async def fake_fetch(self, db, *, installation_id, company_id):
            assert installation_id == "cp-inst-1"  # server-issued id used for the signed request
            return _make_activation_data(installation_id, company_id, "cp-lic-1")["entitlement_jws"]

        lic_cp.HttpControlPlaneClient.fetch_entitlement = fake_fetch  # type: ignore
        async with SessionLocal() as db:
            res = await svc.refresh(db, force=True)
            assert res["ok"] is True and res["state"] == "ACTIVE"

        # 7) Initial Stripe checkout reaches the provider using the server-issued installation id.
        seen = {}

        async def fake_checkout(self, db, *, company_id, installation_id=None, seats=None):
            seen.update(company_id=company_id, installation_id=installation_id, seats=seats)
            return {"checkout_url": "https://checkout.stripe.com/c/pay/cs_test_1",
                    "company_id": company_id, "seats": seats, "monthly_price_usd": 245}

        lic_cp.HttpControlPlaneClient.create_initial_checkout = fake_checkout  # type: ignore
        async with SessionLocal() as db:
            iid3, cid3 = await _ensure_installation_identity(db, client)
            data = await client.create_initial_checkout(db, company_id=cid3, installation_id=iid3, seats=5)
        assert seen["installation_id"] == "cp-inst-1" and seen["seats"] == 5
        assert data["checkout_url"].startswith("https://checkout.stripe.com/")
    finally:
        for name, fn in _orig.items():
            setattr(lic_cp.HttpControlPlaneClient, name, fn)  # restore (avoid cross-test leakage)
        await app.router.shutdown()


def test_production_activation_flow():
    if _run_isolated("tests/test_setup_activation.py::test_production_activation_flow"):
        return
    _create_db(_FRESH)
    _create_db(f"{_FRESH}_cp")
    try:
        asyncio.run(_flow())
    finally:
        _drop_db(_FRESH)
        _drop_db(f"{_FRESH}_cp")


def test_activation_sends_public_key_only_never_private(tmp_path, monkeypatch):
    """The activation payload carries ONLY the installation PUBLIC key; the private key never leaves
    the machine (defense verified by capturing the exact outbound request)."""
    import httpx
    import licensing.control_plane as lic_cp
    from licensing import identity

    # Self-contained identity dir + CP URL so this test is independent of run order / other tests.
    monkeypatch.setenv("INSTALLATION_KEYS_DIR", str(tmp_path))
    monkeypatch.setattr(lic_cp.config, "CONTROL_PLANE_URL", "https://cp.roofspan.io/api/control-plane")
    captured = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"installation_id": "i", "company_id": "c", "license_id": "l",
                    "entitlement_jws": None, "signing_public_keys": {}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, **k):
            captured["url"] = url
            captured["json"] = json
            return _Resp()

    orig = httpx.AsyncClient
    httpx.AsyncClient = _Client  # type: ignore
    try:
        priv, pub = identity.get_or_create_identity()
        client = lic_cp.HttpControlPlaneClient()
        asyncio.run(client.activate(None, company_name="X", requested_seats=5))
    finally:
        httpx.AsyncClient = orig  # type: ignore

    payload = captured["json"]
    assert payload["installation_public_key"] == pub
    assert "PUBLIC KEY" in pub
    assert payload["requested_seats"] == 5
    blob = "\n".join(str(v) for v in payload.values())
    assert "PRIVATE KEY" not in blob                      # private key material never transmitted
    assert "installation_private_key" not in payload and "private_key" not in payload
