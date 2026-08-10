"""
Independent live-URL verification of the KMS signer refactor.
Uses REACT_APP_BACKEND_URL. Signer is expected to be 'local' in this env.
"""
import base64
import hashlib
import os
import secrets
import time
import uuid

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CP = f"{BASE_URL}/api/control-plane"
BOOTSTRAP = os.environ.get("CP_DEV_BOOTSTRAP_SECRET", "dev-bootstrap-roofspan")
ADMIN = os.environ.get("CP_DEV_ADMIN_SECRET", "dev-admin-roofspan")

H_INSTALLATION = "X-RoofSpan-Installation"
H_TIMESTAMP = "X-RoofSpan-Timestamp"
H_NONCE = "X-RoofSpan-Nonce"
H_SIGNATURE = "X-RoofSpan-Signature"


def _gen_ed25519():
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv, pub_pem


def _canonical(installation_id, ts, nonce, body):
    bh = hashlib.sha256(body or b"").hexdigest()
    return "\n".join([installation_id, str(ts), nonce, bh]).encode()


def _sign_headers(priv, installation_id, body):
    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    sig = base64.b64encode(priv.sign(_canonical(installation_id, ts, nonce, body))).decode()
    return {
        H_INSTALLATION: installation_id,
        H_TIMESTAMP: ts,
        H_NONCE: nonce,
        H_SIGNATURE: sig,
        "Content-Type": "application/json",
    }


def _get_public_keys():
    r = requests.get(f"{CP}/signing-keys/public", timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["keys"]  # {kid: pem}


def _verify_jws(jws: str, keys: dict):
    header = jwt.get_unverified_header(jws)
    kid = header["kid"]
    assert header["alg"] == "EdDSA", f"expected EdDSA, got {header['alg']}"
    pem = keys.get(kid)
    assert pem, f"kid {kid} not in published keys: {list(keys)}"
    payload = jwt.decode(jws, pem, algorithms=["EdDSA"], options={"verify_aud": False})
    return kid, payload


def _activate():
    priv, pub_pem = _gen_ed25519()
    body = {
        "company_id": f"TEST_co_{uuid.uuid4().hex[:8]}",
        "installation_public_key": pub_pem,
        "bootstrap_credential": BOOTSTRAP,
        "requested_seats": 3,
        "device_info": {"host": "pytest"},
    }
    r = requests.post(f"{CP}/activate", json=body, timeout=20)
    assert r.status_code == 200, r.text
    return priv, r.json()


def test_ready_reports_local_signer():
    r = requests.get(f"{CP}/ready", timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert j["ready"] is True and j["checks"]["db"] is True and j["checks"]["signing_key"] is True
    assert j["signer"] == "local"


def test_activation_issues_verifiable_entitlement():
    _priv, data = _activate()
    jws = data["entitlement_jws"]
    keys = _get_public_keys()
    kid, payload = _verify_jws(jws, keys)
    assert kid in keys
    assert payload.get("installation_id")


def test_refresh_issues_verifiable_entitlement():
    priv, data = _activate()
    installation_id = data["installation_id"]
    body = b"{}"
    headers = _sign_headers(priv, installation_id, body)
    r = requests.post(f"{CP}/entitlement/refresh", data=body, headers=headers, timeout=20)
    assert r.status_code == 200, r.text
    jws = r.json()["entitlement_jws"]
    _verify_jws(jws, _get_public_keys())


def test_rotation_old_and_new_kids_coexist_live():
    _priv, data = _activate()
    old_jws = data["entitlement_jws"]
    old_kid = jwt.get_unverified_header(old_jws)["kid"]

    r = requests.post(
        f"{CP}/signing-keys/rotate",
        headers={"X-RoofSpan-Admin": ADMIN, "Content-Type": "application/json"},
        json={},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    rot = r.json()
    new_kid = rot.get("kid") or rot.get("active_kid") or rot.get("new_kid")
    assert new_kid and new_kid != old_kid, f"rotation response: {rot}"

    keys = _get_public_keys()
    assert old_kid in keys, f"old kid {old_kid} missing after rotation: {list(keys)}"
    assert new_kid in keys, f"new kid {new_kid} missing after rotation: {list(keys)}"

    # Old JWS still verifies
    _verify_jws(old_jws, keys)

    # New activation must sign with the new active kid
    _priv2, data2 = _activate()
    fresh_kid, _ = _verify_jws(data2["entitlement_jws"], keys)
    assert fresh_kid == new_kid, f"expected active kid {new_kid}, got {fresh_kid}"
