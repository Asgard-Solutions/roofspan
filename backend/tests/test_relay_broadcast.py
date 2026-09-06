"""Office->Field broadcast fan-out and acceptance semantics (network-free)."""
import asyncio
import json

from relay import protocol as P
from relay.hub import InstallationConn, RelayHub
from relay.registry import AsyncMemoryRegistry
from relay.transport import InProcessBus


class FakeDevice:
    def __init__(self):
        self.frames = []

    async def send_text(self, s):
        self.frames.append(json.loads(s))


class FakeSocket:
    def __init__(self):
        self.frames = []

    async def send_text(self, s):
        self.frames.append(json.loads(s))


class FailingTransport:
    async def publish(self, channel, message):
        raise RuntimeError("valkey unavailable")


class HangingTransport:
    async def publish(self, channel, message):
        await asyncio.Event().wait()


def _two_nodes():
    bus = InProcessBus()
    store = {}
    hub_a = RelayHub("nodeA", registry=AsyncMemoryRegistry("nodeA", store=store), transport=bus)
    hub_b = RelayHub("nodeB", registry=AsyncMemoryRegistry("nodeB", store=store), transport=bus)
    return hub_a, hub_b


FRAME = {"type": "measurement_changed", "event_id": "e1", "lead_id": "L1",
         "measurement_set_id": "S1", "revision_id": "R1", "updated_at": "2026-06-01T00:00:00+00:00"}


def test_cross_node_delivery_is_accepted_once_published():
    async def scenario():
        a, b = _two_nodes()
        await a.startup(); await b.startup()
        dev = FakeDevice()
        b.register_device("inst1", "k1", dev)
        result = await a.broadcast("inst1", FRAME)
        await asyncio.sleep(0.05)
        assert result.accepted is True
        assert result.delivered_local == 0
        assert len(dev.frames) == 1
        assert dev.frames[0]["event_id"] == "e1"
        await a.shutdown(); await b.shutdown()
    asyncio.run(scenario())


def test_origin_echo_dedupe():
    async def scenario():
        a, b = _two_nodes()
        await a.startup(); await b.startup()
        dev_a = FakeDevice()
        a.register_device("inst1", "k1", dev_a)
        result = await a.broadcast("inst1", FRAME)
        await asyncio.sleep(0.05)
        assert result.accepted is True
        assert result.delivered_local == 1
        assert len(dev_a.frames) == 1
        await a.shutdown(); await b.shutdown()
    asyncio.run(scenario())


def test_both_nodes_have_devices():
    async def scenario():
        a, b = _two_nodes()
        await a.startup(); await b.startup()
        dev_a, dev_b = FakeDevice(), FakeDevice()
        a.register_device("inst1", "ka", dev_a)
        b.register_device("inst1", "kb", dev_b)
        result = await a.broadcast("inst1", FRAME)
        await asyncio.sleep(0.05)
        assert result.accepted is True
        assert result.delivered_local == 1
        assert len(dev_a.frames) == 1
        assert len(dev_b.frames) == 1
        await a.shutdown(); await b.shutdown()
    asyncio.run(scenario())


def test_single_node_memory_mode_accepts_after_local_processing():
    async def scenario():
        hub = RelayHub("solo")
        dev = FakeDevice()
        hub.register_device("i", "k", dev)
        result = await hub.broadcast("i", FRAME)
        assert result.accepted is True
        assert result.delivered_local == 1
        assert len(dev.frames) == 1
    asyncio.run(scenario())


def test_unregister_stops_delivery_but_single_node_still_accepts():
    async def scenario():
        hub = RelayHub("solo2")
        dev = FakeDevice()
        hub.register_device("i", "k", dev)
        hub.unregister_device("i", "k")
        result = await hub.broadcast("i", FRAME)
        assert result.accepted is True
        assert result.delivered_local == 0
        assert dev.frames == []
        assert hub.device_count("i") == 0
    asyncio.run(scenario())


def test_publish_failure_is_not_accepted_even_after_local_delivery():
    async def scenario():
        hub = RelayHub("fail", transport=FailingTransport())
        dev = FakeDevice()
        hub.register_device("i", "k", dev)
        result = await hub.broadcast("i", FRAME)
        assert result.accepted is False
        assert result.reason == "publish_failed"
        assert result.delivered_local == 1
        assert len(dev.frames) == 1
    asyncio.run(scenario())


def test_publish_timeout_is_not_accepted():
    async def scenario():
        hub = RelayHub("hang", transport=HangingTransport(), broadcast_publish_timeout=0.01)
        result = await hub.broadcast("i", FRAME)
        assert result.accepted is False
        assert result.reason == "publish_timeout"
        assert result.delivered_local == 0
    asyncio.run(scenario())


def test_failed_cross_node_publish_sends_no_broadcast_ack():
    async def scenario():
        hub = RelayHub("fail-ack", transport=FailingTransport())
        dev = FakeDevice()
        hub.register_device("i", "k", dev)
        ws = FakeSocket()
        conn = InstallationConn("i", ws)
        result = await hub.broadcast_and_ack("i", FRAME, conn)
        assert result.accepted is False
        assert result.delivered_local == 1
        assert ws.frames == []
    asyncio.run(scenario())


def test_accepted_broadcast_sends_one_ack_with_stable_event_id():
    async def scenario():
        hub = RelayHub("ok-ack")
        ws = FakeSocket()
        conn = InstallationConn("i", ws)
        result = await hub.broadcast_and_ack("i", FRAME, conn)
        assert result.accepted is True
        assert len(ws.frames) == 1
        assert ws.frames[0]["type"] == P.T_BROADCAST_ACK
        assert ws.frames[0]["event_id"] == "e1"
    asyncio.run(scenario())
