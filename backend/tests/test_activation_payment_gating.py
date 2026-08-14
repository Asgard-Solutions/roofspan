"""Activation must NOT grant paid access before Stripe payment succeeds.

Reproduces the bug (activation issued an ACTIVE 5-seat entitlement immediately) and proves the fixed
lifecycle end-to-end against the in-process Control Plane, WITHOUT network or Stripe keys (the Stripe
provider is faked). Stripe stays authoritative: only a verified webhook flips the subscription to
ACTIVE with the purchased seats.

Run: cd /app/backend && PYTHONPATH=/app/backend python -m pytest tests/test_activation_payment_gating.py -o addopts='' -q
"""
import os
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import psycopg

_base = "postgresql+asyncpg://roofspan:roofspan_local_pwd@127.0.0.1:5432"
_NAME = f"cpgate_{uuid.uuid4().hex[:8]}"
os.environ["CONTROL_PLANE_DATABASE_URL"] = f"{_base}/{_NAME}"
os.environ.setdefault("DATABASE_URL", f"{_base}/{_NAME}_app")

_admin_dsn = "postgresql://roofspan:roofspan_local_pwd@127.0.0.1:5432/postgres"


def _mk(n):
    with psycopg.connect(_admin_dsn, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{n}"')


def _rm(n):
    with psycopg.connect(_admin_dsn, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)')


def _new_identity():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pub


def _decode(entitlement_jws, signing_public_keys):
    from cryptography.hazmat.primitives import serialization
    from licensing import entitlement as ent
    keys = {k: serialization.load_pem_public_key(v.encode()) for k, v in signing_public_keys.items()}
    return ent.verify_entitlement(entitlement_jws, keys)


class _FakeStripeProvider:
    """Network-free stand-in: create_checkout_session (initial checkout) + subscription normalization
    used by checkout.session.completed handling."""
    name = "stripe"

    def _clamp(self, seats):
        return max(5, min(50, int(seats)))

    def create_checkout_session(self, company_id, seats, origin_url=None):
        _FakeStripeProvider.last_checkout = {"company_id": company_id, "seats": seats}
        return f"https://checkout.stripe.com/c/pay/cs_{company_id[:6]}"

    def retrieve_subscription(self, sid):
        return {"id": sid}

    def normalize_subscription(self, sub):
        return {"seats": 5, "current_period_end": datetime.now(timezone.utc) + timedelta(days=30),
                "cancel_at_period_end": False, "state": "ACTIVE"}


async def _flow():
    from control_plane import service, config
    from control_plane import billing as cp_billing
    from control_plane.db import SessionLocal
    from control_plane.models import Company, Installation, License, Subscription
    from licensing import reqsig
    from sqlalchemy import select, func

    await service.init_control_plane()
    priv, pub = _new_identity()

    # 1) ACTIVATION does NOT grant paid access.
    async with SessionLocal() as db:
        data = await service.activate(db, company_name="Gate Co", requested_seats=5, public_key_pem=pub,
                                      software_version="1.0.0", bootstrap_credential=config.DEV_BOOTSTRAP_SECRET)
    ent0 = _decode(data["entitlement_jws"], data["signing_public_keys"])
    assert ent0.subscription_state == "SUSPENDED", ent0.subscription_state   # NOT ACTIVE
    assert ent0.seats_licensed == 0                                          # NO usable seats pre-payment

    # identity registered (company/installation/license/subscription all exist).
    async with SessionLocal() as db:
        assert (await db.execute(select(func.count(Company.id)))).scalar_one() == 1
        assert (await db.execute(select(func.count(Installation.id)))).scalar_one() == 1
        assert (await db.execute(select(func.count(License.id)))).scalar_one() == 1
        sub = (await db.execute(select(Subscription))).scalar_one()
        assert sub.state == "SUSPENDED" and sub.seats == 0 and sub.current_period_end is None

    iid, cid = data["installation_id"], data["company_id"]

    # 2) UNPAID install can still AUTHENTICATE + refresh (returns a SUSPENDED/0 entitlement, not ACTIVE).
    async with SessionLocal() as db:
        ts, nonce = str(int(datetime.now(timezone.utc).timestamp())), uuid.uuid4().hex
        sig = reqsig.sign_request(priv, installation_id=iid, timestamp=ts, nonce=nonce, body=b"")
        rr = await service.refresh_entitlement(db, installation_id=iid, timestamp=ts, nonce=nonce,
                                                body=b"", signature_b64=sig)
    ent_unpaid = _decode(rr["entitlement_jws"], rr["signing_public_keys"])
    assert ent_unpaid.subscription_state == "SUSPENDED" and ent_unpaid.seats_licensed == 0

    # 3) UNPAID install can request the INITIAL Stripe Checkout (defaults to the 5-seat minimum).
    fake = _FakeStripeProvider()
    _orig_get = cp_billing.get_stripe_provider
    cp_billing.get_stripe_provider = lambda: fake
    try:
        async with SessionLocal() as db:
            co = await service.stripe_create_checkout(db, company_id=cid, seats=None, origin_url=None)
        assert co["url"].startswith("https://checkout.stripe.com/")
        assert co["seats"] == 5                        # 5-seat minimum even though sub.seats is 0

        # 4) A verified Stripe webhook (checkout.session.completed) transitions the subscription to ACTIVE.
        parsed = SimpleNamespace(event_type="checkout.session.completed", provider_customer_id="cus_x",
                                 provider_subscription_id="sub_x", normalized_state=None,
                                 seats=None, current_period_end=None, cancel_at_period_end=None,
                                 company_reference=cid)
        async with SessionLocal() as db:
            state = await service._apply_stripe_event(db, parsed=parsed, provider=fake)
        assert state == "ACTIVE"
        async with SessionLocal() as db:
            sub = (await db.execute(select(Subscription))).scalar_one()
            assert sub.state == "ACTIVE" and sub.seats == 5   # purchased seats from Stripe
    finally:
        cp_billing.get_stripe_provider = _orig_get

    # 5) After the webhook, entitlement refresh returns ACTIVE with the purchased seat quantity.
    async with SessionLocal() as db:
        ts, nonce = str(int(datetime.now(timezone.utc).timestamp())), uuid.uuid4().hex
        sig = reqsig.sign_request(priv, installation_id=iid, timestamp=ts, nonce=nonce, body=b"")
        rr2 = await service.refresh_entitlement(db, installation_id=iid, timestamp=ts, nonce=nonce,
                                                 body=b"", signature_b64=sig)
    ent_paid = _decode(rr2["entitlement_jws"], rr2["signing_public_keys"])
    assert ent_paid.subscription_state == "ACTIVE" and ent_paid.seats_licensed == 5

    # 6) Activation retry (same public key) is IDEMPOTENT: no duplicate company/installation/subscription,
    #    and an EXISTING PAID customer stays ACTIVE (activation never resets a paid sub to SUSPENDED).
    async with SessionLocal() as db:
        data2 = await service.activate(db, company_name="Gate Co", requested_seats=5, public_key_pem=pub,
                                       software_version="1.0.0", bootstrap_credential=config.DEV_BOOTSTRAP_SECRET)
    assert data2["installation_id"] == iid and data2["company_id"] == cid
    ent_retry = _decode(data2["entitlement_jws"], data2["signing_public_keys"])
    assert ent_retry.subscription_state == "ACTIVE" and ent_retry.seats_licensed == 5   # paid customer unaffected
    async with SessionLocal() as db:
        assert (await db.execute(select(func.count(Company.id)))).scalar_one() == 1
        assert (await db.execute(select(func.count(Installation.id)))).scalar_one() == 1
        assert (await db.execute(select(func.count(Subscription.id)))).scalar_one() == 1


def test_activation_payment_gating_lifecycle():
    _mk(_NAME)
    try:
        asyncio.run(_flow())
    finally:
        _rm(_NAME)


def test_activation_creates_suspended_not_active_in_source():
    # The exact non-active state used before payment is SUSPENDED with 0 seats (no new state invented).
    src = open(os.path.join(os.path.dirname(__file__), "..", "control_plane", "service.py")).read()
    assert 'state="SUSPENDED", seats=0' in src
    assert 'state="ACTIVE", seats=seats' not in src  # the pre-payment ACTIVE grant is gone


def test_stripe_promo_support_remains_enabled():
    src = open(os.path.join(os.path.dirname(__file__), "..", "control_plane", "billing.py")).read()
    assert "allow_promotion_codes=True" in src
    assert "OWNERTEST" not in src
