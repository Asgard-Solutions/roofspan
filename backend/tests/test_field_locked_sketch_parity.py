"""Field vs Office roof-sketch document parity + contracts (Plan RoofSpan Field locked-viewer P0).

Verifies:
  1. Mobile GET /api/mobile/measurements/{rev}/sketches/{struct} returns the EXACT SAME sketch document
     as Office GET /api/measurements/{rev}/sketches/{struct} (same service; Field parity with Office).
  2. A structure with no saved sketch returns HTTP 404 with detail {code: 'sketch_not_found'} on BOTH
     the mobile and office endpoints (authoritative empty state).
  3. Mobile sketch GET enforces measurement scope — a sales user cannot read another rep's sketch (403);
     owner/office roles can read.

Runnable: PYTHONPATH=backend pytest -q backend/tests/test_field_locked_sketch_parity.py
Hermetic: creates its own property/user/lead/measurement rows; teardown deletes them.
"""
import sys, uuid
sys.path.insert(0, "backend")

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from db import SessionLocal
from models import MeasurementStructure
from schemas_measurements import MeasurementRevisionIn, StructureIn
from services import measurements as msvc
from services import measurement_sketches as ssvc
from routers.measurement_sketches import get_sketch as office_get_sketch
from routers.mobile import mobile_get_sketch

from _sketch_fixtures import FakeUser, seed_property, seed_user, seed_lead, teardown, run_isolated

# A real drawable roof sketch: 4 vertices, 4 edges, 1 facet (like RoofSpan Office would save).
DOC_FULL = {
    "schema_version": 1,
    "edit_mode": "connected_graph",
    "vertices": [
        {"id": "v1", "x": 0, "y": 0},
        {"id": "v2", "x": 10, "y": 0},
        {"id": "v3", "x": 10, "y": 8},
        {"id": "v4", "x": 0, "y": 8},
    ],
    "edges": [
        {"id": "e1", "v1": "v1", "v2": "v2"},
        {"id": "e2", "v1": "v2", "v2": "v3"},
        {"id": "e3", "v1": "v3", "v2": "v4"},
        {"id": "e4", "v1": "v4", "v2": "v1"},
    ],
    "facets": [{"id": "f1", "label": "F1", "pitch_rise": 6, "edges": ["e1", "e2", "e3", "e4"]}],
    "penetrations": [],
}


async def _revision_two_structures(db, user, prop, lead):
    rev = await msvc.create_revision(db, MeasurementRevisionIn(
        property_id=str(prop.id), lead_id=str(lead.id),
        structures=[
            StructureIn(ref="s1", name="Main House", structure_type="main_house"),
            StructureIn(ref="s2", name="Garage",     structure_type="detached_garage"),
        ]), user)
    await db.flush()
    structs = (await db.execute(
        select(MeasurementStructure).where(MeasurementStructure.revision_id == rev.id)
    )).scalars().all()
    # Save a sketch ONLY on the first structure (the second will be the "no sketch yet" case).
    s_with = structs[0]
    s_empty = structs[1]
    await ssvc.save_sketch(db, str(rev.id), str(s_with.id), edit_mode="connected_graph",
                           document=dict(DOC_FULL), schema_version=1, expected_version=None, user=user)
    return rev, str(s_with.id), str(s_empty.id)


async def _scenario():
    async with SessionLocal() as db:
        owner = FakeUser(id=None, role="owner")
        propA = await seed_property(db)
        propB = await seed_property(db)
        salesA = await seed_user(db, role="sales", label="Rep A")
        salesB = await seed_user(db, role="sales", label="Rep B")
        leadA = await seed_lead(db, property_id=propA.id, assigned_user_id=salesA.id)
        leadB = await seed_lead(db, property_id=propB.id, assigned_user_id=salesB.id)
        set_a = set_b = None
        try:
            revA, sA_with, sA_empty = await _revision_two_structures(db, salesA, propA, leadA)
            revB, sB_with, _sB_empty = await _revision_two_structures(db, salesB, propB, leadB)
            set_a, set_b = revA.set_id, revB.set_id
            ra, rb = str(revA.id), str(revB.id)

            # ---------- 1) PARITY: Field vs Office return identical `document` for the same sketch ----------
            office_out = await office_get_sketch(ra, sA_with, salesA, db)
            mobile_out = await mobile_get_sketch(ra, sA_with, salesA, db)
            assert office_out["structure_id"] == sA_with == mobile_out["structure_id"]
            assert office_out["document_version"] == mobile_out["document_version"] >= 1
            assert office_out["edit_mode"] == mobile_out["edit_mode"] == "connected_graph"
            assert office_out["schema_version"] == mobile_out["schema_version"] == 1
            # THE CORE PARITY: Field and Office return the SAME document (the fix's contract).
            assert office_out["document"] == mobile_out["document"], "Field/Office document parity broken"
            # And it's the full geometry (not a single line): facets/vertices present.
            doc = mobile_out["document"]
            assert len(doc["facets"]) >= 1, "Field must return facets — not a single-line stub"
            assert len(doc["vertices"]) >= 3
            assert len(doc["edges"]) >= 3

            # Owner sees the same identical document via mobile endpoint too.
            mobile_owner = await mobile_get_sketch(ra, sA_with, owner, db)
            assert mobile_owner["document"] == office_out["document"]

            # ---------- 2) sketch_not_found 404 on BOTH endpoints for a structure with no saved sketch ----------
            for label, coro in (("office", office_get_sketch(ra, sA_empty, salesA, db)),
                                ("mobile", mobile_get_sketch(ra, sA_empty, salesA, db))):
                with pytest.raises(HTTPException) as ei:
                    await coro
                assert ei.value.status_code == 404, f"{label} should 404 when no sketch"
                d = ei.value.detail
                assert isinstance(d, dict), f"{label} 404 detail must be structured"
                assert d.get("code") == "sketch_not_found", f"{label} must expose code=sketch_not_found (got {d})"

            # ---------- 3) SCOPE 403: sales user cannot read another rep's sketch via mobile endpoint ----------
            with pytest.raises(HTTPException) as ei:
                await mobile_get_sketch(rb, sB_with, salesA, db)  # A trying to read B's sketch
            assert ei.value.status_code == 403, f"cross-rep mobile GET must be 403, got {ei.value.status_code}"

            with pytest.raises(HTTPException) as ei:
                await mobile_get_sketch(ra, sA_with, salesB, db)  # B trying to read A's sketch
            assert ei.value.status_code == 403

            # Owner/office read across reps on the mobile endpoint.
            assert (await mobile_get_sketch(rb, sB_with, owner, db))["structure_id"] == sB_with
        finally:
            await teardown(db, set_ids=[x for x in (set_a, set_b) if x],
                           lead_ids=[leadA.id, leadB.id], property_ids=[propA.id, propB.id],
                           user_ids=[salesA.id, salesB.id],
                           audit_entity_ids=[sA_with, sA_empty, sB_with])


def test_field_office_sketch_parity_and_contracts():
    run_isolated(_scenario)


if __name__ == "__main__":
    run_isolated(_scenario)
    print("FIELD/OFFICE SKETCH PARITY + CONTRACTS PASSED")
