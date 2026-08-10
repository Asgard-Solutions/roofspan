"""REAL-Valkey Secure Relay integration suite (gated by RELAY_RUN_INTEGRATION=1).

Exercises the ACTUAL production path — ValkeyRegistry (atomic Lua ownership), ValkeyTransport
(real Redis/Valkey Pub/Sub), TTL liveness, heartbeat re-claim, reconnect, and a genuine TWO-PROCESS
cross-node request/response — against a REAL Redis-compatible server. NO MemoryRegistry / InProcessBus
is used here. NO production credentials are used (local/test values only).

NOTE: local Docker/managed Redis runs WITHOUT TLS — this validates protocol/PubSub/Lua/TTL/reconnect
only. Real AWS ElastiCache Valkey TLS connectivity remains HUMAN REQUIRED at deploy time.
"""
import asyncio
import os
import subprocess
import sys
import time
import uuid

import pytest
import redis as redislib
import requests
import websockets
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from relay import config as C
from relay import protocol as P
from relay.hub import RelayHub, InstallationConn, RelayUnavailable, RelayPayloadTooLarge
from relay.registry import ValkeyRegistry, _route_key
from relay.transport import ValkeyTransport

pytestmark = pytest.mark.integration

LOCAL = "http://127.0.0.1:8001"
CP = f"{LOCAL}/api/control-plane"
BOOTSTRAP = "dev-bootstrap-roofspan"
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}


# ---- office-tunnel stand-in (NOT the Valkey path; the local Office WebSocket) ----------------
class FakeTunnelWS:
    def __init__(self, hub, installation_id, responder):
        self.hub = hub
        self.installation_id = installation_id
        self.responder = responder

    async def send_text(self, s):
        frame = P.loads(s)
        resp = self.responder(frame)
        if resp is not None:
            asyncio.create_task(self._respond(frame["request_id"], resp))

    async def _respond(self, rid, resp):
        self.hub.resolve(self.installation_id, rid, resp)


def _ok(frame):
    return {"type": "response", "request_id": frame["request_id"], "status": 200,
            "headers": {}, "body": P.b64e(b"ok")}


def _req(rid, path="/api/health"):
    return {"type": "request", "request_id": rid, "method": "GET", "path": path, "headers": {}, "body": ""}


async def _make_node(url, node_id, ttl=45):
    reg = ValkeyRegistry(url, node_id, ttl=ttl)
    tr = ValkeyTransport(url, node_id)
    hub = RelayHub(node_id, registry=reg, transport=tr)
    await hub.startup()
    await asyncio.sleep(0.35)  # let the real SUBSCRIBE become active
    return hub, reg


async def _close(hub, reg):
    await hub.shutdown()
    await reg.aclose()


# =============================================================================================
# Real Valkey: registry, transport, ownership, TTL
# =============================================================================================
def test_valkey_reachable(valkey_url, flush_valkey):
    r = redislib.from_url(valkey_url, decode_responses=True)
    assert r.ping() is True
    ver = r.info("server").get("redis_version") or r.info("server").get("valkey_version")
    assert ver
    r.close()


def test_cross_node_request_response(valkey_url, flush_valkey):
    """B -> real Valkey lookup -> real Pub/Sub -> A -> Office tunnel -> A -> Pub/Sub -> B."""
    async def scenario():
        hubA, regA = await _make_node(valkey_url, "node-a")
        hubB, regB = await _make_node(valkey_url, "node-b")
        try:
            iid = uuid.uuid4().hex
            await hubA.register(InstallationConn(iid, FakeTunnelWS(hubA, iid, _ok)))
            await asyncio.sleep(0.1)
            resp = await hubB.route(iid, _req("r1"), timeout=8)
            assert resp["status"] == 200 and P.b64d(resp["body"]) == b"ok"
            assert hubB._cross_pending == {}
        finally:
            await _close(hubA, regA)
            await _close(hubB, regB)

    asyncio.run(scenario())


def test_registration_key_ttl_present(valkey_url, flush_valkey):
    async def scenario():
        reg = ValkeyRegistry(valkey_url, "node-a", ttl=45)
        iid = uuid.uuid4().hex
        await reg.register(iid)
        r = redislib.from_url(valkey_url, decode_responses=True)
        assert r.get(_route_key(iid)) == "node-a"       # correct node id stored
        assert 0 < r.ttl(_route_key(iid)) <= 45          # TTL present
        r.close()
        await reg.aclose()

    asyncio.run(scenario())


