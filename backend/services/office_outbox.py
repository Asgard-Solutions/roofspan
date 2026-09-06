"""Office -> Field measurement invalidation — DURABLE TRANSACTIONAL OUTBOX.

A row is written in the SAME DB transaction as the measurement/sketch mutation (transactional outbox
pattern), so an invalidation is never lost and never emitted for an uncommitted write. The loopback
Relay Connector LEASES undelivered rows (lease/ack/retry), forwards a lightweight `measurement_changed`
frame up the tunnel, and ACKs only after the Relay confirms acceptance. Delivery is AT-LEAST-ONCE and
the row id is the STABLE event id echoed end to end. The event carries NO business document — only the
routing ids + a watermark (Field then pulls the canonical copy).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import MeasurementSet, RelayOutboxEvent


def _now() -> datetime:
    return datetime.now(timezone.utc)


def frame_from_row(row: RelayOutboxEvent) -> dict:
    """The exact `measurement_changed` frame the connector forwards up the tunnel."""
    return {
        "type": "measurement_changed",
        "event_id": str(row.id),
        "event_type": row.event_type,
        "lead_id": str(row.lead_id) if row.lead_id else None,
        "measurement_set_id": str(row.measurement_set_id) if row.measurement_set_id else None,
        "revision_id": str(row.revision_id) if row.revision_id else None,
        "structure_id": row.structure_id,
        "sketch_document_version": row.sketch_document_version,
        "updated_at": row.updated_at_watermark,
    }


async def enqueue(db: AsyncSession, *, event_type: str, lead_id=None, measurement_set_id=None,
                  revision_id=None, updated_at=None, structure_id=None,
                  sketch_document_version=None) -> RelayOutboxEvent:
    """Add an outbox row to the CURRENT session (caller commits it with the write — transactional)."""
    if isinstance(updated_at, datetime):
        updated_at = updated_at.isoformat()
    row = RelayOutboxEvent(
        event_type=event_type[:48], lead_id=lead_id, measurement_set_id=measurement_set_id,
        revision_id=revision_id, structure_id=(str(structure_id) if structure_id else None),
        sketch_document_version=sketch_document_version, updated_at_watermark=updated_at,
    )
    db.add(row)
    return row


async def emit_for_revision(db: AsyncSession, rev, event_type: str, *, structure_id=None,
                            sketch_document_version=None) -> RelayOutboxEvent:
    """Resolve lead_id from the revision's set and enqueue a lightweight invalidation."""
    lead_id = None
    if rev.set_id:
        mset = await db.get(MeasurementSet, rev.set_id)
        if mset:
            lead_id = mset.lead_id
    return await enqueue(
        db, event_type=event_type, lead_id=lead_id, measurement_set_id=rev.set_id,
        revision_id=rev.id, updated_at=rev.updated_at, structure_id=structure_id,
        sketch_document_version=sketch_document_version,
    )


async def lease(db: AsyncSession, *, limit: int = 64, lease_seconds: int = 30) -> list[dict]:
    """Atomically claim up to `limit` undelivered, unleased (or lease-expired) events for delivery.

    Uses SELECT ... FOR UPDATE SKIP LOCKED so concurrent leasers never hand out the same row, then
    extends the lease + bumps attempts. Returns the frames to forward. Commits the lease."""
    now = _now()
    stmt = (
        select(RelayOutboxEvent)
        .where(RelayOutboxEvent.delivered_at.is_(None))
        .where((RelayOutboxEvent.leased_until.is_(None)) | (RelayOutboxEvent.leased_until < now))
        .order_by(RelayOutboxEvent.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    until = now + timedelta(seconds=max(1, lease_seconds))
    for r in rows:
        r.leased_until = until
        r.attempts = (r.attempts or 0) + 1
    await db.commit()
    return [frame_from_row(r) for r in rows]


async def ack(db: AsyncSession, event_ids) -> int:
    """Mark events delivered (idempotent — only rows not already delivered). Commits."""
    ids = []
    for x in event_ids or []:
        if not x:
            continue
        ids.append(x if isinstance(x, uuid.UUID) else uuid.UUID(str(x)))
    if not ids:
        return 0
    res = await db.execute(
        update(RelayOutboxEvent)
        .where(RelayOutboxEvent.id.in_(ids))
        .where(RelayOutboxEvent.delivered_at.is_(None))
        .values(delivered_at=_now())
    )
    await db.commit()
    return res.rowcount or 0


async def pending_count(db: AsyncSession) -> int:
    now = _now()
    stmt = (
        select(RelayOutboxEvent.id)
        .where(RelayOutboxEvent.delivered_at.is_(None))
        .where((RelayOutboxEvent.leased_until.is_(None)) | (RelayOutboxEvent.leased_until < now))
    )
    return len(list((await db.execute(stmt)).scalars().all()))
