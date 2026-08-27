"""Relay HTTP tile-passthrough tests (in-container proof).

Proves the Mobile map can fetch Office MapTiler satellite/building tiles over plain HTTPS through the
Relay: the device is authenticated at the relay (installation active + device paired + entitled), then
the tile request is routed down the SAME installation tunnel to the Office's server-side MapTiler proxy.
The provider key never leaves the Office; the relay authorizes the device and forwards nothing else.

MapTiler is not configured in-container, so a fully-authorized request routes end-to-end and the Office
tile endpoint answers 404 ("not configured") — which proves the whole chain (device auth -> route ->
Office tile endpoint -> status propagation) without needing a real provider key.
"""
import asyncio
import time
import uuid

import httpx
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from relay.tunnel_client import InstallationTunnel

LOCAL = "http://127.0.0.1:8001"
WS_INSTALL = "ws://127.0.0.1:8001/api/relay/installation"
CP = f"{LOCAL}/api/control-plane"
BOOTSTRAP = "dev-bootstrap-roofspan"
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}


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


def _tile_url(kind, iid, did, dc, tok, z=1, x=0, y=0):
    return (f"{LOCAL}/api/relay/tiles/{kind}/{z}/{x}/{y}"
            f"?iid={iid}&did={did}&dc={dc}&tok={tok}")


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


def test_tile_unknown_kind_rejected():
    data, priv = _activate()
    device_id, cred = _pair(data, priv)
    r = requests.get(_tile_url("bogus", data["installation_id"], device_id, cred, "x"), timeout=15)
    assert r.status_code == 404


def test_tile_rejects_unpaired_device():
    data, _ = _activate()
    r = requests.get(_tile_url("satellite", data["installation_id"], str(uuid.uuid4()), "nope", "x"), timeout=15)
    assert r.status_code == 403
    assert r.json().get("detail") == "device_not_paired"


def test_tile_rejects_wrong_credential():
    data, priv = _activate()
    device_id, _cred = _pair(data, priv)
    r = requests.get(_tile_url("satellite", data["installation_id"], device_id, "wrong-secret", "x"), timeout=15)
    assert r.status_code == 403
    assert r.json().get("detail") == "device_auth_failed"


def test_tile_office_offline_when_no_tunnel():
    data, priv = _activate()
    device_id, cred = _pair(data, priv)
    tok = _owner_jwt()
    # Device authorized, but no installation tunnel is connected -> office_offline.
    r = requests.get(_tile_url("satellite", data["installation_id"], device_id, cred, tok), timeout=15)
    assert r.status_code == 503
    assert r.json().get("detail") == "office_offline"


def test_tile_routes_through_tunnel_to_office():
    """Full authorized passthrough: device auth OK + tunnel up + valid user token.
    MapTiler is not configured in-container, so the Office tile endpoint answers 404 and the relay
    propagates it — proving the request reached the Office tile proxy through the tunnel."""
    data, priv = _activate()
    device_id, cred = _pair(data, priv)
    tok = _owner_jwt()

    async def scenario():
        async def inner():
            url = _tile_url("satellite", data["installation_id"], device_id, cred, tok)
            async with httpx.AsyncClient(timeout=20) as c:
                return await c.get(url)
        return await _with_tunnel(data["installation_id"], priv, inner)

    r = asyncio.run(scenario())
    # 404 => reached Office satellite proxy (MapTiler not configured). Never 403 (device auth passed).
    assert r.status_code == 404, (r.status_code, r.text)


def test_tile_bad_user_token_propagates_401():
    data, priv = _activate()
    device_id, cred = _pair(data, priv)

    async def scenario():
        async def inner():
            url = _tile_url("satellite", data["installation_id"], device_id, cred, "not-a-valid-jwt")
            async with httpx.AsyncClient(timeout=20) as c:
                return await c.get(url)
        return await _with_tunnel(data["installation_id"], priv, inner)

    r = asyncio.run(scenario())
    # Office get_current_user rejects the token -> 401 propagated by the relay tile endpoint.
    assert r.status_code == 401, (r.status_code, r.text)