def test_heartbeat_extends_ttl(valkey_url, flush_valkey):
    async def scenario():
        reg = ValkeyRegistry(valkey_url, "node-a", ttl=2)
        iid = uuid.uuid4().hex
        await reg.register(iid)
        await asyncio.sleep(1.2)
        assert await reg.heartbeat(iid) is True          # renews (owner)
        await asyncio.sleep(1.2)                          # 2.4s total > initial 2s TTL
        assert await reg.lookup_node(iid) == "node-a"     # survived thanks to renewal
        await reg.aclose()

    asyncio.run(scenario())


def test_stale_registration_expires(valkey_url, flush_valkey):
    async def scenario():
        reg = ValkeyRegistry(valkey_url, "node-a", ttl=1)
        iid = uuid.uuid4().hex
        await reg.register(iid)
        await asyncio.sleep(1.5)
        assert await reg.lookup_node(iid) is None         # TTL expired -> not routable
        await reg.aclose()

    asyncio.run(scenario())


def test_atomic_ownership_newest_wins_and_owner_safe(valkey_url, flush_valkey):
    """Real Lua: A registers X; B becomes newer owner; A's heartbeat/unregister must NOT clobber B."""
    async def scenario():
        regA = ValkeyRegistry(valkey_url, "node-a")
        regB = ValkeyRegistry(valkey_url, "node-b")
        iid = uuid.uuid4().hex
        await regA.register(iid)
        await regB.register(iid)                          # newest wins
        assert await regA.lookup_node(iid) == "node-b"
        assert await regA.heartbeat(iid) is False         # stale owner cannot renew/clobber
        await regA.unregister(iid)                        # compare-and-delete: no-op for stale A
        assert await regB.lookup_node(iid) == "node-b"    # B still owns
        assert await regB.heartbeat(iid) is True
        await regA.aclose()
        await regB.aclose()

    asyncio.run(scenario())


def test_duplicate_reconnect_keeps_new_owner(valkey_url, flush_valkey):
    async def scenario():
        regA = ValkeyRegistry(valkey_url, "node-a")
        regB = ValkeyRegistry(valkey_url, "node-b")
        iid = uuid.uuid4().hex
        await regA.register(iid)                          # A owns
        await regB.register(iid)                          # same installation reconnects on B
        assert await regB.lookup_node(iid) == "node-b"
        await regA.unregister(iid)                        # A disconnects afterwards
        assert await regB.lookup_node(iid) == "node-b"    # B remains registered/routable
        await regA.aclose()
        await regB.aclose()

    asyncio.run(scenario())


def test_node_death_ttl_cleanup_and_recovery(valkey_url, flush_valkey):
    async def scenario():
        iid = uuid.uuid4().hex
        regA = ValkeyRegistry(valkey_url, "node-a", ttl=2)
        await regA.register(iid)
        await regA.aclose()                               # node A "dies" — no more heartbeats
        await asyncio.sleep(2.4)
        regC = ValkeyRegistry(valkey_url, "node-c", ttl=2)
        assert await regC.lookup_node(iid) is None        # dead route cleaned by TTL
        await regC.register(iid)                          # recovery via a live node
        assert await regC.lookup_node(iid) == "node-c"
        await regC.aclose()

    asyncio.run(scenario())


def test_pending_timeout_cleanup_then_recovers(valkey_url, flush_valkey, monkeypatch):
    monkeypatch.setattr(C, "REQUEST_TIMEOUT", 0.4)

    async def scenario():
        hubA, regA = await _make_node(valkey_url, "node-a")
        hubB, regB = await _make_node(valkey_url, "node-b")
        try:
            iid = uuid.uuid4().hex
            await hubA.register(InstallationConn(iid, FakeTunnelWS(hubA, iid, lambda f: None)))  # never answers
            await asyncio.sleep(0.1)
            with pytest.raises((asyncio.TimeoutError, TimeoutError)):
                await hubB.route(iid, _req("r1"), timeout=0.5)
            assert hubB._cross_pending == {}              # no leak
            # A valid tunnel replaces the dead one -> subsequent request works
            await hubA.register(InstallationConn(iid, FakeTunnelWS(hubA, iid, _ok)))
            await asyncio.sleep(0.1)
            resp = await hubB.route(iid, _req("r2"), timeout=8)
            assert resp["status"] == 200
        finally:
            await _close(hubA, regA)
            await _close(hubB, regB)

    asyncio.run(scenario())


def test_payload_bounds_over_limit_rejected_before_publish(valkey_url, flush_valkey, monkeypatch):
    monkeypatch.setattr(C, "MAX_ENVELOPE_BYTES", 512)

    async def scenario():
        hubA, regA = await _make_node(valkey_url, "node-a")
        hubB, regB = await _make_node(valkey_url, "node-b")
        try:
            iid = uuid.uuid4().hex
            await hubA.register(InstallationConn(iid, FakeTunnelWS(hubA, iid, _ok)))
            await asyncio.sleep(0.1)
            small = await hubB.route(iid, _req("r1"), timeout=8)   # normal request ok
            assert small["status"] == 200
            big = _req("r2")
            big["body"] = "A" * 2000                                # exceeds 512-byte envelope ceiling
            with pytest.raises(RelayPayloadTooLarge):
                await hubB.route(iid, big, timeout=8)
            assert hubB._cross_pending == {}
        finally:
            await _close(hubA, regA)
            await _close(hubB, regB)

    asyncio.run(scenario())


