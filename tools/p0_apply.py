#!/usr/bin/env python3
"""Apply and verify the current RoofSpan P0 hardening increment.

Temporary implementation helper. The branch workflow runs this against a complete checkout, which lets
us make narrowly asserted replacements without rewriting unrelated large source files through the GitHub
contents API. It is removed before the pull request is merged.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one replacement, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def run(*cmd: str, cwd: str | None = None) -> None:
    subprocess.run(cmd, cwd=ROOT / cwd if cwd else ROOT, check=True)


def run_expected_failure(*cmd: str) -> None:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    print(proc.stdout, flush=True)
    print(proc.stderr, flush=True)
    if proc.returncode == 0:
        raise RuntimeError("Regression test unexpectedly passed before the P0-3 production change")


# ---------------------------------------------------------------------------
# RED: publication failure/timeout must be observable, and an installation
# connection must receive no broadcast_ack until the full topology accepts it.
# ---------------------------------------------------------------------------
write(
    "backend/tests/test_relay_broadcast.py",
    '''"""Office->Field broadcast fan-out and acceptance semantics (network-free)."""\nimport asyncio\nimport json\n\nfrom relay import protocol as P\nfrom relay.hub import InstallationConn, RelayHub\nfrom relay.registry import AsyncMemoryRegistry\nfrom relay.transport import InProcessBus\n\n\nclass FakeDevice:\n    def __init__(self):\n        self.frames = []\n\n    async def send_text(self, s):\n        self.frames.append(json.loads(s))\n\n\nclass FakeSocket:\n    def __init__(self):\n        self.frames = []\n\n    async def send_text(self, s):\n        self.frames.append(json.loads(s))\n\n\nclass FailingTransport:\n    async def publish(self, channel, message):\n        raise RuntimeError("valkey unavailable")\n\n\nclass HangingTransport:\n    async def publish(self, channel, message):\n        await asyncio.Event().wait()\n\n\ndef _two_nodes():\n    bus = InProcessBus()\n    store = {}\n    hub_a = RelayHub("nodeA", registry=AsyncMemoryRegistry("nodeA", store=store), transport=bus)\n    hub_b = RelayHub("nodeB", registry=AsyncMemoryRegistry("nodeB", store=store), transport=bus)\n    return hub_a, hub_b\n\n\nFRAME = {"type": "measurement_changed", "event_id": "e1", "lead_id": "L1",\n         "measurement_set_id": "S1", "revision_id": "R1", "updated_at": "2026-06-01T00:00:00+00:00"}\n\n\ndef test_cross_node_delivery_is_accepted_once_published():\n    async def scenario():\n        a, b = _two_nodes()\n        await a.startup(); await b.startup()\n        dev = FakeDevice()\n        b.register_device("inst1", "k1", dev)\n        result = await a.broadcast("inst1", FRAME)\n        await asyncio.sleep(0.05)\n        assert result.accepted is True\n        assert result.delivered_local == 0\n        assert len(dev.frames) == 1\n        assert dev.frames[0]["event_id"] == "e1"\n        await a.shutdown(); await b.shutdown()\n    asyncio.run(scenario())\n\n\ndef test_origin_echo_dedupe():\n    async def scenario():\n        a, b = _two_nodes()\n        await a.startup(); await b.startup()\n        dev_a = FakeDevice()\n        a.register_device("inst1", "k1", dev_a)\n        result = await a.broadcast("inst1", FRAME)\n        await asyncio.sleep(0.05)\n        assert result.accepted is True\n        assert result.delivered_local == 1\n        assert len(dev_a.frames) == 1\n        await a.shutdown(); await b.shutdown()\n    asyncio.run(scenario())\n\n\ndef test_both_nodes_have_devices():\n    async def scenario():\n        a, b = _two_nodes()\n        await a.startup(); await b.startup()\n        dev_a, dev_b = FakeDevice(), FakeDevice()\n        a.register_device("inst1", "ka", dev_a)\n        b.register_device("inst1", "kb", dev_b)\n        result = await a.broadcast("inst1", FRAME)\n        await asyncio.sleep(0.05)\n        assert result.accepted is True\n        assert result.delivered_local == 1\n        assert len(dev_a.frames) == 1\n        assert len(dev_b.frames) == 1\n        await a.shutdown(); await b.shutdown()\n    asyncio.run(scenario())\n\n\ndef test_single_node_memory_mode_accepts_after_local_processing():\n    async def scenario():\n        hub = RelayHub("solo")\n        dev = FakeDevice()\n        hub.register_device("i", "k", dev)\n        result = await hub.broadcast("i", FRAME)\n        assert result.accepted is True\n        assert result.delivered_local == 1\n        assert len(dev.frames) == 1\n    asyncio.run(scenario())\n\n\ndef test_unregister_stops_delivery_but_single_node_still_accepts():\n    async def scenario():\n        hub = RelayHub("solo2")\n        dev = FakeDevice()\n        hub.register_device("i", "k", dev)\n        hub.unregister_device("i", "k")\n        result = await hub.broadcast("i", FRAME)\n        assert result.accepted is True\n        assert result.delivered_local == 0\n        assert dev.frames == []\n        assert hub.device_count("i") == 0\n    asyncio.run(scenario())\n\n\ndef test_publish_failure_is_not_accepted_even_after_local_delivery():\n    async def scenario():\n        hub = RelayHub("fail", transport=FailingTransport())\n        dev = FakeDevice()\n        hub.register_device("i", "k", dev)\n        result = await hub.broadcast("i", FRAME)\n        assert result.accepted is False\n        assert result.reason == "publish_failed"\n        assert result.delivered_local == 1\n        assert len(dev.frames) == 1\n    asyncio.run(scenario())\n\n\ndef test_publish_timeout_is_not_accepted():\n    async def scenario():\n        hub = RelayHub("hang", transport=HangingTransport(), broadcast_publish_timeout=0.01)\n        result = await hub.broadcast("i", FRAME)\n        assert result.accepted is False\n        assert result.reason == "publish_timeout"\n        assert result.delivered_local == 0\n    asyncio.run(scenario())\n\n\ndef test_failed_cross_node_publish_sends_no_broadcast_ack():\n    async def scenario():\n        hub = RelayHub("fail-ack", transport=FailingTransport())\n        dev = FakeDevice()\n        hub.register_device("i", "k", dev)\n        ws = FakeSocket()\n        conn = InstallationConn("i", ws)\n        result = await hub.broadcast_and_ack("i", FRAME, conn)\n        assert result.accepted is False\n        assert result.delivered_local == 1\n        assert ws.frames == []\n    asyncio.run(scenario())\n\n\ndef test_accepted_broadcast_sends_one_ack_with_stable_event_id():\n    async def scenario():\n        hub = RelayHub("ok-ack")\n        ws = FakeSocket()\n        conn = InstallationConn("i", ws)\n        result = await hub.broadcast_and_ack("i", FRAME, conn)\n        assert result.accepted is True\n        assert len(ws.frames) == 1\n        assert ws.frames[0]["type"] == P.T_BROADCAST_ACK\n        assert ws.frames[0]["event_id"] == "e1"\n    asyncio.run(scenario())\n''',
)

run_expected_failure("pytest", "-q", "backend/tests/test_relay_broadcast.py")

# ---------------------------------------------------------------------------
# GREEN: model broadcast acceptance explicitly. Multi-node mode requires the
# shared broker to accept publication; otherwise no ack is written upstream.
# ---------------------------------------------------------------------------
replace_once(
    "backend/relay/config.py",
    'REQUEST_TIMEOUT = float(os.environ.get("RELAY_REQUEST_TIMEOUT", "30"))\n',
    'REQUEST_TIMEOUT = float(os.environ.get("RELAY_REQUEST_TIMEOUT", "30"))\n'
    'BROADCAST_PUBLISH_TIMEOUT = float(os.environ.get("RELAY_BROADCAST_PUBLISH_TIMEOUT", "5"))\n',
)
replace_once(
    "backend/relay/hub.py",
    "import asyncio\nimport logging\n",
    "import asyncio\nimport logging\nfrom dataclasses import dataclass\n",
)
replace_once(
    "backend/relay/hub.py",
    '''class RelayPayloadTooLarge(Exception):\n    """Cross-node envelope exceeds the relay payload ceiling; rejected before publish."""\n\n\nclass InstallationConn:''',
    '''class RelayPayloadTooLarge(Exception):\n    """Cross-node envelope exceeds the relay payload ceiling; rejected before publish."""\n\n\n@dataclass(frozen=True)\nclass BroadcastResult:\n    """Whether Relay accepted responsibility for an Office invalidation."""\n\n    delivered_local: int\n    accepted: bool\n    reason: str | None = None\n\n\nclass InstallationConn:''',
)
replace_once(
    "backend/relay/hub.py",
    '''class RelayHub:\n    def __init__(self, node_id: str, registry=None, transport=None):\n        self.node_id = node_id\n        self._registry = registry\n        self._transport = transport\n''',
    '''class RelayHub:\n    def __init__(self, node_id: str, registry=None, transport=None, broadcast_publish_timeout=None):\n        self.node_id = node_id\n        self._registry = registry\n        self._transport = transport\n        self._broadcast_publish_timeout = (\n            C.BROADCAST_PUBLISH_TIMEOUT\n            if broadcast_publish_timeout is None\n            else max(0.001, float(broadcast_publish_timeout))\n        )\n''',
)
old_broadcast = '''    async def broadcast(self, installation_id: str, frame: dict) -> int:\n        """Fan an Office->Field invalidation to all paired devices for this installation.\n\n        Delivers to LOCAL devices immediately, then (multi-node) publishes ONCE to the shared broadcast\n        channel so every OTHER node delivers to its own local devices. The originating node drops its own\n        echo in ``_on_broadcast`` (origin match) so a device on the origin node is never double-delivered.\n        Returns the count delivered locally."""\n        delivered = await self._deliver_local(installation_id, frame)\n        if self._transport is not None:\n            env = E.build_broadcast(self.node_id, installation_id, frame)\n            raw = P.dumps(env)\n            if len(raw.encode("utf-8")) <= C.MAX_ENVELOPE_BYTES:\n                try:\n                    await self._transport.publish(R.broadcast_channel(), raw)\n                except Exception as e:  # noqa: BLE001 - transport bounce: local devices already got it\n                    log.warning("relay broadcast publish failed: %s", str(e)[:160])\n        return delivered\n'''
new_broadcast = '''    async def broadcast(self, installation_id: str, frame: dict) -> BroadcastResult:\n        """Fan an Office->Field invalidation and report topology-wide acceptance.\n\n        Local device sends are best-effort. In multi-node mode the durable Office event may be retired only\n        after the shared broker accepts the publication; a broker failure/timeout leaves it unacknowledged so\n        the connector retries after the lease expires.\n        """\n        delivered = await self._deliver_local(installation_id, frame)\n        if self._transport is None:\n            return BroadcastResult(delivered_local=delivered, accepted=True)\n\n        env = E.build_broadcast(self.node_id, installation_id, frame)\n        raw = P.dumps(env)\n        if len(raw.encode("utf-8")) > C.MAX_ENVELOPE_BYTES:\n            log.warning("relay broadcast rejected: envelope exceeds configured ceiling")\n            return BroadcastResult(delivered_local=delivered, accepted=False, reason="payload_too_large")\n        try:\n            await asyncio.wait_for(\n                self._transport.publish(R.broadcast_channel(), raw),\n                timeout=self._broadcast_publish_timeout,\n            )\n        except asyncio.CancelledError:\n            raise\n        except TimeoutError:\n            log.warning("relay broadcast publish timed out")\n            return BroadcastResult(delivered_local=delivered, accepted=False, reason="publish_timeout")\n        except Exception as e:  # noqa: BLE001 - leave Office event unacked for lease-expiry retry\n            log.warning("relay broadcast publish failed: %s", str(e)[:160])\n            return BroadcastResult(delivered_local=delivered, accepted=False, reason="publish_failed")\n        return BroadcastResult(delivered_local=delivered, accepted=True)\n\n    async def broadcast_and_ack(\n        self, installation_id: str, frame: dict, conn: InstallationConn\n    ) -> BroadcastResult:\n        """Acknowledge upstream only after ``broadcast`` accepted the full configured topology."""\n        result = await self.broadcast(installation_id, frame)\n        if not result.accepted:\n            return result\n        ack = P.broadcast_ack(\n            event_id=frame.get("event_id"),\n            delivered=result.delivered_local,\n        )\n        async with conn.send_lock:\n            await conn.ws.send_text(P.dumps(ack))\n        return result\n'''
replace_once("backend/relay/hub.py", old_broadcast, new_broadcast)
replace_once(
    "backend/relay/server.py",
    '''                # Office->Field invalidation pushed UP the tunnel by the loopback connector. Fan it out\n                # to every paired device for this installation, then ACK so the connector can retire the\n                # durable outbox event (it retries until it sees this acceptance).\n                delivered = await hub.broadcast(installation_id, frame)\n                async with conn.send_lock:\n                    await _send(ws, P.broadcast_ack(event_id=frame.get("event_id"), delivered=delivered))\n''',
    '''                # Fan out and ACK only after the configured Relay topology accepts responsibility. A\n                # failed/timeout cross-node publication intentionally sends no ACK, so the Office lease\n                # expires and the stable event is retried.\n                await hub.broadcast_and_ack(installation_id, frame, conn)\n''',
)

run(
    "pytest", "-q",
    "backend/tests/test_relay_broadcast.py",
    "backend/tests/test_relay_multinode.py",
)
run(
    "python", "-m", "py_compile",
    "backend/relay/config.py", "backend/relay/hub.py", "backend/relay/server.py",
)

Path("/tmp/p0_commit_message").write_text(
    "fix: gate relay acknowledgements on broadcast acceptance\n",
    encoding="utf-8",
)
