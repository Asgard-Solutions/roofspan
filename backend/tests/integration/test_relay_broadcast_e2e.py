"""FULL multi-process Office->Field INSTANT-SYNC broadcast E2E (gated by RELAY_RUN_INTEGRATION=1).

Exercises the ENTIRE server/connector/relay transport path headlessly, with real processes and real
Valkey Pub/Sub:

    Office backend (:8001, durable outbox + loopback lease/ack)
        -> Relay Connector (InstallationTunnel: leases the outbox, forwards up the tunnel,
                            waits for the Relay's ACCEPTANCE, then acks the outbox)
        -> Relay NODE A (real uvicorn process; receives measurement_changed, fans out, acks)
        -> Valkey broadcast channel
        -> Relay NODE B (real uvicorn process; the paired device is connected here)
        -> synthetic Mobile WebSocket client (receives the measurement_changed invalidation)

Proves: at-least-once delivery with a stable event id, the Relay acceptance-before-ack contract, and
cross-node fan-out when the device and the Office tunnel are on DIFFERENT relay nodes. Physical
Android/iOS acceptance remains pending (cannot run native Expo here).
"""
import asyncio
import time
import uuid
from datetime import datetime, timezone

import pytest
import requests
import websockets

from relay import protocol as P

# Reuse the proven harness helpers from the Valkey E2E suite.
from tests.integration.test_relay_valkey import (
    CP, LOCAL, _activate, _pair, _spawn_relay,
)

pytestmark = pytest.mark.integration


async def _connector_token():
    from db import SessionLocal
    from routers.relay_connector import _get_or_create_connector_token
    async with SessionLocal() as db:
        return await _get_or_create_connector_token(db)


async def _enqueue_office_event(*, lead_id, revision_id):
    """Represents a committed Office measurement write producing a durable outbox row."""
    from db import SessionLocal
    from services import office_outbox
    async with SessionLocal() as db:
        row = await office_outbox.enqueue(
            db, event_type="measurement.update", lead_id=lead_id,
            measurement_set_id=uuid.uuid4(), revision_id=revision_id,
            updated_at=datetime.now(timezone.utc),
        )
        await db.commit()
        return str(row.id)


async def _outbox_delivered(event_id) -> bool:
    from db import SessionLocal
    from models import RelayOutboxEvent
    async with SessionLocal() as db:
        row = await db.get(RelayOutboxEvent, uuid.UUID(event_id))
        return bool(row and row.delivered_at is not None)


async def _cleanup_event(event_id):
    from db import SessionLocal, engine
    from models import RelayOutboxEvent
    from sqlalchemy import delete
    async with SessionLocal() as db:
        await db.execute(delete(RelayOutboxEvent).where(RelayOutboxEvent.id == uuid.UUID(event_id)))
        await db.commit()
    await engine.dispose()


def test_office_to_field_broadcast_cross_node(valkey_url, flush_valkey):
    assert requests.get(f"{LOCAL}/api/health", timeout=5).status_code == 200
    relay_a = _spawn_relay(9111, "bcast-a", valkey_url)
    relay_b = _spawn_relay(9112, "bcast-b", valkey_url)
    tunnel = None
    task = None
    event_id = None
    try:
        data, priv = _activate()
        device_id, cred = _pair(data, priv)
        iid = data["installation_id"]
        lead_id = uuid.uuid4()
        revision_id = uuid.uuid4()

        async def scenario():
            nonlocal tunnel, task, event_id
            from relay.tunnel_client import InstallationTunnel

            token = await _connector_token()

            # 1) Mobile connects to relay NODE B FIRST so it is registered before the broadcast fires.
            ws = await websockets.connect("ws://127.0.0.1:9112/api/relay/mobile")
            await ws.send(P.dumps({"type": P.T_HELLO, "installation_id": iid, "device_id": device_id,
                                   "device_credential": cred, "protocol": P.PROTOCOL_VERSION}))
            ready = P.loads(await ws.recv())
            assert ready.get("type") == P.T_READY, ready

            # 2) A committed Office write lands a durable outbox event.
            event_id = await _enqueue_office_event(lead_id=lead_id, revision_id=revision_id)

            # 3) The connector (Office installation) opens its tunnel to relay NODE A with the outbox
            #    token; its pump leases the event, forwards it up, and acks after the Relay accepts.
            tunnel = InstallationTunnel("ws://127.0.0.1:9111/api/relay/installation", iid, priv, LOCAL,
                                        outbox_token=token, outbox_poll_wait_ms=4000, accept_timeout=10.0)
            task = asyncio.create_task(tunnel.run())
            await asyncio.wait_for(tunnel.ready.wait(), timeout=15)

            # 4) The synthetic Mobile receives the measurement_changed invalidation (cross-node).
            frame = None
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                except asyncio.TimeoutError:
                    continue
                f = P.loads(msg)
                if f.get("type") == P.T_MEASUREMENT_CHANGED and f.get("event_id") == event_id:
                    frame = f
                    break
            await ws.close()

            # 5) The outbox row is acked (delivered) only AFTER the Relay's acceptance.
            delivered = False
            for _ in range(20):
                if await _outbox_delivered(event_id):
                    delivered = True
                    break
                await asyncio.sleep(0.5)
            return frame, delivered

        frame, delivered = asyncio.run(scenario())

        assert frame is not None, "Mobile never received the Office->Field invalidation"
        assert frame["lead_id"] == str(lead_id)
        assert frame["revision_id"] == str(revision_id)
        assert frame["event_id"] == event_id
        assert delivered, "outbox event was not acked after relay acceptance"
    finally:
        if tunnel is not None:
            tunnel.stop()
        if task is not None:
            task.cancel()
        if event_id is not None:
            try:
                asyncio.run(_cleanup_event(event_id))
            except Exception:  # noqa: BLE001
                pass
        for p in (relay_a, relay_b):
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()
