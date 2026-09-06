"""Office->Field broadcast fan-out (network-free, in-process).

Proves the relay hub's new broadcast path: local delivery, cross-node delivery over the shared
broadcast channel, ORIGIN-echo de-duplication (the originating node never double-delivers when it
receives its own publication), single-node/memory delivery, and unregister. Uses InProcessBus +
AsyncMemoryRegistry so no socket/Valkey is required (mirrors test_relay_multinode.py).
"""
import asyncio
import json

from relay.hub import RelayHub
from relay.registry import AsyncMemoryRegistry
from relay.transport import InProcessBus


class FakeDevice:
    def __init__(self):
        self.frames = []

    async def send_text(self, s):
        self.frames.append(json.loads(s))


def _two_nodes():
    bus = InProcessBus()
    store = {}
    hub_a = RelayHub("nodeA", registry=AsyncMemoryRegistry("nodeA", store=store), transport=bus)
    hub_b = RelayHub("nodeB", registry=AsyncMemoryRegistry("nodeB", store=store), transport=bus)
    return hub_a, hub_b


FRAME = {"type": "measurement_changed", "event_id": "e1", "lead_id": "L1",
         "measurement_set_id": "S1", "revision_id": "R1", "updated_at": "2026-06-01T00:00:00+00:00"}


def test_cross_node_delivery():
    async def scenario():
        a, b = _two_nodes()
        await a.startup(); await b.startup()
        dev = FakeDevice()
        b.register_device("inst1", "k1", dev)              # device is on node B
        delivered = await a.broadcast("inst1", FRAME)      # broadcast originates on node A (no local dev)
        await asyncio.sleep(0.05)                          # let the in-process bus deliver
        assert delivered == 0                              # node A had no local device
        assert len(dev.frames) == 1                        # node B delivered exactly once (cross-node)
        assert dev.frames[0]["event_id"] == "e1"
        await a.shutdown(); await b.shutdown()
    asyncio.run(scenario())


def test_origin_echo_dedupe():
    async def scenario():
        a, b = _two_nodes()
        await a.startup(); await b.startup()
        dev_a = FakeDevice()
        a.register_device("inst1", "k1", dev_a)            # device on the ORIGIN node
        delivered = await a.broadcast("inst1", FRAME)      # local delivery + publish to shared channel
        await asyncio.sleep(0.05)                          # node A ALSO receives its own publication...
        assert delivered == 1
        assert len(dev_a.frames) == 1                      # ...but must NOT deliver twice (origin skip)
        await a.shutdown(); await b.shutdown()
    asyncio.run(scenario())


def test_both_nodes_have_devices():
    async def scenario():
        a, b = _two_nodes()
        await a.startup(); await b.startup()
        dev_a, dev_b = FakeDevice(), FakeDevice()
        a.register_device("inst1", "ka", dev_a)
        b.register_device("inst1", "kb", dev_b)
        await a.broadcast("inst1", FRAME)
        await asyncio.sleep(0.05)
        assert len(dev_a.frames) == 1                      # each device gets exactly one copy
        assert len(dev_b.frames) == 1
        await a.shutdown(); await b.shutdown()
    asyncio.run(scenario())


def test_single_node_memory_mode():
    async def scenario():
        hub = RelayHub("solo")                             # no transport, no registry (memory mode)
        await hub.startup()
        dev = FakeDevice()
        hub.register_device("i", "k", dev)
        delivered = await hub.broadcast("i", FRAME)
        assert delivered == 1 and len(dev.frames) == 1
        await hub.shutdown()
    asyncio.run(scenario())


def test_unregister_stops_delivery():
    async def scenario():
        hub = RelayHub("solo2")
        await hub.startup()
        dev = FakeDevice()
        hub.register_device("i", "k", dev)
        hub.unregister_device("i", "k")
        delivered = await hub.broadcast("i", FRAME)
        assert delivered == 0 and dev.frames == []
        assert hub.device_count("i") == 0
        await hub.shutdown()
    asyncio.run(scenario())


def test_no_devices_no_error():
    async def scenario():
        a, b = _two_nodes()
        await a.startup(); await b.startup()
        delivered = await a.broadcast("nobody", FRAME)     # no device anywhere — safe no-op
        await asyncio.sleep(0.02)
        assert delivered == 0
        await a.shutdown(); await b.shutdown()
    asyncio.run(scenario())
