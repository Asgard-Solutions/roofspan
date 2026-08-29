"""Optimistic-concurrency (409) for Field Property/DNK/Visit mutations, driving the conflict banner.

Runnable: PYTHONPATH=backend pytest -q backend/tests/test_property_concurrency.py -n0
"""
import sys
import uuid as _uuid

sys.path.insert(0, "backend")

import pytest  # noqa: F401
from fastapi import HTTPException
from sqlalchemy import delete

from db import SessionLocal
from models import Property, Territory, CanvassSection, CanvassSectionProperty, User
from routers.mobile import patch_property as mobile_patch, create_visit as mobile_visit, MobilePropertyPatch, MobileVisitIn
from _sketch_fixtures import FakeUser, seed_user, run_isolated


class _Req:
    client = type("c", (), {"host": "t"})()
    headers = {}


async def _run():
    db = SessionLocal()
    made = {"prop": None, "terr": None, "sec": None, "users": []}
    try:
        rep = await seed_user(db, role="sales", label="CC Rep"); made["users"].append(rep.id)
        p = Property(id=_uuid.uuid4(), source="test", formatted_address="1 Concurrency Ct", do_not_knock=False)
        db.add(p); made["prop"] = p.id; await db.flush()
        terr = Territory(id=_uuid.uuid4(), name="CC T", geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]})
        db.add(terr); made["terr"] = terr.id; await db.flush()
        sec = CanvassSection(id=_uuid.uuid4(), territory_id=terr.id, name="S", geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}, assigned_user_id=rep.id, active=True)
        db.add(sec); made["sec"] = sec.id; await db.flush()
        db.add(CanvassSectionProperty(id=_uuid.uuid4(), section_id=sec.id, property_id=p.id))
        await db.commit(); await db.refresh(p)
        rep_u = FakeUser(rep.id, role="sales", email=rep.email)

        token0 = p.updated_at

        # No token -> succeeds (backward compatible).
        await mobile_patch(str(p.id), MobilePropertyPatch(notes="a"), _Req(), user=rep_u, db=db)
        await db.refresh(p)
        assert p.updated_at != token0, "updated_at advanced after a patch (acts as the concurrency token)"
        print("PASS: no-token patch succeeds and advances updated_at")

        # Matching token -> succeeds.
        cur = p.updated_at
        r = await mobile_patch(str(p.id), MobilePropertyPatch(do_not_knock=True, expected_updated_at=cur), _Req(), user=rep_u, db=db)
        assert r.do_not_knock is True
        print("PASS: matching-token DNK patch succeeds")

        # STALE token (token0, since two patches have since advanced it) -> 409 with server snapshot.
        try:
            await mobile_patch(str(p.id), MobilePropertyPatch(do_not_knock=False, expected_updated_at=token0), _Req(), user=rep_u, db=db)
            assert False, "stale-token patch should 409"
        except HTTPException as e:
            assert e.status_code == 409
            assert isinstance(e.detail, dict) and e.detail.get("code") == "conflict"
            assert e.detail["server"]["id"] == str(p.id) and e.detail["server"]["do_not_knock"] is True, "409 carries the authoritative server snapshot"
        print("PASS: stale-token patch -> 409 with authoritative detail.server (drives the conflict banner)")

        # Visit with a stale token -> 409 too.
        try:
            await mobile_visit(MobileVisitIn(property_id=str(p.id), outcome="interested", expected_updated_at=token0), _Req(), idempotency_key=None, user=rep_u, db=db)
            assert False, "stale-token visit should 409"
        except HTTPException as e:
            assert e.status_code == 409 and e.detail.get("code") == "conflict"
        # Visit with a fresh token -> succeeds.
        await db.refresh(p)
        v = await mobile_visit(MobileVisitIn(property_id=str(p.id), outcome="interested", expected_updated_at=p.updated_at), _Req(), idempotency_key=None, user=rep_u, db=db)
        assert v["outcome"] == "interested"
        print("PASS: visit honors the concurrency token (stale -> 409, fresh -> created)")

    finally:
        await db.rollback()
        if made.get("prop"):
            await db.execute(delete(Property).where(Property.id == made["prop"]))
        if made.get("sec"):
            await db.execute(delete(CanvassSection).where(CanvassSection.id == made["sec"]))
        if made.get("terr"):
            await db.execute(delete(Territory).where(Territory.id == made["terr"]))
        for uid in made.get("users", []):
            await db.execute(delete(User).where(User.id == uid))
        await db.commit(); await db.close()


def test_property_optimistic_concurrency():
    run_isolated(_run)
