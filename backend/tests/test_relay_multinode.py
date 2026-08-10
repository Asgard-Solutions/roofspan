"""Multi-node Secure Relay routing tests (network-free, in-process).

Spins up TWO RelayHub instances sharing an in-process Pub/Sub bus + a shared async registry keyspace,
plus a fake installation tunnel, to prove cross-node routing/correlation and all ownership/lifecycle
edges WITHOUT binding any socket or requiring real Valkey. Real Valkey/ElastiCache integration is
HUMAN REQUIRED before the first production AWS apply (see completion report).
"""
import asyncio
import base64
import time

import pytest

from relay import config as C
from relay import envelope as E
from relay import protocol as P
from relay.hub import RelayHub, InstallationConn, RelayUnavailable, RelayPayloadTooLarge
from relay.registry import AsyncMemoryRegistry, node_channel
from relay.transport import InProcessBus


# ---- helpers ---------------------------------------------------------------
class FakeTunnelWS:
    """Stands in for an Office installation's outbound tunnel. When the hub sends it a routed
    request frame, it schedules a response back through hub.resolve (unless responder returns None,
    simulating a hung/absent installation)."""

    def __init__(self, hub, installation_id, responder):
        self.hub = hub
        self.installation_id = installation_id
        self.responder = responder
        self.sent = []

    async def send_text(self, s):
        frame = P.loads(s)
        self.sent.append(frame)
        rid = frame["request_id"]
        resp = self.responder(frame)
        if resp is None:
            return  # no response -> caller will time out
        asyncio.create_task(self._respond(rid, resp))

    async def _respond(self, rid, resp):
        self.hub.resolve(self.installation_id, rid, resp)


def _ok_responder(frame):
    return {"type": "response", "request_id": frame["request_id"], "status": 200,
            "headers": {}, "body": P.b64e(b"ok")}


async def _attach_tunnel(hub, installation_id, responder=_ok_responder):
    ws = FakeTunnelWS(hub, installation_id, responder)
    conn = InstallationConn(installation_id, ws)
    await hub.register(conn)
    return conn


def _make_two_node():
    store = {}
    bus = InProcessBus()
    regA = AsyncMemoryRegistry("A", store=store)
    regB = AsyncMemoryRegistry("B", store=store)
    hubA = RelayHub("A", registry=regA, transport=bus)
    hubB = RelayHub("B", registry=regB, transport=bus)
    return store, bus, hubA, hubB


def _req(rid, path="/api/health"):
    return {"type": "request", "request_id": rid, "method": "GET", "path": path, "headers": {}, "body": ""}


# ---- cross-node routing ----------------------------------------------------
def test_cross_node_happy_path():
    async def scenario():
        _, _, hubA, hubB = _make_two_node()
        await hubA.startup(); await hubB.startup()
        try:
            await _attach_tunnel(hubA, "inst-1")  # tunnel lives on A
            resp = await hubB.route("inst-1", _req("r1"), timeout=5)  # request originates on B
            assert resp["status"] == 200
            assert P.b64d(resp["body"]) == b"ok"
            assert hubB._cross_pending == {}  # correlation cleaned up
        finally:
            await hubA.shutdown(); await hubB.shutdown()

    asyncio.run(scenario())


def test_same_node_routes_directly():
    async def scenario():
        _, bus, hubA, hubB = _make_two_node()
        await hubA.startup(); await hubB.startup()
        try:
            await _attach_tunnel(hubB, "inst-1")  # tunnel local to B
            resp = await hubB.route("inst-1", _req("r1"), timeout=5)
            assert resp["status"] == 200
            assert hubB._cross_pending == {}  # never used cross-node path
        finally:
            await hubA.shutdown(); await hubB.shutdown()

    asyncio.run(scenario())


def test_unknown_installation_unavailable():
    async def scenario():
        _, _, hubA, hubB = _make_two_node()
        await hubA.startup(); await hubB.startup()
        try:
            with pytest.raises(RelayUnavailable):
                await hubB.route("nope", _req("r1"), timeout=1)
        finally:
            await hubA.shutdown(); await hubB.shutdown()

    asyncio.run(scenario())


