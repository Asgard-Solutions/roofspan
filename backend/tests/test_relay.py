"""Phase C4 Secure Relay tests (in-container proof).

Proves: outbound installation tunnel (Ed25519 challenge-response auth), Mobile request routing with
response correlation, the full authorization chain (installation entitled + device paired + LOCAL
FastAPI RBAC authoritative), and resilience/security edges (unpaired/revoked device, suspended
license, bad signature, protocol mismatch, tunnel unavailable, duplicate request id).

Uses ws://127.0.0.1:8001 (in-container) so the protocol is proven deterministically. The tunnel
forwards to the LOCAL FastAPI — RBAC/auth stay local; the relay never becomes the RBAC authority.
"""
import asyncio
import json
import time
import uuid

import psycopg
import pytest
import requests
import websockets
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from relay import protocol as P
from relay.tunnel_client import InstallationTunnel

LOCAL = "http://127.0.0.1:8001"
WS_INSTALL = "ws://127.0.0.1:8001/api/relay/installation"
WS_MOBILE = "ws://127.0.0.1:8001/api/relay/mobile"
CP = f"{LOCAL}/api/control-plane"
BOOTSTRAP = "dev-bootstrap-roofspan"
ADMIN = {"X-RoofSpan-Admin": "dev-admin-roofspan"}
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}


def _activate(seats=5):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    r = requests.post(f"{CP}/activate", json={"company_name": "Relay Co", "requested_seats": seats,
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
    res = requests.post(f"{CP}/pairing/resolve", json={"token": p["token"], "label": "Test iPhone"}, timeout=15).json()
    return res["device_id"]


def _owner_jwt():
    return requests.post(f"{LOCAL}/api/auth/login", json=OWNER, timeout=15).json()["access_token"]


def _set_cp_state(company_id, state):
    cn = psycopg.connect(host="127.0.0.1", port=5432, user="roofspan", password="roofspan_local_pwd",
                         dbname="roofspan_control_plane")
    cn.execute("UPDATE subscriptions SET state=%s WHERE company_id=%s", (state, company_id))
    cn.commit()
    cn.close()


async def _mobile_open(installation_id, device_id):
    ws = await websockets.connect(WS_MOBILE)
    await ws.send(P.dumps({"type": P.T_HELLO, "installation_id": installation_id,
                           "device_id": device_id, "protocol": P.PROTOCOL_VERSION}))
    first = P.loads(await ws.recv())
    return ws, first


async def _mobile_request(ws, method, path, token=None, request_id=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    rid = request_id or uuid.uuid4().hex
    await ws.send(P.dumps({"type": P.T_REQUEST, "request_id": rid, "method": method,
                           "path": path, "headers": headers, "body": ""}))
    return P.loads(await ws.recv())


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


def test_relay_routes_mobile_request_with_local_rbac():
    data, priv = _activate()
    device_id = _pair(data, priv)
    token = _owner_jwt()

    async def scenario():
        async def inner():
            ws, ready = await _mobile_open(data["installation_id"], device_id)
            assert ready.get("type") == P.T_READY, ready
            # 1) health routed (no auth)
            h = await _mobile_request(ws, "GET", "/api/health")
            assert h["type"] == P.T_RESPONSE and h["status"] == 200
            assert b"roofspan-office" in P.b64d(h["body"])
            # 2) business route WITH owner JWT -> 200 (local RBAC authoritative)
            u = await _mobile_request(ws, "GET", "/api/users", token=token)
            assert u["status"] == 200, P.b64d(u["body"])
            # 3) same business route WITHOUT token -> 401 (relay does NOT bypass local auth)
            n = await _mobile_request(ws, "GET", "/api/users")
            assert n["status"] == 401
            await ws.close()
        return await _with_tunnel(data["installation_id"], priv, inner)

    asyncio.run(scenario())


def test_relay_rejects_unpaired_device():
    data, _ = _activate()

    async def scenario():
        ws, first = await _mobile_open(data["installation_id"], str(uuid.uuid4()))
        await ws.close()
        return first

    first = asyncio.run(scenario())
    assert first.get("type") == P.T_ERROR and first.get("code") == "device_not_paired"


def test_relay_rejects_revoked_device():
    data, priv = _activate()
    device_id = _pair(data, priv)
    assert requests.post(f"{CP}/pairing/devices/{device_id}/revoke", headers=ADMIN, timeout=15).status_code == 200

    async def scenario():
        ws, first = await _mobile_open(data["installation_id"], device_id)
        await ws.close()
        return first

    first = asyncio.run(scenario())
    assert first.get("code") == "device_not_paired"


def test_relay_blocks_suspended_subscription():
    data, priv = _activate()
    device_id = _pair(data, priv)
    _set_cp_state(data["company_id"], "SUSPENDED")

    async def scenario():
        ws, first = await _mobile_open(data["installation_id"], device_id)
        await ws.close()
        return first

    first = asyncio.run(scenario())
    assert first.get("code") == "subscription_inactive"


def test_relay_installation_bad_signature_fails_auth():
    data, _ = _activate()
    wrong = Ed25519PrivateKey.generate()  # not the registered key

    async def scenario():
        tunnel = InstallationTunnel(WS_INSTALL, data["installation_id"], wrong, LOCAL)
        task = asyncio.create_task(tunnel.run())
        try:
            ready = await asyncio.wait_for(tunnel.ready.wait(), timeout=4)
            return ready
        except asyncio.TimeoutError:
            return False
        finally:
            tunnel.stop()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    got_ready = asyncio.run(scenario())
    assert got_ready is False  # never became ready => auth rejected


def test_relay_protocol_mismatch():
    data, priv = _activate()
    device_id = _pair(data, priv)

    async def scenario():
        ws = await websockets.connect(WS_MOBILE)
        await ws.send(P.dumps({"type": P.T_HELLO, "installation_id": data["installation_id"],
                               "device_id": device_id, "protocol": "999"}))
        first = P.loads(await ws.recv())
        await ws.close()
        return first

    first = asyncio.run(scenario())
    assert first.get("code") == "protocol_mismatch"


def test_relay_tunnel_unavailable_when_installation_offline():
    data, priv = _activate()
    device_id = _pair(data, priv)
    token = _owner_jwt()

    async def scenario():
        ws, ready = await _mobile_open(data["installation_id"], device_id)  # no tunnel started
        assert ready.get("type") == P.T_READY
        r = await _mobile_request(ws, "GET", "/api/health", token=token)
        await ws.close()
        return r

    r = asyncio.run(scenario())
    assert r.get("type") == P.T_ERROR and r.get("code") == "tunnel_unavailable"


def test_relay_duplicate_request_id_rejected():
    data, priv = _activate()
    device_id = _pair(data, priv)

    async def scenario():
        async def inner():
            ws, ready = await _mobile_open(data["installation_id"], device_id)
            rid = uuid.uuid4().hex
            r1 = await _mobile_request(ws, "GET", "/api/health", request_id=rid)
            assert r1["type"] == P.T_RESPONSE and r1["status"] == 200
            r2 = await _mobile_request(ws, "GET", "/api/health", request_id=rid)
            await ws.close()
            return r2
        return await _with_tunnel(data["installation_id"], priv, inner)

    r2 = asyncio.run(scenario())
    assert r2.get("type") == P.T_ERROR and r2.get("code") == "duplicate_request"
