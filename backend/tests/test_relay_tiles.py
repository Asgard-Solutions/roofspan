"""Relay HTTP tile-passthrough tests (in-container proof) — ticket-based auth.

The Mobile app exchanges its device credentials + user token ONCE for a short-lived, opaque ticket
(POST /api/relay/tile-ticket), then fetches tiles with that ticket in the X-RoofSpan-Tile-Ticket
header. Credentials never appear in tile URLs, and tile URLs stay stable (offline-cache friendly).

MapTiler is not configured in-container, so a fully-authorized tile request routes end-to-end and the
Office tile endpoint answers 404 ("not configured") — proving the whole chain (ticket -> device
re-validation -> tunnel route -> Office tile proxy -> status propagation).
"""
import asyncio
import time
import uuid

import httpx
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from relay.tunnel_client import InstallationTunnel

LOCAL = "http://127.0.0.1:8001"
WS_INSTALL = "ws://127.0.0.1:8001/api/relay/installation"
CP = f"{LOCAL}/api/control-plane"
BOOTSTRAP = "dev-bootstrap-roofspan"
ADMIN = {"X-RoofSpan-Admin": "dev-admin-roofspan"}
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
TICKET_URL = f"{LOCAL}/api/relay/tile-ticket"


def _activate(seats=5):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    r = requests.post(f"{CP}/activate", json={"company_name": "Tile Co", "requested_seats": seats,
                      "installation_public_key": pub, "software_version": "1.0.0",
                      "bootstrap_credential": BOOTSTRAP}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json(), priv


def _sign_get(installation_id, priv):
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    sig = __import__("licensing.reqsig", fromlist=["reqsig"]).sign_request(
        priv, installation_id=installation_id, timestamp=ts, nonce=nonce, body=b"")
    return {"X-RoofSpan-Installation": installation_id, "X-RoofSpan-Timestamp": ts,
            "X-RoofSpan-Nonce": nonce, "X-RoofSpan-Signature": sig}


def _pair(data, priv):
    h = _sign_get(data["installation_id"], priv)
    p = requests.post(f"{CP}/pairing/create", headers=h, timeout=15).json()
    res = requests.post(f"{CP}/pairing/resolve", json={"token": p["token"], "label": "Tile iPhone"}, timeout=15).json()
    return res["device_id"], res["device_credential"]


def _owner_jwt():
    return requests.post(f"{LOCAL}/api/auth/login", json=OWNER, timeout=15).json()["access_token"]


def _mint(installation_id, device_id, credential, token):
    return requests.post(TICKET_URL, json={
        "installation_id": installation_id, "device_id": device_id,
        "device_credential": credential, "token": token}, timeout=15)


def _tile_url(kind, z=1, x=0, y=0):
    return f"{LOCAL}/api/relay/tiles/{kind}/{z}/{x}/{y}"


async def _with_tunnel(installation_id, priv, coro):
    tunnel = InstallationTunnel(WS_INSTALL, installation_id, priv, LOCAL)
    task = asyncio.create_task(tunnel.run())
    try:
        await asyncio.wait_for(tunnel.ready.wait(), timeout=10)
        return await coro()
    finally:
        tunnel.stop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ---- ticket minting authorization ------------------------------------------

def test_ticket_mint_rejects_unpaired_device():
    data, _ = _activate()
    r = _mint(data["installation_id"], str(uuid.uuid4()), "nope", "x")
    assert r.status_code == 403 and r.json().get("detail") == "device_not_paired"


def test_ticket_mint_rejects_wrong_credential():
    data, priv = _activate()
    device_id, _cred = _pair(data, priv)
    r = _mint(data["installation_id"], device_id, "wrong-secret", "x")
    assert r.status_code == 403 and r.json().get("detail") == "device_auth_failed"


def test_ticket_mint_succeeds_for_paired_device():
    data, priv = _activate()
    device_id, cred = _pair(data, priv)
    r = _mint(data["installation_id"], device_id, cred, _owner_jwt())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ticket") and body.get("expires_in", 0) > 0


# ---- tile GET (ticket header) ----------------------------------------------

def test_tile_unknown_kind_rejected():
    r = requests.get(_tile_url("bogus"), timeout=15)
    assert r.status_code == 404


def test_tile_missing_ticket_unauthorized():
    r = requests.get(_tile_url("satellite"), timeout=15)
    assert r.status_code == 401 and r.json().get("detail") == "invalid_or_expired_ticket"


def test_tile_invalid_ticket_unauthorized():
    r = requests.get(_tile_url("satellite"), headers={"X-RoofSpan-Tile-Ticket": "garbage"}, timeout=15)
    assert r.status_code == 401


def test_tile_office_offline_when_no_tunnel():
    data, priv = _activate()
    device_id, cred = _pair(data, priv)
    ticket = _mint(data["installation_id"], device_id, cred, _owner_jwt()).json()["ticket"]
    r = requests.get(_tile_url("satellite"), headers={"X-RoofSpan-Tile-Ticket": ticket}, timeout=15)
    assert r.status_code == 503 and r.json().get("detail") == "office_offline"


def test_tile_revoked_device_blocked_even_with_ticket():
    data, priv = _activate()
    device_id, cred = _pair(data, priv)
    ticket = _mint(data["installation_id"], device_id, cred, _owner_jwt()).json()["ticket"]
    # Revoke the device AFTER minting; the tile endpoint must re-validate and refuse.
    assert requests.post(f"{CP}/pairing/devices/{device_id}/revoke", headers=ADMIN, timeout=15).status_code == 200
    r = requests.get(_tile_url("satellite"), headers={"X-RoofSpan-Tile-Ticket": ticket}, timeout=15)
    assert r.status_code == 403 and r.json().get("detail") == "device_not_paired"


def test_tile_routes_through_tunnel_to_office():
    data, priv = _activate()
    device_id, cred = _pair(data, priv)
    ticket = _mint(data["installation_id"], device_id, cred, _owner_jwt()).json()["ticket"]

    async def scenario():
        async def inner():
            async with httpx.AsyncClient(timeout=20) as c:
                return await c.get(_tile_url("satellite"), headers={"X-RoofSpan-Tile-Ticket": ticket})
        return await _with_tunnel(data["installation_id"], priv, inner)

    r = asyncio.run(scenario())
    # 404 => reached the Office satellite proxy (MapTiler not configured). Never 401/403.
    assert r.status_code == 404, (r.status_code, r.text)


def test_tile_bad_user_token_propagates_401():
    data, priv = _activate()
    device_id, cred = _pair(data, priv)
    ticket = _mint(data["installation_id"], device_id, cred, "not-a-valid-jwt").json()["ticket"]

    async def scenario():
        async def inner():
            async with httpx.AsyncClient(timeout=20) as c:
                return await c.get(_tile_url("buildings"), headers={"X-RoofSpan-Tile-Ticket": ticket})
        return await _with_tunnel(data["installation_id"], priv, inner)

    r = asyncio.run(scenario())
    # Office get_current_user rejects the embedded token -> 401 propagated.
    assert r.status_code == 401, (r.status_code, r.text)