def test_cross_node_timeout_cleans_pending(monkeypatch):
    monkeypatch.setattr(C, "REQUEST_TIMEOUT", 0.3)

    async def scenario():
        _, _, hubA, hubB = _make_two_node()
        await hubA.startup(); await hubB.startup()
        try:
            await _attach_tunnel(hubA, "inst-1", responder=lambda f: None)  # never responds
            with pytest.raises((asyncio.TimeoutError, TimeoutError)):
                await hubB.route("inst-1", _req("r1"), timeout=0.1)
            assert hubB._cross_pending == {}  # future removed on timeout
        finally:
            await hubA.shutdown(); await hubB.shutdown()

    asyncio.run(scenario())


def test_target_node_disappears_fails_cleanly():
    async def scenario():
        _, bus, hubA, hubB = _make_two_node()
        await hubA.startup(); await hubB.startup()
        try:
            await _attach_tunnel(hubA, "inst-1")
            await bus.unsubscribe(node_channel("A"))  # node A vanishes (crash) but TTL not yet expired
            with pytest.raises((asyncio.TimeoutError, TimeoutError)):
                await hubB.route("inst-1", _req("r1"), timeout=0.2)
            assert hubB._cross_pending == {}
        finally:
            await hubA.shutdown(); await hubB.shutdown()

    asyncio.run(scenario())


def test_installation_disconnect_fails_cleanly():
    async def scenario():
        _, _, hubA, hubB = _make_two_node()
        await hubA.startup(); await hubB.startup()
        try:
            conn = await _attach_tunnel(hubA, "inst-1")
            await hubA.unregister("inst-1", conn)  # tunnel disconnects, releases ownership
            with pytest.raises(RelayUnavailable):
                await hubB.route("inst-1", _req("r1"), timeout=1)
        finally:
            await hubA.shutdown(); await hubB.shutdown()

    asyncio.run(scenario())


def test_duplicate_response_resolves_once():
    async def scenario():
        _, _, _, hubB = _make_two_node()
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        hubB._cross_pending["c1"] = fut
        env = E.build_response("A", "B", "inst-1", "c1", {"status": 200})
        hubB._handle_remote_response(env)
        assert fut.result() == {"status": 200}
        hubB._handle_remote_response(env)  # duplicate/late — must be a safe no-op
        hubB._handle_remote_response(E.build_response("A", "B", "inst-1", "unknown", {"status": 200}))

    asyncio.run(scenario())


def test_malformed_envelope_rejected_safely():
    async def scenario():
        _, _, _, hubB = _make_two_node()
        await hubB._on_envelope("this is not json")
        await hubB._on_envelope(P.dumps({"relay_internal_version": 2, "type": "request"}))
        await hubB._on_envelope(P.dumps({"relay_internal_version": 1, "type": "bogus"}))
        with pytest.raises(E.EnvelopeError):
            E.validate({"relay_internal_version": 1, "type": "request", "source_node": "A",
                        "target_node": "B", "installation_id": "i", "correlation_id": "c", "frame": "notdict"})
        assert hubB._cross_pending == {}

    asyncio.run(scenario())


def test_oversize_envelope_rejected_before_publish(monkeypatch):
    monkeypatch.setattr(C, "MAX_ENVELOPE_BYTES", 200)

    async def scenario():
        _, _, hubA, hubB = _make_two_node()
        await hubA.startup(); await hubB.startup()
        try:
            await _attach_tunnel(hubA, "inst-1")
            frame = _req("r1")
            frame["body"] = "A" * 500  # pushes the envelope over the 200-byte ceiling
            with pytest.raises(RelayPayloadTooLarge):
                await hubB.route("inst-1", frame, timeout=1)
            assert hubB._cross_pending == {}  # nothing left pending; publish never happened
        finally:
            await hubA.shutdown(); await hubB.shutdown()

    asyncio.run(scenario())


# ---- ownership / lifecycle -------------------------------------------------
def test_newest_tunnel_wins():
    async def scenario():
        store = {}
        regA = AsyncMemoryRegistry("A", store=store)
        regB = AsyncMemoryRegistry("B", store=store)
        await regA.register("inst-1")
        assert await regB.lookup_node("inst-1") == "A"
        await regB.register("inst-1")  # reconnect lands on node B — newest wins
        assert await regA.lookup_node("inst-1") == "B"

    asyncio.run(scenario())


