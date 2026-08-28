import asyncio
from dotenv import load_dotenv; load_dotenv("backend/.env")
import sys; sys.path.insert(0, "backend")

from sqlalchemy import delete, select
from db import SessionLocal
from models import MeasurementSet, MeasurementRevision, MeasurementStructure, Property
from schemas_measurements import MeasurementRevisionIn, StructureIn
from services import measurements as msvc
from services import measurement_sketches as ssvc


class U:  # stand-in user
    email = "sketchtester@roofspan.com"
    role = "owner"


async def main():
    async with SessionLocal() as db:
        pid = (await db.execute(select(Property.id).limit(1))).scalars().first()
        user = U()
        payload = MeasurementRevisionIn(property_id=str(pid), structures=[
            StructureIn(ref="s1", name="Main House", structure_type="main_house"),
            StructureIn(ref="s2", name="Garage", structure_type="detached_garage"),
        ], facets=[], edges=[], penetrations=[])
        rev = await msvc.create_revision(db, payload, user)
        await db.flush()
        structs = (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == rev.id).order_by(MeasurementStructure.sort))).scalars().all()
        s1 = str(structs[0].id)
        doc = {"schema_version": 1, "edit_mode": "connected_graph", "vertices": [{"id": "v1", "x": 0, "y": 0}], "edges": [], "facets": []}

        # create -> version 1
        r1 = await ssvc.save_sketch(db, str(rev.id), s1, edit_mode="connected_graph", document=doc, schema_version=1, expected_version=None, user=user)
        assert r1["document_version"] == 1, r1["document_version"]
        print("create -> version 1 OK")

        # update with correct expected_version -> version 2
        r2 = await ssvc.save_sketch(db, str(rev.id), s1, edit_mode="connected_graph", document=doc, schema_version=1, expected_version=1, user=user)
        assert r2["document_version"] == 2
        print("update -> version 2 OK")

        # stale expected_version=1 now conflicts
        try:
            await ssvc.save_sketch(db, str(rev.id), s1, edit_mode="connected_graph", document=doc, schema_version=1, expected_version=1, user=user)
            assert False, "expected SketchConflict"
        except ssvc.SketchConflict as e:
            assert e.server["document_version"] == 2
            print("stale version -> SketchConflict OK")

        # different structure saves independently at version 1
        s2 = str(structs[1].id)
        r3 = await ssvc.save_sketch(db, str(rev.id), s2, edit_mode="manual_polygon", document=doc, schema_version=1, expected_version=None, user=user)
        assert r3["document_version"] == 1 and r3["edit_mode"] == "manual_polygon"
        print("second structure independent save OK")

        # clone revision -> sketches copied and remapped to NEW structure ids, version reset to 1
        new = await msvc.clone_revision(db, rev, user)
        await db.flush()
        new_sketches = await ssvc.list_sketches(db, str(new.id))
        assert len(new_sketches) == 2, ("cloned sketch count", len(new_sketches))
        new_struct_ids = set(str(x.id) for x in (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == new.id))).scalars().all())
        assert all(sk["structure_id"] in new_struct_ids for sk in new_sketches), "sketch not remapped to new structure ids"
        assert all(sk["document_version"] == 1 for sk in new_sketches), "cloned sketch version should reset to 1"
        assert all(sk["structure_id"] not in (s1, s2) for sk in new_sketches), "cloned sketch still points at old structure ids"
        print("clone copies + remaps sketches (version reset to 1) OK")

        # locked revision cannot be modified
        for to in ["field_complete", "office_verified", "locked"]:
            await msvc.transition_status(db, new, to, user)
        new_s = (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == new.id))).scalars().first()
        try:
            await ssvc.save_sketch(db, str(new.id), str(new_s.id), edit_mode="connected_graph", document=doc, schema_version=1, expected_version=1, user=user)
            assert False, "expected 409 on locked revision"
        except Exception as e:
            assert getattr(e, "status_code", None) == 409, type(e)
            print("locked revision rejects sketch edit (409) OK")

        # cleanup
        setids = (await db.execute(select(MeasurementSet.id).where(MeasurementSet.property_id == pid))).scalars().all()
        for sid in setids:
            await db.execute(delete(MeasurementSet).where(MeasurementSet.id == sid))
        await db.commit()
        print("\nSKETCH SERVICE TESTS PASSED")


asyncio.run(main())