def test_malformed_pubsub_message_is_survived(valkey_url, flush_valkey):
    async def scenario():
        hubA, regA = await _make_node(valkey_url, "node-a")
        hubB, regB = await _make_node(valkey_url, "node-b")
        try:
            r = redislib.from_url(valkey_url, decode_responses=True)
            r.publish("relay:node:node-b", "this is not json")            # garbage
            r.publish("relay:node:node-b", P.dumps({"relay_internal_version": 99, "type": "request"}))
            r.close()
            await asyncio.sleep(0.3)
            # Node B is still alive and routing works after malformed input.
            iid = uuid.uuid4().hex
            await hubA.register(InstallationConn(iid, FakeTunnelWS(hubA, iid, _ok)))
            await asyncio.sleep(0.1)
            resp = await hubB.route(iid, _req("r1"), timeout=8)
            assert resp["status"] == 200
        finally:
            await _close(hubA, regA)
            await _close(hubB, regB)

    asyncio.run(scenario())


def test_pubsub_reconnect_after_valkey_restart(managed_valkey, monkeypatch):
    """Interrupt Valkey; verify the transport read loop reconnects AND heartbeat re-claims ownership
    so cross-node routing RECOVERS (not silently dead)."""
    monkeypatch.setattr(C, "HEARTBEAT_INTERVAL", 1.0)
    url = managed_valkey.url

    async def scenario():
        hubA, regA = await _make_node(url, "node-a", ttl=5)
        hubB, regB = await _make_node(url, "node-b", ttl=5)
        try:
            iid = uuid.uuid4().hex
            await hubA.register(InstallationConn(iid, FakeTunnelWS(hubA, iid, _ok)))
            await asyncio.sleep(0.2)
            assert (await hubB.route(iid, _req("r1"), timeout=8))["status"] == 200  # baseline

            managed_valkey.stop()               # Valkey interruption (data lost — no persistence)
            await asyncio.sleep(0.5)
            managed_valkey.start()              # bring it back

            # Poll: read loop must reconnect and heartbeat must re-claim the (now-absent) route.
            recovered = False
            deadline = time.time() + 25
            while time.time() < deadline:
                try:
                    r = await hubB.route(iid, _req(uuid.uuid4().hex), timeout=3)
                    if r.get("status") == 200:
                        recovered = True
                        break
                except Exception:  # noqa: BLE001 - transport still recovering; keep polling
                    pass
                await asyncio.sleep(1.0)
            assert recovered, "cross-node routing did NOT recover after Valkey restart (reconnect blocker)"
        finally:
            await _close(hubA, regA)
            await _close(hubB, regB)

    asyncio.run(scenario())


# =============================================================================================
# Readiness + production startup fail-fast (real process/real Valkey)
# =============================================================================================
def test_relay_readiness_reflects_valkey_health(valkey_url, flush_valkey, monkeypatch):
    import relay_app
    from fastapi import HTTPException

    async def scenario():
        monkeypatch.setenv("RELAY_REGISTRY", "valkey")
        monkeypatch.setenv("RELAY_VALKEY_URL", valkey_url)
        res = await relay_app.relay_health()
        assert res["status"] == "ok" and res["checks"]["valkey"] is True
        # Valkey unavailable -> production readiness must fail (not merely "process alive").
        monkeypatch.setenv("RELAY_VALKEY_URL", "redis://127.0.0.1:1")  # dead
        with pytest.raises(HTTPException) as ei:
            await relay_app.relay_health()
        assert ei.value.status_code == 503

    asyncio.run(scenario())


def _run_config_check(env_overrides):
    env = os.environ.copy()
    env.pop("RELAY_NODE_ID", None)
    env.pop("ECS_CONTAINER_METADATA_URI_V4", None)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "from relay import config; config.require_production_config()"],
        cwd="/app/backend", env=env, capture_output=True, text=True,
    )