def test_old_owner_cannot_delete_new_owner():
    async def scenario():
        store = {}
        regA = AsyncMemoryRegistry("A", store=store)
        regB = AsyncMemoryRegistry("B", store=store)
        await regA.register("inst-1")
        await regB.register("inst-1")           # B now owns
        await regA.unregister("inst-1")         # stale A disconnect must NOT drop B's route
        assert await regB.lookup_node("inst-1") == "B"
        assert await regA.heartbeat("inst-1") is False  # stale owner can't renew

    asyncio.run(scenario())


def test_ttl_expiry_makes_owner_unroutable():
    async def scenario():
        clock = {"t": 1000.0}
        reg = AsyncMemoryRegistry("A", ttl=45, now=lambda: clock["t"])
        await reg.register("inst-1")
        assert await reg.lookup_node("inst-1") == "A"
        clock["t"] += 100  # past TTL — dead node
        assert await reg.lookup_node("inst-1") is None

    asyncio.run(scenario())


def test_heartbeat_renews_ttl():
    async def scenario():
        clock = {"t": 1000.0}
        regA = AsyncMemoryRegistry("A", ttl=45, now=lambda: clock["t"])
        regB = AsyncMemoryRegistry("B", ttl=45, now=lambda: clock["t"], store=regA._reg)
        await regA.register("inst-1")           # expires at 1045
        clock["t"] = 1030.0
        assert await regA.heartbeat("inst-1") is True   # renew -> expires 1075
        assert await regB.heartbeat("inst-1") is False  # other node cannot renew our route
        clock["t"] = 1050.0
        assert await regA.lookup_node("inst-1") == "A"  # would have expired without renewal

    asyncio.run(scenario())


def test_max_upload_envelope_fits():
    """A max-size (20MB) upload base64-encoded into a request frame must fit the 28MB envelope
    ceiling with headroom — proves MAX_ENVELOPE_BYTES is not silently unbounded/insufficient."""
    body_b64 = base64.b64encode(b"\0" * C.MAX_UPLOAD_BYTES).decode()
    frame = {"type": "request", "request_id": "r1", "method": "POST", "path": "/api/mobile/photos",
             "headers": {"content-type": "application/octet-stream"}, "body": body_b64}
    env = E.build_request("B", "A", "inst-1", "r1", frame)
    size = len(P.dumps(env).encode("utf-8"))
    assert size <= C.MAX_ENVELOPE_BYTES, (size, C.MAX_ENVELOPE_BYTES)


# ---- production fail-fast ---------------------------------------------------
def test_production_requires_valkey_registry(monkeypatch):
    monkeypatch.setattr(C, "RELAY_ENV", "production")
    monkeypatch.setattr(C, "RELAY_REGISTRY", "memory")
    monkeypatch.setattr(C, "RELAY_VALKEY_URL", "rediss://x:6379")
    monkeypatch.setattr(C, "NODE_ID_SOURCE", "env")
    with pytest.raises(RuntimeError):
        C.require_production_config()


def test_production_requires_valkey_url(monkeypatch):
    monkeypatch.setattr(C, "RELAY_ENV", "production")
    monkeypatch.setattr(C, "RELAY_REGISTRY", "valkey")
    monkeypatch.setattr(C, "RELAY_VALKEY_URL", None)
    monkeypatch.setattr(C, "NODE_ID_SOURCE", "env")
    with pytest.raises(RuntimeError):
        C.require_production_config()


def test_production_requires_unique_node_id(monkeypatch):
    monkeypatch.setattr(C, "RELAY_ENV", "production")
    monkeypatch.setattr(C, "RELAY_REGISTRY", "valkey")
    monkeypatch.setattr(C, "RELAY_VALKEY_URL", "rediss://x:6379")
    monkeypatch.setattr(C, "NODE_ID_SOURCE", "random")  # no env / ECS identity established
    with pytest.raises(RuntimeError):
        C.require_production_config()


def test_production_config_ok_with_env_node_id(monkeypatch):
    monkeypatch.setattr(C, "RELAY_ENV", "production")
    monkeypatch.setattr(C, "RELAY_REGISTRY", "valkey")
    monkeypatch.setattr(C, "RELAY_VALKEY_URL", "rediss://x:6379")
    monkeypatch.setattr(C, "NODE_ID_SOURCE", "env")
    C.require_production_config()  # must not raise
