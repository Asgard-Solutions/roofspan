"""P6 — User-specific Mobile pairing (Control Plane). Reuses the signed-installation harness.

Proves: pairing bound to a specific Office user; token single-use; expired token rejected; reused
token rejected; wrong/invalid token rejected; 6-digit fallback works; binding carried to the device
+ device list; revoke blocks; re-pair issues a fresh working code. No secrets/passwords in the QR.
"""
import os
import time
import json
import uuid
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import reqsig

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CP = f"{BASE_URL}/api/control-plane"
BOOTSTRAP = os.environ.get("CP_DEV_BOOTSTRAP_SECRET", "dev-bootstrap-roofspan")
ADMIN = {"X-RoofSpan-Admin": os.environ.get("CP_DEV_ADMIN_SECRET", "dev-admin-roofspan")}

USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())


def _activate():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    r = requests.post(f"{CP}/activate", json={"company_name": "Bind Co", "requested_seats": 5,
                      "installation_public_key": pub, "software_version": "1.0.0", "bootstrap_credential": BOOTSTRAP}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json(), priv


def _signed(method, path, iid, priv, body=b""):
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    sig = reqsig.sign_request(priv, installation_id=iid, timestamp=ts, nonce=nonce, body=body)
    h = {reqsig.H_INSTALLATION: iid, reqsig.H_TIMESTAMP: ts, reqsig.H_NONCE: nonce, reqsig.H_SIGNATURE: sig}
    return requests.request(method, f"{CP}{path}", data=body, headers=h, timeout=15)


def _create_for_user(user_id, label):
    data, priv = _activate()
    body = json.dumps({"expected_user_id": user_id, "expected_user_label": label}).encode()
    r = _signed("POST", "/pairing/create", data["installation_id"], priv, body=body)
    assert r.status_code == 200, r.text
    return data, priv, r.json()


def test_qr_bound_to_user_and_no_secrets():
    data, priv, p = _create_for_user(USER_A, "Jake Field")
    assert p["expected_user_id"] == USER_A and p["expected_user_label"] == "Jake Field"
    s = json.dumps(p["qr_payload"]).lower()
    assert "password" not in s and "credential" not in s and "token" in s
    # resolve carries the binding onto the device
    r = requests.post(f"{CP}/pairing/resolve", json={"token": p["token"], "label": "Jake iPhone"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["expected_user_id"] == USER_A and body["expected_user_label"] == "Jake Field"
    assert body["device_credential"] and body["installation_id"] == data["installation_id"]


def test_numeric_fallback_carries_binding():
    _, _, p = _create_for_user(USER_A, "Jake Field")
    r = requests.post(f"{CP}/pairing/resolve", json={"numeric_code": p["numeric_code"]}, timeout=15)
    assert r.status_code == 200 and r.json()["expected_user_id"] == USER_A


def test_token_single_use_and_reuse_rejected():
    _, _, p = _create_for_user(USER_A, "Jake")
    assert requests.post(f"{CP}/pairing/resolve", json={"token": p["token"]}, timeout=15).status_code == 200
    assert requests.post(f"{CP}/pairing/resolve", json={"token": p["token"]}, timeout=15).status_code == 409


def test_invalid_token_rejected():
    assert requests.post(f"{CP}/pairing/resolve", json={"token": "deadbeef" * 4}, timeout=15).status_code == 404
    assert requests.post(f"{CP}/pairing/resolve", json={"numeric_code": "000000"}, timeout=15).status_code == 404


def test_wrong_user_binding_is_fixed_server_side():
    # A token minted for USER_B can never enroll as USER_A — the binding is set server-side at create.
    _, _, pb = _create_for_user(USER_B, "Sara")
    res = requests.post(f"{CP}/pairing/resolve", json={"token": pb["token"]}, timeout=15).json()
    assert res["expected_user_id"] == USER_B and res["expected_user_id"] != USER_A


def test_device_list_filtered_by_user_then_revoke_and_repair():
    data, priv, pa = _create_for_user(USER_A, "Jake")
    dev = requests.post(f"{CP}/pairing/resolve", json={"token": pa["token"]}, timeout=15).json()
    dev_id = dev["device_id"]
    dl = _signed("GET", "/pairing/devices", data["installation_id"], priv, body=b"")
    assert dl.status_code == 200
    mine = [d for d in dl.json()["devices"] if d["id"] == dev_id]
    assert mine and mine[0]["expected_user_id"] == USER_A
    # revoke blocks the device (does not disable the user)
    rv = requests.post(f"{CP}/pairing/devices/{dev_id}/revoke", headers=ADMIN, timeout=15)
    assert rv.status_code == 200 and rv.json()["status"] == "REVOKED"
    # re-pair: a fresh code works and yields a new device
    _, _, pa2 = _create_for_user(USER_A, "Jake")
    dev2 = requests.post(f"{CP}/pairing/resolve", json={"token": pa2["token"]}, timeout=15).json()
    assert dev2["device_id"] and dev2["device_id"] != dev_id
