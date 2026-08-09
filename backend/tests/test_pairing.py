"""Phase C3 integration tests: Mobile pairing (QR/numeric), device management, version negotiation,
and Mobile license-lock enforcement.
"""
import os
import time
import uuid

import requests
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import reqsig

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
CP = f"{BASE_URL}/api/control-plane"
BOOTSTRAP = os.environ.get("CP_DEV_BOOTSTRAP_SECRET", "dev-bootstrap-roofspan")
ADMIN = {"X-RoofSpan-Admin": os.environ.get("CP_DEV_ADMIN_SECRET", "dev-admin-roofspan")}
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}


def _login():
    r = requests.post(f"{API}/auth/login", json=OWNER, timeout=15)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _activate():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    r = requests.post(f"{CP}/activate", json={"company_name": "Pair Co", "requested_seats": 5,
                      "installation_public_key": pub, "software_version": "1.0.0", "bootstrap_credential": BOOTSTRAP}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json(), priv


def _signed_post(path, iid, priv, body=b""):
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    sig = reqsig.sign_request(priv, installation_id=iid, timestamp=ts, nonce=nonce, body=body)
    h = {reqsig.H_INSTALLATION: iid, reqsig.H_TIMESTAMP: ts, reqsig.H_NONCE: nonce, reqsig.H_SIGNATURE: sig}
    return requests.post(f"{CP}{path}", data=body, headers=h, timeout=15)


def _create_pairing():
    data, priv = _activate()
    r = _signed_post("/pairing/create", data["installation_id"], priv)
    assert r.status_code == 200, r.text
    return data, priv, r.json()


def test_pairing_create_requires_installation_auth():
    assert requests.post(f"{CP}/pairing/create", timeout=15).status_code == 401


def test_pairing_create_and_resolve_by_token():
    data, priv, p = _create_pairing()
    assert len(p["token"]) == 32 and len(p["numeric_code"]) == 6
    assert "token" in p["qr_payload"] and "password" not in str(p["qr_payload"]).lower()
    r = requests.post(f"{CP}/pairing/resolve", json={"token": p["token"], "label": "Field iPhone"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["installation_id"] == data["installation_id"]
    assert body["device_id"] and body["relay_endpoint"] and body["min_mobile_version"]


def test_pairing_resolve_by_numeric_code():
    data, priv, p = _create_pairing()
    r = requests.post(f"{CP}/pairing/resolve", json={"numeric_code": p["numeric_code"]}, timeout=15)
    assert r.status_code == 200 and r.json()["installation_id"] == data["installation_id"]


def test_pairing_token_single_use():
    data, priv, p = _create_pairing()
    assert requests.post(f"{CP}/pairing/resolve", json={"token": p["token"]}, timeout=15).status_code == 200
    assert requests.post(f"{CP}/pairing/resolve", json={"token": p["token"]}, timeout=15).status_code == 409


def test_pairing_resolve_invalid_code():
    assert requests.post(f"{CP}/pairing/resolve", json={"numeric_code": "000000"}, timeout=15).status_code == 404


def test_device_list_and_revoke():
    data, priv, p = _create_pairing()
    res = requests.post(f"{CP}/pairing/resolve", json={"token": p["token"]}, timeout=15).json()
    dev_id = res["device_id"]
    lst = _signed_post("/pairing/devices", data["installation_id"], priv)  # GET signed? use GET below
    # devices list is GET (signed) — build a signed GET
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    sig = reqsig.sign_request(priv, installation_id=data["installation_id"], timestamp=ts, nonce=nonce, body=b"")
    h = {reqsig.H_INSTALLATION: data["installation_id"], reqsig.H_TIMESTAMP: ts, reqsig.H_NONCE: nonce, reqsig.H_SIGNATURE: sig}
    dl = requests.get(f"{CP}/pairing/devices", headers=h, timeout=15)
    assert dl.status_code == 200 and any(d["id"] == dev_id for d in dl.json()["devices"])
    rv = requests.post(f"{CP}/pairing/devices/{dev_id}/revoke", headers=ADMIN, timeout=15)
    assert rv.status_code == 200 and rv.json()["status"] == "REVOKED"


def test_version_check_states():
    # set a policy window then check three versions
    requests.put(f"{CP}/version-policy", json={"mobile_min_supported": "1.2.0", "mobile_latest": "2.0.0"}, headers=ADMIN, timeout=15)
    assert requests.post(f"{CP}/mobile/version-check", json={"app_version": "1.0.0"}, timeout=15).json()["status"] == "must_update"
    assert requests.post(f"{CP}/mobile/version-check", json={"app_version": "1.5.0"}, timeout=15).json()["status"] == "update_available"
    assert requests.post(f"{CP}/mobile/version-check", json={"app_version": "2.0.0"}, timeout=15).json()["status"] == "ok"


def test_local_mobile_version_gate():
    owner = _login()
    # below the local minimum (1.0.0) -> 426 must_update
    r = requests.get(f"{API}/mobile/leads", headers={**owner, "X-RoofSpan-App-Version": "0.9.0"}, timeout=15)
    assert r.status_code == 426
    # current version passes the gate
    r2 = requests.get(f"{API}/mobile/leads", headers={**owner, "X-RoofSpan-App-Version": "1.0.0"}, timeout=15)
    assert r2.status_code == 200


def test_mobile_license_lock_when_suspended():
    owner = _login()
    def set_state(state, seats=1000):
        requests.post(f"{API}/dev/licensing/set-state", json={"state": state, "seats_licensed": seats}, headers=owner, timeout=15)
    try:
        set_state("SUSPENDED")
        r = requests.get(f"{API}/mobile/leads", headers={**owner, "X-RoofSpan-App-Version": "1.0.0"}, timeout=15)
        assert r.status_code == 403 and r.json().get("code") == "subscription_inactive"
        # licensing status remains readable so Mobile can show a license-lock screen
        assert requests.get(f"{API}/subscription", headers=owner, timeout=15).status_code == 200
    finally:
        set_state("ACTIVE")
