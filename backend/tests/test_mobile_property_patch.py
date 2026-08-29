"""Field (mobile) Property mutation — Do Not Knock on/off + notes, with property-level authorization.

Runnable: PYTHONPATH=backend pytest -q backend/tests/test_mobile_property_patch.py -n0
"""
import sys
import uuid as _uuid

sys.path.insert(0, "backend")

import pytest  # noqa: F401
from fastapi import HTTPException
from sqlalchemy import delete

from db import SessionLocal
from models import Property, Territory, CanvassSection, CanvassSectionProperty, User
from routers.mobile import patch_property as mobile_patch_property, MobilePropertyPatch
from _sketch_fixtures import FakeUser, seed_user, run_isolated


class _Req:
    client = type("c", (), {"host": "test"})()
    headers = {}


async def _run():
    db = SessionLocal()
    made = {"prop": None, "terr": None, "sec": None, "users": []}
    try:
        rep = await seed_user(db, role="sales", label="DNK Rep"); made["users"].append(rep.id)
        rep_other = await seed_user(db, role="sales", label="DNK Rep B"); made["users"].append(rep_other.id)

        p = Property(id=_uuid.uuid4(), source="test", formatted_address="1 DNK Way", do_not_knock=False)
        db.add(p); made["prop"] = p.id; await db.flush()
        terr = Territory(id=_uuid.uuid4(), name="DNK Terr", geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]})
        db.add(terr); made["terr"] = terr.id; await db.flush()
        sec = CanvassSection(id=_uuid.uuid4(), territory_id=terr.id, name="S", geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}, assigned_user_id=rep.id, active=True)
        db.add(sec); made["sec"] = sec.id; await db.flush()
        db.add(CanvassSectionProperty(id=_uuid.uuid4(), section_id=sec.id, property_id=p.id))
        await db.commit()

        rep_u = FakeUser(rep.id, role="sales", email=rep.email)
        other_u = FakeUser(rep_other.id, role="sales", email=rep_other.email)

        # DNK OFF -> ON
        r = await mobile_patch_property(str(p.id), MobilePropertyPatch(do_not_knock=True, do_not_knock_reason="Field ON"), _Req(), user=rep_u, db=db)
        assert r.do_not_knock is True and r.do_not_knock_reason == "Field ON"
        await db.refresh(p); assert p.do_not_knock is True
        print("PASS: authorized rep turns DNK OFF -> ON (persisted)")

        # DNK ON -> OFF
        r = await mobile_patch_property(str(p.id), MobilePropertyPatch(do_not_knock=False), _Req(), user=rep_u, db=db)
        assert r.do_not_knock is False
        await db.refresh(p); assert p.do_not_knock is False
        print("PASS: authorized rep turns DNK ON -> OFF (persisted)")

        # notes update
        r = await mobile_patch_property(str(p.id), MobilePropertyPatch(notes="left flyer"), _Req(), user=rep_u, db=db)
        assert r.notes == "left flyer"
        print("PASS: authorized rep updates notes")

        # unauthorized rep -> 403
        try:
            await mobile_patch_property(str(p.id), MobilePropertyPatch(do_not_knock=True), _Req(), user=other_u, db=db)
            assert False, "unauthorized rep mutated the property"
        except HTTPException as e:
            assert e.status_code == 403
        print("PASS: unauthorized rep DNK mutation rejected (403)")

    finally:
        await db.rollback()
        for pid in (made.get("prop"),):
            if pid:
                await db.execute(delete(Property).where(Property.id == pid))
        if made.get("sec"):
            await db.execute(delete(CanvassSection).where(CanvassSection.id == made["sec"]))
        if made.get("terr"):
            await db.execute(delete(Territory).where(Territory.id == made["terr"]))
        for uid in made.get("users", []):
            await db.execute(delete(User).where(User.id == uid))
        await db.commit(); await db.close()


def test_mobile_property_dnk_and_authz():
    run_isolated(_run)
