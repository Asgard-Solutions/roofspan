"""Phase C2 integration tests: Control Plane billing webhook ingestion (validation, idempotency,
out-of-order handling), normalized state transitions, reconciliation, and hosted URL generation.

Uses BILLING_MODE=mock (default) so no external RevenueCat/Stripe account is required.
"""
import os
import time
import uuid

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import reqsig
from licensing import entitlement as ent

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CP = f"{BASE_URL}/api/control-plane"
BOOTSTRAP = os.environ.get("CP_DEV_BOOTSTRAP_SECRET", "dev-bootstrap-roofspan")
ADMIN = {"X-RoofSpan-Admin": os.environ.get("CP_DEV_ADMIN_SECRET", "dev-admin-roofspan")}
WEBHOOK_AUTH = os.environ.get("REVENUECAT_WEBHOOK_AUTH", "dev-webhook-secret")


def _new_keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pub


def _activate(seats=10):
    priv, pub = _new_keypair()
    r = requests.post(f"{CP}/activate", json={
        "company_name": "Billing Co", "requested_seats": seats, "installation_public_key": pub,
        "software_version": "1.0.0", "bootstrap_credential": BOOTSTRAP}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json(), priv


def _current_state(data, priv):
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    sig = reqsig.sign_request(priv, installation_id=data["installation_id"], timestamp=ts, nonce=nonce, body=b"")
    h = {reqsig.H_INSTALLATION: data["installation_id"], reqsig.H_TIMESTAMP: ts,
         reqsig.H_NONCE: nonce, reqsig.H_SIGNATURE: sig}
    r = requests.post(f"{CP}/entitlement/refresh", data=b"", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    e = ent.verify_entitlement(r.json()["entitlement_jws"],
                               {k: serialization.load_pem_public_key(v.encode()) for k, v in r.json()["signing_public_keys"].items()})
    return e.subscription_state


def _webhook(company_id, etype, ts_ms=None, event_id=None, auth=WEBHOOK_AUTH):
    payload = {"api_version": "1.0", "event": {
        "id": event_id or uuid.uuid4().hex, "type": etype, "app_user_id": company_id,
        "event_timestamp_ms": ts_ms or int(time.time() * 1000)}}
    headers = {"Authorization": auth, "Content-Type": "application/json"}
    return requests.post(f"{CP}/billing/webhook", json=payload, headers=headers, timeout=15)


def test_webhook_requires_auth():
    data, _ = _activate()
    r = _webhook(data["company_id"], "RENEWAL", auth="wrong")
    assert r.status_code == 401


def test_webhook_billing_issue_sets_grace():
    data, priv = _activate()
    assert _webhook(data["company_id"], "BILLING_ISSUE").status_code == 200
    assert _current_state(data, priv) == "GRACE"


def test_webhook_expiration_then_renewal_recovers():
    data, priv = _activate()
    assert _webhook(data["company_id"], "EXPIRATION", ts_ms=1000).status_code == 200
    assert _current_state(data, priv) == "SUSPENDED"
    # recovery — no reinstall/activation
    assert _webhook(data["company_id"], "RENEWAL", ts_ms=2000).status_code == 200
    assert _current_state(data, priv) == "ACTIVE"


def test_webhook_idempotent_duplicate():
    data, priv = _activate()
    eid = uuid.uuid4().hex
    r1 = _webhook(data["company_id"], "BILLING_ISSUE", event_id=eid)
    r2 = _webhook(data["company_id"], "BILLING_ISSUE", event_id=eid)
    assert r1.json()["status"] == "processed"
    assert r2.json()["status"] == "duplicate"


def test_webhook_out_of_order_ignored():
    data, priv = _activate()
    assert _webhook(data["company_id"], "RENEWAL", ts_ms=5000).status_code == 200
    r = _webhook(data["company_id"], "EXPIRATION", ts_ms=1000)  # older than the processed RENEWAL
    assert r.json()["status"] == "ignored"
    assert _current_state(data, priv) == "ACTIVE"


def _entitlement_for(data, priv):
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    sig = reqsig.sign_request(priv, installation_id=data["installation_id"], timestamp=ts, nonce=nonce, body=b"")
    h = {reqsig.H_INSTALLATION: data["installation_id"], reqsig.H_TIMESTAMP: ts,
         reqsig.H_NONCE: nonce, reqsig.H_SIGNATURE: sig}
    r = requests.post(f"{CP}/entitlement/refresh", data=b"", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    return ent.verify_entitlement(r.json()["entitlement_jws"],
                                  {k: serialization.load_pem_public_key(v.encode()) for k, v in r.json()["signing_public_keys"].items()})


def test_webhook_cancellation_stays_active_until_period_end():
    data, priv = _activate()
    r = _webhook(data["company_id"], "CANCELLATION")
    assert r.status_code == 200 and r.json()["state"] == "ACTIVE"  # remains usable through paid period
    e = _entitlement_for(data, priv)
    assert e.subscription_state == "ACTIVE"
    assert e.cancel_at_period_end is True
    assert e.current_period_end is not None


def test_seat_increase_is_immediate():
    data, priv = _activate(seats=10)
    r = requests.put(f"{CP}/subscriptions/{data['company_id']}/seats", params={"seats": 15}, headers=ADMIN, timeout=15)
    assert r.status_code == 200 and r.json()["effect"] == "immediate"
    assert _entitlement_for(data, priv).seats_licensed == 15


def test_seat_decrease_is_scheduled():
    data, priv = _activate(seats=15)
    r = requests.put(f"{CP}/subscriptions/{data['company_id']}/seats", params={"seats": 10}, headers=ADMIN, timeout=15)
    assert r.status_code == 200 and r.json()["effect"] == "scheduled"
    e = _entitlement_for(data, priv)
    assert e.seats_licensed == 15               # still 15 through current period
    assert e.scheduled_seats == 10              # scheduled reduction surfaced
    assert e.scheduled_seats_at is not None


def test_grace_started_surfaced_on_billing_issue():
    data, priv = _activate()
    _webhook(data["company_id"], "BILLING_ISSUE")
    e = _entitlement_for(data, priv)
    assert e.subscription_state == "GRACE"
    assert e.grace_started_at is not None


def test_grace_expiry_transitions_to_suspended_via_sweep():
    data, priv = _activate()
    _webhook(data["company_id"], "BILLING_ISSUE")
    # backdate grace_started beyond the 7-day window, then sweep
    import psycopg
    from datetime import datetime, timezone, timedelta
    cn = psycopg.connect(host="127.0.0.1", port=5432, user="roofspan", password="roofspan_local_pwd", dbname="roofspan_control_plane")
    cn.execute("UPDATE subscriptions SET grace_started_at=%s WHERE company_id=%s",
               (datetime.now(timezone.utc) - timedelta(days=8), data["company_id"]))
    cn.commit()
    sw = requests.post(f"{CP}/billing/sweep", headers=ADMIN, timeout=15)
    assert sw.status_code == 200
    assert _entitlement_for(data, priv).subscription_state == "SUSPENDED"


def test_reconcile_mock():
    data, priv = _activate()
    _webhook(data["company_id"], "EXPIRATION", ts_ms=1000)
    assert _current_state(data, priv) == "SUSPENDED"
    r = requests.post(f"{CP}/billing/reconcile", params={"company_id": data["company_id"]}, headers=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ACTIVE"  # mock reconcile reports active
    assert _current_state(data, priv) == "ACTIVE"


def test_checkout_and_portal_urls():
    data, _ = _activate()
    c = requests.post(f"{CP}/billing/checkout", params={"company_id": data["company_id"]}, headers=ADMIN, timeout=15)
    assert c.status_code == 200 and c.json()["url"]
    p = requests.get(f"{CP}/billing/portal-url", params={"company_id": data["company_id"]}, headers=ADMIN, timeout=15)
    assert p.status_code == 200 and p.json()["url"]


def test_billing_admin_endpoints_require_admin():
    data, _ = _activate()
    assert requests.post(f"{CP}/billing/checkout", params={"company_id": data["company_id"]}, timeout=15).status_code == 401
    assert requests.post(f"{CP}/billing/reconcile", params={"company_id": data["company_id"]}, timeout=15).status_code == 401
