"""Pytest contract tests for the roof sketch service (Plan 1 foundation corrections).

Runnable: PYTHONPATH=backend pytest -q backend/tests/test_measurement_sketch_service.py
Safe: only deletes the MeasurementSet it creates; never destroys arbitrary customer rows.
"""
import asyncio
from dotenv import load_dotenv
load_dotenv("backend/.env")
import sys
sys.path.insert(0, "backend")

import pytest
from sqlalchemy import delete, select
from db import SessionLocal
from models import MeasurementSet, MeasurementStructure, Property
from schemas_measurements import MeasurementRevisionIn, StructureIn
from services import measurements as msvc
from services import measurement_sketches as ssvc
from fastapi import HTTPException


class _U:
    email = "sketch_pytest@roofspan.test"
    role = "owner"


DOC_CG = {"schema_version": 1, "edit_mode": "connected_graph", "vertices": [{"id": "v1", "x": 0, "y": 0}], "edges": [], "facets": []}


async def _scenario():
    async with SessionLocal() as db:
        pid = (await db.execute(select(Property.id).limit(1))).scalars().first()
        assert pid is not None, "need at least one property in test DB"
        user = _U()
        rev = await msvc.create_revision(db, MeasurementRevisionIn(property_id=str(pid), structures=[
            StructureIn(ref="s1", name="Main House", structure_type="main_house"),
            StructureIn(ref="s2", name="Garage", structure_type="detached_garage"),
        ]), user)
        await db.flush()
        created_set_id = rev.set_id
        structs = (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == rev.id).order_by(MeasurementStructure.sort))).scalars().all()
        s1, s2 = str(structs[0].id), str(structs[1].id)
        try:
            r1 = await ssvc.save_sketch(db, str(rev.id), s1, edit_mode="connected_graph", document=dict(DOC_CG), schema_version=1, expected_version=None, user=user)
            assert r1["document_version"] == 1
            assert r1["document"]["structure_id"] == s1

            r2 = await ssvc.save_sketch(db, str(rev.id), s1, edit_mode="connected_graph", document=dict(DOC_CG), schema_version=1, expected_version=1, user=user)
            assert r2["document_version"] == 2

            # ATOMIC CAS: two writers from the SAME version -> one wins, other conflicts.
            w1 = await ssvc.save_sketch(db, str(rev.id), s1, edit_mode="connected_graph", document=dict(DOC_CG), schema_version=1, expected_version=2, user=user)
            assert w1["document_version"] == 3
            conflicted = False
            try:
                await ssvc.save_sketch(db, str(rev.id), s1, edit_mode="connected_graph", document=dict(DOC_CG), schema_version=1, expected_version=2, user=user)
            except ssvc.SketchConflict as e:
                conflicted = True
                assert e.server["document_version"] == 3
            assert conflicted, "second same-version writer must conflict (no last-write-wins)"

            # NORMALIZATION rejects contradictions (edit_mode / structure_id / schema_version / bad mode)
            for bad in [dict(edit_mode="manual_polygon"), dict(structure_id="00000000-0000-0000-0000-000000000000"), dict(schema_version=99)]:
                d = dict(DOC_CG); d.update(bad)
                with pytest.raises(HTTPException) as ei:
                    await ssvc.save_sketch(db, str(rev.id), s1, edit_mode="connected_graph", document=d, schema_version=1, expected_version=3, user=user)
                assert ei.value.status_code == 422
            with pytest.raises(HTTPException) as ei:
                await ssvc.save_sketch(db, str(rev.id), s1, edit_mode="triangle", document={}, schema_version=1, expected_version=3, user=user)
            assert ei.value.status_code == 422

            r3 = await ssvc.save_sketch(db, str(rev.id), s2, edit_mode="manual_polygon", document={"edit_mode": "manual_polygon"}, schema_version=1, expected_version=None, user=user)
            assert r3["document_version"] == 1 and r3["edit_mode"] == "manual_polygon"

            # CLONE remaps structure ids inside the document; no old structure id remains.
            new = await msvc.clone_revision(db, rev, user)
            await db.flush()
            new_sketches = await ssvc.list_sketches(db, str(new.id))
            assert len(new_sketches) == 2
            new_struct_ids = set(str(x.id) for x in (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == new.id))).scalars().all())
            for sk in new_sketches:
                assert sk["structure_id"] in new_struct_ids
                assert sk["document"]["structure_id"] in new_struct_ids
                assert sk["document"]["structure_id"] not in (s1, s2)
                assert sk["document_version"] == 1

            for to in ["field_complete", "office_verified", "locked"]:
                await msvc.transition_status(db, new, to, user)
            new_s = (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == new.id))).scalars().first()
            with pytest.raises(HTTPException) as ei:
                await ssvc.save_sketch(db, str(new.id), str(new_s.id), edit_mode="connected_graph", document=dict(DOC_CG), schema_version=1, expected_version=1, user=user)
            assert ei.value.status_code == 409
        finally:
            assert created_set_id is not None
            await db.execute(delete(MeasurementSet).where(MeasurementSet.id == created_set_id))
            await db.commit()


def test_sketch_service_contract():
    asyncio.run(_scenario())


if __name__ == "__main__":
    asyncio.run(_scenario())
    print("SKETCH SERVICE TESTS PASSED")
