"""Two-salesperson A/B authorization contract for roof sketches (Plan 1 foundation hardening).

Runnable: PYTHONPATH=backend pytest -q backend/tests/test_measurement_sketch_authz.py
Hermetic: creates two sales users, two properties, two leads and two measurement sets. No login /
real password needed — the authorization layer is exercised directly with principal objects.

Matrix (sales): A->A allowed, A->B denied, B->A denied, B->B allowed.
Office roles (owner/administrator/office) retain broad access. Covers list / GET / PUT direct-UUID.
"""
import sys
sys.path.insert(0, "backend")

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from db import SessionLocal
from models import MeasurementStructure
from schemas_measurements import MeasurementRevisionIn, StructureIn
from services import measurements as msvc
from services import measurement_sketches as ssvc
from routers.measurement_sketches import _scope, list_sketches, get_sketch, put_sketch
from schemas_sketch import SketchWriteIn
from starlette.requests import Request

from _sketch_fixtures import FakeUser, seed_property, seed_user, seed_lead, teardown, run_isolated

DOC = {"schema_version": 1, "edit_mode": "connected_graph", "vertices": [], "edges": [], "facets": []}


def _req():
    return Request({"type": "http", "method": "PUT", "path": "/", "headers": [], "client": ("test", 1234), "query_string": b""})


def _write(ev):
    return SketchWriteIn(document=dict(DOC), edit_mode="connected_graph", schema_version=1, expected_version=ev)


async def _revision_for(db, user, prop, lead):
    rev = await msvc.create_revision(db, MeasurementRevisionIn(
        property_id=str(prop.id), lead_id=str(lead.id),
        structures=[StructureIn(ref="s1", name="Main House", structure_type="main_house")]), user)
    await db.flush()
    struct = (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == rev.id))).scalars().first()
    await ssvc.save_sketch(db, str(rev.id), str(struct.id), edit_mode="connected_graph", document=dict(DOC), schema_version=1, expected_version=None, user=user)
    return rev, str(struct.id)


async def _denied(coro):
    with pytest.raises(HTTPException) as ei:
        await coro
    assert ei.value.status_code == 403, f"expected 403, got {ei.value.status_code}"


async def _scenario():
    async with SessionLocal() as db:
        owner = FakeUser(id=None, role="owner")
        admin = FakeUser(id=None, role="administrator")
        office = FakeUser(id=None, role="office")
        propA = await seed_property(db)
        propB = await seed_property(db)
        userA = await seed_user(db, role="sales", label="Rep A")
        userB = await seed_user(db, role="sales", label="Rep B")
        leadA = await seed_lead(db, property_id=propA.id, assigned_user_id=userA.id)
        leadB = await seed_lead(db, property_id=propB.id, assigned_user_id=userB.id)
        set_a = set_b = None
        try:
            revA, sA = await _revision_for(db, userA, propA, leadA)
            revB, sB = await _revision_for(db, userB, propB, leadB)
            set_a, set_b = revA.set_id, revB.set_id
            ra, rb = str(revA.id), str(revB.id)

            # --- _scope authorization matrix (the guard used by list/GET/PUT) ---
            assert (await _scope(db, ra, userA)).id == revA.id  # A -> A
            assert (await _scope(db, rb, userB)).id == revB.id  # B -> B
            await _denied(_scope(db, rb, userA))                # A -> B denied
            await _denied(_scope(db, ra, userB))                # B -> A denied
            for mgr in (owner, admin, office):
                assert (await _scope(db, ra, mgr)).id == revA.id  # office roles: broad access
                assert (await _scope(db, rb, mgr)).id == revB.id

            # --- LIST direct-UUID ---
            assert len(await list_sketches(ra, userA, db)) == 1
            await _denied(list_sketches(rb, userA, db))
            await _denied(list_sketches(ra, userB, db))
            assert len(await list_sketches(rb, userB, db)) == 1
            assert len(await list_sketches(rb, owner, db)) == 1  # office role sees other rep's

            # --- GET direct-UUID ---
            assert (await get_sketch(ra, sA, userA, db))["structure_id"] == sA
            await _denied(get_sketch(rb, sB, userA, db))
            await _denied(get_sketch(ra, sA, userB, db))
            assert (await get_sketch(rb, sB, userB, db))["structure_id"] == sB

            # --- PUT authorization on the ACTUAL put_sketch route (not just the helper) ---
            # A -> A allowed (existing v1 -> v2); A -> B denied
            assert (await put_sketch(ra, sA, _write(1), _req(), userA, db))["document_version"] == 2
            await _denied(put_sketch(rb, sB, _write(1), _req(), userA, db))
            # B -> A denied; B -> B allowed (existing v1 -> v2)
            await _denied(put_sketch(ra, sA, _write(2), _req(), userB, db))
            assert (await put_sketch(rb, sB, _write(1), _req(), userB, db))["document_version"] == 2
            # office roles may PUT either revision by direct UUID
            assert (await put_sketch(ra, sA, _write(2), _req(), owner, db))["document_version"] == 3
            assert (await put_sketch(rb, sB, _write(2), _req(), admin, db))["document_version"] == 3
            assert (await put_sketch(ra, sA, _write(3), _req(), office, db))["document_version"] == 4
        finally:
            await teardown(db, set_ids=[x for x in (set_a, set_b) if x],
                           lead_ids=[leadA.id, leadB.id], property_ids=[propA.id, propB.id],
                           user_ids=[userA.id, userB.id], audit_entity_ids=[sA, sB])


def test_ab_authorization_contract():
    run_isolated(_scenario)


if __name__ == "__main__":
    run_isolated(_scenario)
    print("SKETCH A/B AUTHORIZATION TESTS PASSED")
