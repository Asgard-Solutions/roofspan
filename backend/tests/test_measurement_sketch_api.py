"""Hermetic in-process HTTP contract for the roof sketch API (Plan 1 foundation closure).

Runnable in CI with NO live server, NO real password, NO arbitrary customer property, 0 skips:
    PYTHONPATH=backend pytest -q backend/tests/test_measurement_sketch_api.py
Uses httpx ASGITransport against the real FastAPI app, overriding only the authentication dependency
(`get_current_user`) to inject generated test principals. The DB dependency uses the real per-request
session against the test DATABASE_URL. All rows are created and cleaned up by the test itself.

Covers: create->200 v1, update->v2, stale->409(+server payload), malformed canonical doc->422,
locked revision PUT->409, and salesperson A/B direct-UUID authorization on the ACTUAL PUT route.
"""
import sys
sys.path.insert(0, "backend")

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from db import SessionLocal
from core import get_current_user
from models import MeasurementStructure
from schemas_measurements import MeasurementRevisionIn, StructureIn
from services import measurements as msvc
from _sketch_fixtures import seed_property, seed_user, seed_lead, teardown, run_isolated

DOC = {"schema_version": 1, "edit_mode": "connected_graph", "vertices": [{"id": "v1", "x": 0, "y": 0}], "edges": [], "facets": []}
_principal = {"user": None}


async def _seed_revision(db, sales_user, prop, lead):
    rev = await msvc.create_revision(db, MeasurementRevisionIn(
        property_id=str(prop.id), lead_id=str(lead.id),
        structures=[StructureIn(ref="s1", name="Main House", structure_type="main_house"),
                    StructureIn(ref="s2", name="Garage", structure_type="detached_garage")]), sales_user)
    await db.flush()
    structs = (await db.execute(select(MeasurementStructure).where(
        MeasurementStructure.revision_id == rev.id).order_by(MeasurementStructure.sort))).scalars().all()
    return rev, str(structs[0].id), str(structs[1].id)


async def _scenario():
    from server import app
    app.dependency_overrides[get_current_user] = lambda: _principal["user"]
    propA = propB = userA = userB = owner = leadA = leadB = None
    set_a = set_b = None
    aids = []
    try:
        async with SessionLocal() as db:
            propA = await seed_property(db); propB = await seed_property(db)
            userA = await seed_user(db, role="sales", label="Rep A")
            userB = await seed_user(db, role="sales", label="Rep B")
            owner = await seed_user(db, role="owner", label="Owner")
            leadA = await seed_lead(db, property_id=propA.id, assigned_user_id=userA.id)
            leadB = await seed_lead(db, property_id=propB.id, assigned_user_id=userB.id)
            revA, a1, a2 = await _seed_revision(db, userA, propA, leadA)
            revB, b1, b2 = await _seed_revision(db, userB, propB, leadB)
            set_a, set_b = revA.set_id, revB.set_id
            ra, rb = str(revA.id), str(revB.id)
            aids = [a1, a2, b1, b2]
            await db.commit()  # ASGI requests use their own sessions; must see the seed

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            def use(u): _principal["user"] = u
            async def put(rid, sid, doc, ev, mode="connected_graph", sv=1):
                return await client.put(f"/api/measurements/{rid}/sketches/{sid}",
                                        json={"schema_version": sv, "edit_mode": mode, "document": doc, "expected_version": ev})

            # --- Sales A on OWN revision: create -> update -> stale conflict -> malformed 422 ---
            use(userA)
            r = await put(ra, a1, DOC, None); assert r.status_code == 200 and r.json()["document_version"] == 1
            r = await put(ra, a1, DOC, 1); assert r.status_code == 200 and r.json()["document_version"] == 2
            r = await put(ra, a1, DOC, 1); assert r.status_code == 409 and r.json()["detail"]["server"]["document_version"] == 2
            bad = dict(DOC); bad["structure_id"] = "00000000-0000-0000-0000-000000000000"
            r = await put(ra, a1, bad, 2); assert r.status_code == 422

            # --- A/B direct-UUID authorization on the REAL PUT route ---
            r = await put(rb, b1, DOC, None); assert r.status_code == 403, "Sales A PUT B must be denied"
            assert (await client.get(f"/api/measurements/{ra}/sketches")).status_code == 200
            assert (await client.get(f"/api/measurements/{rb}/sketches")).status_code == 403
            assert (await client.get(f"/api/measurements/{ra}/sketches/{a1}")).status_code == 200
            assert (await client.get(f"/api/measurements/{rb}/sketches/{b1}")).status_code == 403

            use(userB)
            r = await put(rb, b1, DOC, None); assert r.status_code == 200 and r.json()["document_version"] == 1, "Sales B PUT B allowed"
            r = await put(ra, a1, DOC, 2); assert r.status_code == 403, "Sales B PUT A must be denied"
            assert (await client.get(f"/api/measurements/{rb}/sketches")).status_code == 200
            assert (await client.get(f"/api/measurements/{ra}/sketches")).status_code == 403

            # --- Owner (office role) broad access: PUT either revision + read across reps ---
            use(owner)
            r = await put(rb, b2, {"edit_mode": "manual_polygon"}, None, mode="manual_polygon"); assert r.status_code == 200
            assert (await client.get(f"/api/measurements/{ra}/sketches")).status_code == 200
            assert (await client.get(f"/api/measurements/{rb}/sketches")).status_code == 200

            # --- Locked revision PUT -> 409 ---
            for to in ["field_complete", "office_verified", "locked"]:
                assert (await client.post(f"/api/measurements/{ra}/status", json={"to": to})).status_code == 200
            r = await put(ra, a1, DOC, 2)
            assert r.status_code == 409 and "locked" in str(r.json()["detail"]).lower()
    finally:
        _principal["user"] = None
        app.dependency_overrides.pop(get_current_user, None)
        async with SessionLocal() as db:
            await teardown(
                db,
                set_ids=[x for x in (set_a, set_b) if x],
                lead_ids=[x.id for x in (leadA, leadB) if x is not None],
                property_ids=[x.id for x in (propA, propB) if x is not None],
                user_ids=[x.id for x in (userA, userB, owner) if x is not None],
                audit_entity_ids=aids,
            )


def test_sketch_api_hermetic_contract():
    run_isolated(_scenario)


if __name__ == "__main__":
    run_isolated(_scenario)
    print("SKETCH API HERMETIC CONTRACT PASSED")
