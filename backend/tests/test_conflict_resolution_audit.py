"""Field merge audit note — how a rep settled a sync conflict is visible to Office.

A resolution ({kept_mine, took_office}) on PATCH /api/mobile/properties/{id}:
  * appends a human-readable line to the property notes (visible on Office + Field), and
  * records a `property.conflict_resolved` audit-log entry (kept_mine / took_office).
An empty/absent resolution writes nothing extra.

Runnable: PYTHONPATH=backend pytest -q backend/tests/test_conflict_resolution_audit.py -n0
"""
import sys
import uuid as _uuid

sys.path.insert(0, "backend")

import pytest  # noqa: F401
from sqlalchemy import delete, select

from db import SessionLocal
from models import Property, Territory, CanvassSection, CanvassSectionProperty, User, AuditLog
from routers.mobile import patch_property as mobile_patch_property, MobilePropertyPatch, ConflictResolution
from _sketch_fixtures import FakeUser, seed_user, run_isolated


class _Req:
    client = type("c", (), {"host": "test"})()
    headers = {}


async def _run():
    db = SessionLocal()
    made = {"prop": None, "terr": None, "sec": None, "users": []}
    try:
        rep = await seed_user(db, role="sales", label="Audit Rep"); made["users"].append(rep.id)

        p = Property(id=_uuid.uuid4(), source="test", formatted_address="7 Audit Rd", do_not_knock=False, notes="pre-existing")
        db.add(p); made["prop"] = p.id; await db.flush()
        terr = Territory(id=_uuid.uuid4(), name="Audit Terr", geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]})
        db.add(terr); made["terr"] = terr.id; await db.flush()
        sec = CanvassSection(id=_uuid.uuid4(), territory_id=terr.id, name="S", geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}, assigned_user_id=rep.id, active=True)
        db.add(sec); made["sec"] = sec.id; await db.flush()
        db.add(CanvassSectionProperty(id=_uuid.uuid4(), section_id=sec.id, property_id=p.id))
        await db.commit()

        rep_u = FakeUser(rep.id, role="sales", email=rep.email)

        # Rep kept their DNK, took Office notes -> audit note appended + audit-log entry recorded.
        r = await mobile_patch_property(
            str(p.id),
            MobilePropertyPatch(do_not_knock=True, resolution=ConflictResolution(kept_mine=["do_not_knock"], took_office=["notes"])),
            _Req(), user=rep_u, db=db,
        )
        assert r.do_not_knock is True
        assert r.notes.startswith("pre-existing\n"), "existing notes preserved"
        assert "Sync conflict resolved" in r.notes and "kept Do Not Knock (yours)" in r.notes and "took Notes (Office)" in r.notes
        await db.refresh(p); assert "kept Do Not Knock (yours)" in (p.notes or "")

        rows = (await db.execute(select(AuditLog).where(AuditLog.entity_id == str(p.id), AuditLog.action == "property.conflict_resolved"))).scalars().all()
        assert len(rows) == 1, "exactly one conflict-resolution audit entry"
        assert rows[0].detail.get("kept_mine") == ["do_not_knock"]
        assert rows[0].detail.get("took_office") == ["notes"]
        assert rows[0].detail.get("via") == "mobile"
        print("PASS: resolution appends an audit note to property notes + records a conflict_resolved audit entry")

        # No resolution -> no extra note, no new audit entry.
        r2 = await mobile_patch_property(str(p.id), MobilePropertyPatch(notes="fresh notes"), _Req(), user=rep_u, db=db)
        assert r2.notes == "fresh notes", "plain notes update is not decorated with an audit line"
        rows2 = (await db.execute(select(AuditLog).where(AuditLog.entity_id == str(p.id), AuditLog.action == "property.conflict_resolved"))).scalars().all()
        assert len(rows2) == 1, "no new conflict-resolution audit entry when resolution absent"
        print("PASS: a patch without a resolution writes no audit note and no conflict_resolved entry")

        # Empty resolution (all-Office edge, should never be sent, but defensive) -> no note, no entry.
        r3 = await mobile_patch_property(str(p.id), MobilePropertyPatch(do_not_knock=False, resolution=ConflictResolution(kept_mine=[], took_office=[])), _Req(), user=rep_u, db=db)
        assert "Sync conflict resolved" not in (r3.notes or ""), "empty resolution adds no note"
        rows3 = (await db.execute(select(AuditLog).where(AuditLog.entity_id == str(p.id), AuditLog.action == "property.conflict_resolved"))).scalars().all()
        assert len(rows3) == 1, "empty resolution records no audit entry"
        print("PASS: an empty resolution records nothing")

    finally:
        await db.rollback()
        if made.get("prop"):
            await db.execute(delete(AuditLog).where(AuditLog.entity_id == str(made["prop"])))
            await db.execute(delete(Property).where(Property.id == made["prop"]))
        if made.get("sec"):
            await db.execute(delete(CanvassSection).where(CanvassSection.id == made["sec"]))
        if made.get("terr"):
            await db.execute(delete(Territory).where(Territory.id == made["terr"]))
        for uid in made.get("users", []):
            await db.execute(delete(User).where(User.id == uid))
        await db.commit(); await db.close()


def test_mobile_conflict_resolution_audit_note():
    run_isolated(_run)
