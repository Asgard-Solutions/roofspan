"""Phase C1 integration tests: Control Plane activation, installation-authenticated refresh,
replay protection, revocation, signing-key rotation, subscription updates, version policy, and
integration with the C0 verifier/state machine.
"""
import os
import time
import uuid

import requests
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import reqsig
from licensing import keys as lkeys
from licensing import entitlement as ent
from licensing import state as state_mod

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CP = f"{BASE_URL}/api/control-plane"
BOOTSTRAP = os.environ.get("CP_DEV_BOOTSTRAP_SECRET", "dev-bootstrap-roofspan")
ADMIN = {"X-RoofSpan-Admin": os.environ.get("CP_DEV_ADMIN_SECRET", "dev-admin-roofspan")}


def _new_keypair():
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")
    return priv, pub_pem


def _trusted(pem_map):
    return {kid: serialization.load_pem_public_key(pem.encode("utf-8")) for kid, pem in pem_map.items()}


def _activate(seats=10, company="Test Roofing"):
    priv, pub_pem = _new_keypair()
    r = requests.post(f"{CP}/activate", json={
        "company_name": company, "requested_seats": seats, "installation_public_key": pub_pem,
        "software_version": "1.0.0", "bootstrap_credential": BOOTSTRAP,
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json(), priv


def _signed_refresh(installation_id, priv, *, ts=None, nonce=None, body=b"", tamper=False):
    ts = ts or str(int(time.time()))
    nonce = nonce or uuid.uuid4().hex
    sig = reqsig.sign_request(priv, installation_id=installation_id, timestamp=ts, nonce=nonce, body=body)
    if tamper:
        sig = sig[:-4] + ("AAAA" if sig[-4:] != "AAAA" else "BBBB")
    headers = {
        reqsig.H_INSTALLATION: installation_id, reqsig.H_TIMESTAMP: ts,
        reqsig.H_NONCE: nonce, reqsig.H_SIGNATURE: sig,
    }
    return requests.post(f"{CP}/entitlement/refresh", data=body, headers=headers, timeout=15), nonce


# ---------------- activation + issuance + C0 verify ----------------

def test_activation_issues_verifiable_entitlement():
    data, priv = _activate(seats=12)
    assert data["installation_id"] and data["company_id"] and data["license_id"]
    e = ent.verify_entitlement(data["entitlement_jws"], _trusted(data["signing_public_keys"]))
    # Payment gating: a fresh activation issues a cryptographically-valid but SUSPENDED/0-seat
    # entitlement (no paid access before Stripe payment). Business access is denied.
    assert e.subscription_state == "SUSPENDED" and e.seats_licensed == 0
    assert e.installation_id == data["installation_id"]
    assert state_mod.evaluate(e).business_access is False
    # After payment (subscription flipped ACTIVE by the CP), a signed refresh reflects ACTIVE + seats.
    up = requests.put(f"{CP}/subscriptions/{data['company_id']}",
                      json={"state": "ACTIVE", "seats": 12}, headers=ADMIN, timeout=15)
    assert up.status_code == 200, up.text
    r, _ = _signed_refresh(data["installation_id"], priv)
    assert r.status_code == 200, r.text
    e2 = ent.verify_entitlement(r.json()["entitlement_jws"], _trusted(r.json()["signing_public_keys"]))
    assert e2.subscription_state == "ACTIVE" and e2.seats_licensed == 12
    assert state_mod.evaluate(e2).business_access is True


def test_activation_seat_bounds_clamped():
    # Seat counts are product-locked to [MIN=5, MAX=50]. Seats materialize in the entitlement once the
    # subscription is ACTIVE (post-payment); the CP clamps out-of-range values.
    lo, priv_lo = _activate(seats=1)
    assert requests.put(f"{CP}/subscriptions/{lo['company_id']}", json={"state": "ACTIVE", "seats": 1},
                        headers=ADMIN, timeout=15).status_code == 200
    r_lo, _ = _signed_refresh(lo["installation_id"], priv_lo)
    assert ent.verify_entitlement(r_lo.json()["entitlement_jws"], _trusted(r_lo.json()["signing_public_keys"])).seats_licensed == 5
    hi, priv_hi = _activate(seats=999)
    assert requests.put(f"{CP}/subscriptions/{hi['company_id']}", json={"state": "ACTIVE", "seats": 999},
                        headers=ADMIN, timeout=15).status_code == 200
    r_hi, _ = _signed_refresh(hi["installation_id"], priv_hi)
    assert ent.verify_entitlement(r_hi.json()["entitlement_jws"], _trusted(r_hi.json()["signing_public_keys"])).seats_licensed == 50


def test_activation_bad_credential_rejected():
    _priv, pub_pem = _new_keypair()
    r = requests.post(f"{CP}/activate", json={
        "company_name": "X", "requested_seats": 5, "installation_public_key": pub_pem,
        "software_version": "1.0.0", "bootstrap_credential": "wrong",
    }, timeout=15)
    assert r.status_code == 401


# ---------------- installation-authenticated refresh ----------------

def test_signed_refresh_succeeds():
    data, priv = _activate()
    r, _ = _signed_refresh(data["installation_id"], priv)
    assert r.status_code == 200, r.text
    e = ent.verify_entitlement(r.json()["entitlement_jws"], _trusted(r.json()["signing_public_keys"]))
    assert e.installation_id == data["installation_id"]


def test_replay_nonce_rejected():
    data, priv = _activate()
    r1, nonce = _signed_refresh(data["installation_id"], priv)
    assert r1.status_code == 200
    # reuse the exact same nonce + a fresh signature over the same nonce -> replay
    r2, _ = _signed_refresh(data["installation_id"], priv, nonce=nonce)
    assert r2.status_code == 409, r2.text


def test_stale_timestamp_rejected():
    data, priv = _activate()
    old_ts = str(int(time.time()) - 100000)
    r, _ = _signed_refresh(data["installation_id"], priv, ts=old_ts)
    assert r.status_code == 401


def test_bad_signature_rejected():
    data, priv = _activate()
    r, _ = _signed_refresh(data["installation_id"], priv, tamper=True)
    assert r.status_code == 401


def test_missing_headers_rejected():
    r = requests.post(f"{CP}/entitlement/refresh", data=b"", timeout=15)
    assert r.status_code == 401


# ---------------- revocation ----------------

def test_revoked_installation_cannot_refresh():
    data, priv = _activate()
    rr = requests.post(f"{CP}/installations/{data['installation_id']}/revoke", headers=ADMIN, timeout=15)
    assert rr.status_code == 200, rr.text
    r, _ = _signed_refresh(data["installation_id"], priv)
    assert r.status_code == 403


def test_revoke_requires_admin():
    data, _priv = _activate()
    assert requests.post(f"{CP}/installations/{data['installation_id']}/revoke", timeout=15).status_code == 401


# ---------------- signing-key rotation ----------------

def test_signing_key_rotation_retains_verification():
    data, priv = _activate()
    old = ent.verify_entitlement(data["entitlement_jws"], _trusted(data["signing_public_keys"]))
    old_kid = old.kid
    rot = requests.post(f"{CP}/signing-keys/rotate", headers=ADMIN, timeout=15)
    assert rot.status_code == 200, rot.text
    new_kid = rot.json()["active_kid"]
    assert new_kid != old_kid
    # new refresh uses the new ACTIVE key; retired key still returned for verification
    r, _ = _signed_refresh(data["installation_id"], priv)
    pem_map = r.json()["signing_public_keys"]
    assert new_kid in pem_map and old_kid in pem_map
    new_e = ent.verify_entitlement(r.json()["entitlement_jws"], _trusted(pem_map))
    assert new_e.kid == new_kid
    # the ORIGINAL activation entitlement still verifies against the (now retired) key set
    assert ent.verify_entitlement(data["entitlement_jws"], _trusted(pem_map)).kid == old_kid


# ---------------- subscription updates -> C0 policy ----------------

def test_subscription_update_reflected_in_entitlement():
    data, priv = _activate()
    up = requests.put(f"{CP}/subscriptions/{data['company_id']}", json={"state": "SUSPENDED", "seats": 5}, headers=ADMIN, timeout=15)
    assert up.status_code == 200, up.text
    r, _ = _signed_refresh(data["installation_id"], priv)
    e = ent.verify_entitlement(r.json()["entitlement_jws"], _trusted(r.json()["signing_public_keys"]))
    assert e.subscription_state == "SUSPENDED"
    assert state_mod.evaluate(e).business_access is False


# ---------------- version policy ----------------

def test_version_policy_get_and_update():
    r = requests.get(f"{CP}/version-policy", timeout=15)
    assert r.status_code == 200
    for k in ("office_latest", "office_min_supported", "mobile_latest", "mobile_min_supported"):
        assert k in r.json()
    up = requests.put(f"{CP}/version-policy", json={"mobile_min_supported": "1.2.0", "mobile_update_mandatory": True}, headers=ADMIN, timeout=15)
    assert up.status_code == 200, up.text
    assert up.json()["mobile_min_supported"] == "1.2.0" and up.json()["mobile_update_mandatory"] is True
    # persists
    assert requests.get(f"{CP}/version-policy", timeout=15).json()["mobile_min_supported"] == "1.2.0"


def test_version_policy_update_requires_admin():
    assert requests.put(f"{CP}/version-policy", json={"office_latest": "9.9.9"}, timeout=15).status_code == 401


# ---------------- module-level crypto helpers (identity/reqsig/trusted-keys) ----------------

def test_reqsig_roundtrip_and_tamper_detection():
    priv, pub_pem = _new_keypair()
    ts, nonce, body = str(int(time.time())), uuid.uuid4().hex, b"payload"
    sig = reqsig.sign_request(priv, installation_id="i", timestamp=ts, nonce=nonce, body=body)
    assert reqsig.verify_request(pub_pem, installation_id="i", timestamp=ts, nonce=nonce, body=body, signature_b64=sig)
    # wrong body fails
    assert not reqsig.verify_request(pub_pem, installation_id="i", timestamp=ts, nonce=nonce, body=b"other", signature_b64=sig)


def test_trusted_cp_keys_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(lkeys.config, "TRUSTED_KEYS_DIR", str(tmp_path))
    _priv, pub_pem = _new_keypair()
    lkeys.cache_trusted_cp_keys({"cp-test-kid": pub_pem})
    loaded = lkeys.load_trusted_cp_keys()
    assert "cp-test-kid" in loaded


def test_http_client_fetch_entitlement_end_to_end(tmp_path, monkeypatch):
    """Exercises licensing.HttpControlPlaneClient + identity + reqsig + trusted-key caching against
    the live Control Plane, in isolated temp dirs so the running installation identity is untouched."""
    import asyncio
    from licensing import identity, control_plane as lcp

    inst_dir = tmp_path / "inst"
    trust_dir = tmp_path / "trust"
    monkeypatch.setenv("INSTALLATION_KEYS_DIR", str(inst_dir))
    monkeypatch.setattr(lkeys.config, "TRUSTED_KEYS_DIR", str(trust_dir))
    monkeypatch.setattr(lcp.config, "CONTROL_PLANE_URL", CP)

    # Register PUBLIC key with the CP, then mark the subscription ACTIVE (post-payment) so the signed
    # refresh returns ACTIVE with the purchased seat quantity.
    _priv, pub_pem = identity.get_or_create_identity()
    reg = requests.post(f"{CP}/activate", json={
        "company_name": "HTTP Client Co", "requested_seats": 7, "installation_public_key": pub_pem,
        "software_version": "1.0.0", "bootstrap_credential": BOOTSTRAP,
    }, timeout=15)
    assert reg.status_code == 200, reg.text
    iid, cid = reg.json()["installation_id"], reg.json()["company_id"]
    assert requests.put(f"{CP}/subscriptions/{cid}", json={"state": "ACTIVE", "seats": 7},
                        headers=ADMIN, timeout=15).status_code == 200

    client = lcp.HttpControlPlaneClient()
    jws = asyncio.run(client.fetch_entitlement(None, installation_id=iid, company_id=cid))
    # Client cached the Control-Plane verify keys under the temp trusted dir -> verify offline.
    e = ent.verify_entitlement(jws, lkeys.get_trusted_verify_keys())
    assert e.installation_id == iid and e.seats_licensed == 7 and e.subscription_state == "ACTIVE"
