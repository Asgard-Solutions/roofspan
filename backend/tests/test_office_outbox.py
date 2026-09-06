"""Durable transactional outbox (relay_outbox_events) — DB-backed lease/ack/retry semantics.

Verifies the Office side of Office->Field instant sync: enqueue is transactional, lease atomically
claims + leases undelivered rows with a stable event id, ack marks delivered (idempotent), delivered
rows are never re-leased, and a lease that EXPIRES makes the event available again (at-least-once).
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update

from db import SessionLocal, engine
from models import RelayOutboxEvent
from services import office_outbox


def _uid():
    return uuid.uuid4()


def test_enqueue_lease_ack_flow():
    async def scenario():
        lead = _uid()
        async with SessionLocal() as db:
            row = await office_outbox.enqueue(
                db, event_type="measurement.create", lead_id=lead, measurement_set_id=_uid(),
                revision_id=_uid(), updated_at=datetime.now(timezone.utc),
            )
            await db.commit()
            event_id = str(row.id)

        # Lease returns the frame with the STABLE event id + all routing fields.
        async with SessionLocal() as db:
            events = await office_outbox.lease(db, limit=50, lease_seconds=60)
        mine = [e for e in events if e["event_id"] == event_id]
        assert len(mine) == 1
        f = mine[0]
        assert f["type"] == "measurement_changed"
        assert f["event_type"] == "measurement.create"
        assert f["lead_id"] == str(lead)
        assert f["revision_id"] is not None

        # Row is now leased (unavailable) — an immediate second lease does NOT return it again.
        async with SessionLocal() as db:
            again = await office_outbox.lease(db, limit=50, lease_seconds=60)
        assert event_id not in [e["event_id"] for e in again]

        # Ack marks it delivered; a second ack is a no-op (idempotent).
        async with SessionLocal() as db:
            n1 = await office_outbox.ack(db, [event_id])
            n2 = await office_outbox.ack(db, [event_id])
        assert n1 == 1 and n2 == 0

        # Delivered rows are never leased again even after lease expiry.
        async with SessionLocal() as db:
            await db.execute(update(RelayOutboxEvent)
                             .where(RelayOutboxEvent.id == uuid.UUID(event_id))
                             .values(leased_until=datetime.now(timezone.utc) - timedelta(minutes=5)))
            await db.commit()
        async with SessionLocal() as db:
            final = await office_outbox.lease(db, limit=50, lease_seconds=60)
        assert event_id not in [e["event_id"] for e in final]

        async with SessionLocal() as db:
            await db.execute(delete(RelayOutboxEvent).where(RelayOutboxEvent.id == uuid.UUID(event_id)))
            await db.commit()
        await engine.dispose()
    asyncio.run(scenario())


def test_lease_expiry_redelivers():
    async def scenario():
        async with SessionLocal() as db:
            row = await office_outbox.enqueue(db, event_type="measurement.update", lead_id=_uid())
            await db.commit()
            event_id = str(row.id)

        async with SessionLocal() as db:
            first = await office_outbox.lease(db, limit=50, lease_seconds=60)
        assert event_id in [e["event_id"] for e in first]

        # Simulate a connector that leased but never acked (no relay acceptance): expire the lease.
        async with SessionLocal() as db:
            await db.execute(update(RelayOutboxEvent)
                             .where(RelayOutboxEvent.id == uuid.UUID(event_id))
                             .values(leased_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
            await db.commit()

        async with SessionLocal() as db:
            redelivered = await office_outbox.lease(db, limit=50, lease_seconds=60)
            # attempts must have incremented across the two leases (>= 2).
            reloaded = await db.get(RelayOutboxEvent, uuid.UUID(event_id))
            attempts = reloaded.attempts
        assert event_id in [e["event_id"] for e in redelivered]
        assert attempts >= 2

        async with SessionLocal() as db:
            await db.execute(delete(RelayOutboxEvent).where(RelayOutboxEvent.id == uuid.UUID(event_id)))
            await db.commit()
        await engine.dispose()
    asyncio.run(scenario())