def test_startup_fail_fast_real_process():
    # memory registry in production -> refuse
    assert _run_config_check({"RELAY_ENV": "production", "RELAY_REGISTRY": "memory",
                              "RELAY_NODE_ID": "node-x"}).returncode != 0
    # missing Valkey URL -> refuse
    assert _run_config_check({"RELAY_ENV": "production", "RELAY_REGISTRY": "valkey",
                              "RELAY_VALKEY_URL": "", "RELAY_NODE_ID": "node-x"}).returncode != 0
    # missing unique node identity (no RELAY_NODE_ID, no ECS metadata) -> refuse
    assert _run_config_check({"RELAY_ENV": "production", "RELAY_REGISTRY": "valkey",
                              "RELAY_VALKEY_URL": "redis://x:6379"}).returncode != 0
    # fully configured -> ok
    assert _run_config_check({"RELAY_ENV": "production", "RELAY_REGISTRY": "valkey",
                              "RELAY_VALKEY_URL": "redis://x:6379", "RELAY_NODE_ID": "node-x"}).returncode == 0


# =============================================================================================
# TWO REAL RELAY PROCESSES — full cross-node E2E over real Valkey
# =============================================================================================
def _sign_get(installation_id, priv):
    from licensing import reqsig
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    sig = reqsig.sign_request(priv, installation_id=installation_id, timestamp=ts, nonce=nonce, body=b"")
    return {"X-RoofSpan-Installation": installation_id, "X-RoofSpan-Timestamp": ts,
            "X-RoofSpan-Nonce": nonce, "X-RoofSpan-Signature": sig}


def _activate(seats=5):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    r = requests.post(f"{CP}/activate", json={"company_name": "Relay E2E", "requested_seats": seats,
                      "installation_public_key": pub, "software_version": "1.0.0",
                      "bootstrap_credential": BOOTSTRAP}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json(), priv


def _pair(data, priv):
    h = _sign_get(data["installation_id"], priv)
    p = requests.post(f"{CP}/pairing/create", headers=h, timeout=15).json()
    res = requests.post(f"{CP}/pairing/resolve", json={"token": p["token"], "label": "E2E iPhone"}, timeout=15).json()
    return res["device_id"], res["device_credential"]


def _spawn_relay(port, node_id, valkey_url):
    env = os.environ.copy()
    env.update({"RELAY_ENV": "production", "RELAY_REGISTRY": "valkey",
                "RELAY_VALKEY_URL": valkey_url, "RELAY_NODE_ID": node_id})
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "relay_app:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd="/app/backend", env=env)
    ok = False
    for _ in range(60):
        try:
            if requests.get(f"http://127.0.0.1:{port}/api/relay/health", timeout=2).status_code == 200:
                ok = True
                break
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    if not ok:
        proc.terminate()
        raise RuntimeError(f"relay node {node_id} did not become healthy on {port}")
    return proc


def test_two_process_cross_node_e2e(valkey_url, flush_valkey):
    # main Office backend on 8001 must be running (control plane + local API target).
    assert requests.get(f"{LOCAL}/api/health", timeout=5).status_code == 200
    relay_a = _spawn_relay(9101, "node-a", valkey_url)
    relay_b = _spawn_relay(9102, "node-b", valkey_url)
    tunnel = None
    task = None
    try:
        data, priv = _activate()
        device_id, cred = _pair(data, priv)
        iid = data["installation_id"]

        async def scenario():
            nonlocal tunnel, task
            from relay.tunnel_client import InstallationTunnel
            # Office installation opens its OUTBOUND tunnel to relay NODE A (a real separate process).
            tunnel = InstallationTunnel(f"ws://127.0.0.1:9101/api/relay/installation", iid, priv, LOCAL)
            task = asyncio.create_task(tunnel.run())
            await asyncio.wait_for(tunnel.ready.wait(), timeout=15)
            await asyncio.sleep(0.5)  # allow ValkeyRegistry.register to land

            # Mobile connects to relay NODE B (the other process) and issues a request.
            ws = await websockets.connect("ws://127.0.0.1:9102/api/relay/mobile")
            await ws.send(P.dumps({"type": P.T_HELLO, "installation_id": iid, "device_id": device_id,
                                   "device_credential": cred, "protocol": P.PROTOCOL_VERSION}))
            ready = P.loads(await ws.recv())
            assert ready.get("type") == P.T_READY, ready
            rid = uuid.uuid4().hex
            await ws.send(P.dumps({"type": P.T_REQUEST, "request_id": rid, "method": "GET",
                                   "path": "/api/health", "headers": {}, "body": ""}))
            resp = P.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            await ws.close()
            return resp

        resp = asyncio.run(scenario())
        # Proves the request traversed: Mobile -> node B -> Valkey -> node A -> Office -> back.
        assert resp["type"] == P.T_RESPONSE and resp["status"] == 200, resp
        assert b"roofspan-office" in P.b64d(resp["body"])
    finally:
        if tunnel is not None:
            tunnel.stop()
        if task is not None:
            task.cancel()
        for p in (relay_a, relay_b):
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()
