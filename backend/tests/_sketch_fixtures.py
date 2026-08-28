"""Hermetic fixtures for the roof-sketch foundation tests.

These helpers create their OWN rows (Property / User / Lead) so the suite never depends on an
arbitrary "first live Property" and never needs a real Owner password. Every created row is tracked
so teardown deletes exactly what the test made — and teardown NEVER silently swallows failures.
"""
import os
import sys
import uuid

# Make `backend/` importable and load its env so tests use the SAME DATABASE_URL as the app.
sys.path.insert(0, "backend")
from dotenv import load_dotenv
load_dotenv("backend/.env")

from sqlalchemy import delete, select
from models import Property, User, Lead, MeasurementSet


def run_isolated(coro_factory):
    """Run a fresh event loop and dispose the shared async engine before the loop closes.
    Prevents 'Event loop is closed' when multiple asyncio.run() calls (across test functions/files)
    reuse the module-level engine's connection pool."""
    import asyncio
    from db import engine

    async def _wrap():
        try:
            return await coro_factory()
        finally:
            await engine.dispose()
    asyncio.run(_wrap())


def active_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    assert url, "DATABASE_URL must be set for sketch tests (backend/.env)"
    return url


class FakeUser:
    """Lightweight principal for service/authz calls that only read .id/.role/.email."""
    def __init__(self, id, role="owner", email=None):
        self.id = id
        self.role = role
        self.email = email or f"{role}_{str(id)[:8]}@roofspan.test"


async def seed_property(db) -> Property:
    p = Property(id=uuid.uuid4(), formatted_address="RS-TEST hermetic property", source="test")
    db.add(p)
    await db.flush()
    return p


async def seed_user(db, role="sales", label=None) -> User:
    u = User(id=uuid.uuid4(), email=f"rs-sketch-{uuid.uuid4().hex[:12]}@roofspan.test",
             password_hash="not-a-real-hash", full_name=label or f"RS {role}", role=role, is_active=True)
    db.add(u)
    await db.flush()
    return u


async def seed_lead(db, *, property_id, assigned_user_id) -> Lead:
    lead = Lead(id=uuid.uuid4(), property_id=property_id, assigned_user_id=assigned_user_id,
                name="RS-TEST lead", status="new")
    db.add(lead)
    await db.flush()
    return lead


async def teardown(db, *, set_ids=(), lead_ids=(), property_ids=(), user_ids=(), audit_entity_ids=()):
    """Delete only what a test created. Loud on failure (no bare except)."""
    from models import AuditLog
    for eid in audit_entity_ids:
        await db.execute(delete(AuditLog).where(AuditLog.entity_id == str(eid)))
    for sid in set_ids:
        await db.execute(delete(MeasurementSet).where(MeasurementSet.id == sid))
    for lid in lead_ids:
        await db.execute(delete(Lead).where(Lead.id == lid))
    for pid in property_ids:
        await db.execute(delete(Property).where(Property.id == pid))
    for uid in user_ids:
        await db.execute(delete(User).where(User.id == uid))
    await db.commit()
    # verify the primary artifacts are actually gone (guards against a wrong-DB cleanup no-op)
    for sid in set_ids:
        assert (await db.execute(select(MeasurementSet.id).where(MeasurementSet.id == sid))).first() is None, \
            "MeasurementSet cleanup did not delete the row — cleanup may be pointed at a different database"
