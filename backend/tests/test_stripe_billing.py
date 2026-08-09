"""Production Stripe Billing lifecycle tests (Control Plane, authoritative engine).

Uses the claimable Stripe TEST sandbox (keys in backend/.env). Creates a real test-mode subscription
(seat quantity = licensed seats, $49/seat/mo) and drives the RoofSpan lifecycle through
signature-verified Stripe webhooks: activation binding, seat increase (immediate proration), seat
decrease (scheduled at renewal via Subscription Schedule), cancel-at-period-end + reversal, 7-day
payment-failure GRACE, recovery, idempotency, out-of-order, and signature rejection.
"""
import os
import json
import time
import uuid
import hmac
import hashlib

import pytest
import requests
import stripe
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import reqsig
from licensing import entitlement as ent

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CP = f"{BASE_URL}/api/control-plane"
BOOTSTRAP = os.environ.get("CP_DEV_BOOTSTRAP_SECRET", "dev-bootstrap-roofspan")
ADMIN = {"X-RoofSpan-Admin": os.environ.get("CP_DEV_ADMIN_SECRET", "dev-admin-roofspan")}
WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]
LOOKUP = os.environ.get("STRIPE_SEAT_LOOKUP_KEY", "roofspan_seat_monthly")

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]


def _activate(seats=5):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    r = requests.post(f"{CP}/activate", json={
        "company_name": "Stripe Co", "requested_seats": seats, "installation_public_key": pub,
        "software_version": "1.0.0", "bootstrap_credential": BOOTSTRAP}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json(), priv


def _entitlement(data, priv):
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    sig = reqsig.sign_request(priv, installation_id=data["installation_id"], timestamp=ts, nonce=nonce, body=b"")
    h = {reqsig.H_INSTALLATION: data["installation_id"], reqsig.H_TIMESTAMP: ts,
         reqsig.H_NONCE: nonce, reqsig.H_SIGNATURE: sig}
    r = requests.post(f"{CP}/entitlement/refresh", data=b"", headers=h, timeout=20)
    assert r.status_code == 200, r.text
    return ent.verify_entitlement(
        r.json()["entitlement_jws"],
        {k: serialization.load_pem_public_key(v.encode()) for k, v in r.json()["signing_public_keys"].items()})


def _sign(body: bytes) -> str:
    t = int(time.time())
    signed = f"{t}.{body.decode()}".encode()
    v1 = hmac.new(WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


def _send_event(event: dict, sign=True):
    body = json.dumps(event).encode()
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["Stripe-Signature"] = _sign(body)
    else:
        headers["Stripe-Signature"] = "t=1,v1=deadbeef"
    return requests.post(f"{CP}/billing/stripe/webhook", data=body, headers=headers, timeout=20)


def _evt(etype, obj, created=None, eid=None):
    return {"id": eid or f"evt_{uuid.uuid4().hex}", "type": etype,
            "created": created or int(time.time()), "data": {"object": obj}}


@pytest.fixture
def ctx():
    """Provision a company + a REAL test-mode Stripe subscription (qty 5) and bind it via a
    signature-verified checkout.session.completed webhook."""
    data, priv = _activate(seats=5)
    company_id = data["company_id"]
    price_id = stripe.Price.list(lookup_keys=[LOOKUP], active=True, limit=1).data[0].id
    cust = stripe.Customer.create(metadata={"company_id": company_id}, description="RoofSpan test co")
    pm = stripe.PaymentMethod.attach("pm_card_visa", customer=cust.id)
    stripe.Customer.modify(cust.id, invoice_settings={"default_payment_method": pm.id})
    sub = stripe.Subscription.create(
        customer=cust.id, items=[{"price": price_id, "quantity": 5}],
        metadata={"company_id": company_id}, default_payment_method=pm.id)
    assert sub.status in ("active", "trialing"), sub.status
    # Bind via checkout.session.completed (authoritative seats fetched from Stripe by the CP).
    r = _send_event(_evt("checkout.session.completed",
                    {"client_reference_id": company_id, "subscription": sub.id, "customer": cust.id}))
    assert r.status_code == 200 and r.json()["status"] == "processed", r.text
    yield {"company_id": company_id, "data": data, "priv": priv, "sub_id": sub.id,
           "customer_id": cust.id, "price_id": price_id}
    try:
        stripe.Subscription.cancel(sub.id)
    except Exception:
        pass


def test_activation_binding_active_5_seats(ctx):
    e = _entitlement(ctx["data"], ctx["priv"])
    assert e.subscription_state == "ACTIVE"
    assert e.seats_licensed == 5


def test_seat_increase_is_immediate(ctx):
    r = requests.put(f"{CP}/billing/stripe/seats", params={"company_id": ctx["company_id"], "seats": 8},
                     headers=ADMIN, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["effect"] == "immediate" and r.json()["seats"] == 8
    # Stripe subscription quantity updated
    sub = stripe.Subscription.retrieve(ctx["sub_id"])
    assert sub["items"]["data"][0]["quantity"] == 8
    assert _entitlement(ctx["data"], ctx["priv"]).seats_licensed == 8


def test_seat_decrease_is_scheduled(ctx):
    # bump up first (immediate), then reduce (scheduled)
    requests.put(f"{CP}/billing/stripe/seats", params={"company_id": ctx["company_id"], "seats": 10},
                 headers=ADMIN, timeout=30)
    r = requests.put(f"{CP}/billing/stripe/seats", params={"company_id": ctx["company_id"], "seats": 6},
                     headers=ADMIN, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["effect"] == "scheduled"
    e = _entitlement(ctx["data"], ctx["priv"])
    assert e.seats_licensed == 10           # unchanged through current period
    assert e.scheduled_seats == 6           # scheduled reduction surfaced
    assert e.scheduled_seats_at is not None
    # a Stripe Subscription Schedule now governs the subscription
    sub = stripe.Subscription.retrieve(ctx["sub_id"])
    assert sub.get("schedule") is not None


def test_cancel_at_period_end_and_reactivate(ctx):
    r = requests.post(f"{CP}/billing/stripe/cancel", params={"company_id": ctx["company_id"], "cancel": True},
                      headers=ADMIN, timeout=30)
    assert r.status_code == 200 and r.json()["cancel_at_period_end"] is True, r.text
    e = _entitlement(ctx["data"], ctx["priv"])
    assert e.cancel_at_period_end is True and e.subscription_state == "ACTIVE"
    # reverse
    r2 = requests.post(f"{CP}/billing/stripe/cancel", params={"company_id": ctx["company_id"], "cancel": False},
                       headers=ADMIN, timeout=30)
    assert r2.status_code == 200 and r2.json()["cancel_at_period_end"] is False
    assert _entitlement(ctx["data"], ctx["priv"]).cancel_at_period_end is False


def test_payment_failure_grace_then_recovery(ctx):
    # invoice.payment_failed -> GRACE with grace_started_at
    r = _send_event(_evt("invoice.payment_failed",
                    {"subscription": ctx["sub_id"], "customer": ctx["customer_id"]}, created=int(time.time())))
    assert r.status_code == 200 and r.json()["state"] == "GRACE", r.text
    e = _entitlement(ctx["data"], ctx["priv"])
    assert e.subscription_state == "GRACE" and e.grace_started_at is not None
    # invoice.paid -> ACTIVE, grace cleared
    r2 = _send_event(_evt("invoice.paid",
                     {"subscription": ctx["sub_id"], "customer": ctx["customer_id"],
                      "period_end": int(time.time()) + 30 * 86400}, created=int(time.time()) + 1))
    assert r2.status_code == 200 and r2.json()["state"] == "ACTIVE", r2.text
    assert _entitlement(ctx["data"], ctx["priv"]).subscription_state == "ACTIVE"


def test_grace_expiry_to_suspended_via_sweep(ctx):
    _send_event(_evt("invoice.payment_failed", {"subscription": ctx["sub_id"], "customer": ctx["customer_id"]}))
    assert _entitlement(ctx["data"], ctx["priv"]).subscription_state == "GRACE"
    import psycopg
    from datetime import datetime, timezone, timedelta
    cn = psycopg.connect(host="127.0.0.1", port=5432, user="roofspan", password="roofspan_local_pwd",
                         dbname="roofspan_control_plane")
    cn.execute("UPDATE subscriptions SET grace_started_at=%s WHERE company_id=%s",
               (datetime.now(timezone.utc) - timedelta(days=8), ctx["company_id"]))
    cn.commit()
    cn.close()
    assert requests.post(f"{CP}/billing/sweep", headers=ADMIN, timeout=20).status_code == 200
    assert _entitlement(ctx["data"], ctx["priv"]).subscription_state == "SUSPENDED"
    # recover for cleanliness
    _send_event(_evt("invoice.paid", {"subscription": ctx["sub_id"], "customer": ctx["customer_id"]},
                created=int(time.time()) + 100))


def test_webhook_signature_required():
    r = _send_event(_evt("invoice.paid", {"subscription": "sub_x", "customer": "cus_x"}), sign=False)
    assert r.status_code == 401


def test_webhook_idempotent_duplicate(ctx):
    eid = f"evt_{uuid.uuid4().hex}"
    ev = _evt("customer.subscription.updated",
              {"id": ctx["sub_id"], "customer": ctx["customer_id"], "status": "active",
               "cancel_at_period_end": False, "current_period_end": int(time.time()) + 30 * 86400,
               "metadata": {"company_id": ctx["company_id"]},
               "items": {"data": [{"quantity": 8}]}}, eid=eid)
    r1 = _send_event(ev)
    r2 = _send_event(ev)
    assert r1.json()["status"] == "processed"
    assert r2.json()["status"] == "duplicate"


def test_webhook_out_of_order_ignored(ctx):
    base = int(time.time()) + 500
    period = base + 30 * 86400
    newer = _evt("customer.subscription.updated",
                 {"id": ctx["sub_id"], "customer": ctx["customer_id"], "status": "active",
                  "cancel_at_period_end": False, "current_period_end": period,
                  "metadata": {"company_id": ctx["company_id"]}, "items": {"data": [{"quantity": 8}]}},
                 created=base)
    assert _send_event(newer).json()["status"] == "processed"
    older = _evt("customer.subscription.updated",
                 {"id": ctx["sub_id"], "customer": ctx["customer_id"], "status": "past_due",
                  "cancel_at_period_end": False, "current_period_end": period,
                  "metadata": {"company_id": ctx["company_id"]}, "items": {"data": [{"quantity": 8}]}},
                 created=base - 100)
    assert _send_event(older).json()["status"] == "ignored"


def test_stripe_reconcile(ctx):
    r = requests.post(f"{CP}/billing/stripe/reconcile", params={"company_id": ctx["company_id"]},
                      headers=ADMIN, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["state"] in ("ACTIVE", "GRACE")


def test_seat_bounds_enforced(ctx):
    # request above max -> clamped to 50 on the immediate increase path
    r = requests.put(f"{CP}/billing/stripe/seats", params={"company_id": ctx["company_id"], "seats": 999},
                     headers=ADMIN, timeout=30)
    assert r.status_code == 200 and r.json()["seats"] == 50
