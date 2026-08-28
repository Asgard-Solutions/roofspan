"""Identity-preserving measurement persistence + roof-sketch survival (Task 4 Closure Phase 1).

Runnable: PYTHONPATH=backend pytest -q backend/tests/test_measurement_sketch_survival.py

Proves the editable-revision save path (`replace_children`) reconciles children BY IDENTITY instead
of delete+reinsert:
  1. A normal Worksheet save (every child sent back with its server-UUID `ref`) preserves every child
     UUID, so the associated MeasurementSketchDocument survives untouched and photos stay attached to
     the SAME entity UUID.
  2. Omitting a child from the full PUT deletes it intentionally — its sketch is CASCADE-removed and
     its photos are retained on the measurement revision (never silently orphaned).
  3. Mixed add/update/delete in one save behaves deterministically (survivors keep ids, new rows get
     fresh ids, omitted rows are removed) and sketches on surviving structures persist.
  4. A `ref`/id that is a real UUID but belongs to a DIFFERENT revision, or no longer exists, is
     rejected with 409 (never silently reused or inserted as new).
"""
import sys
import uuid as _uuid

sys.path.insert(0, "backend")

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from db import SessionLocal
from models import (
    MeasurementStructure, MeasurementFacet, MeasurementEdge, MeasurementPenetration, Photo,
)
from schemas_measurements import (
    MeasurementRevisionIn, StructureIn, FacetIn, EdgeIn, PenetrationIn,
)
from services import measurements as msvc
from services import measurement_sketches as ssvc

from _sketch_fixtures import FakeUser, seed_property, teardown, run_isolated

PHOTO_TAG = "rs-survival-test"
DOC = {"schema_version": 1, "edit_mode": "connected_graph",
       "vertices": [{"id": "v1", "x": 0, "y": 0}], "edges": [], "facets": []}


async def _structs(db, rid):
    return (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == rid).order_by(MeasurementStructure.sort))).scalars().all()


async def _facets(db, rid):
    return (await db.execute(select(MeasurementFacet).where(MeasurementFacet.revision_id == rid).order_by(MeasurementFacet.sort))).scalars().all()


async def _edges(db, rid):
    return (await db.execute(select(MeasurementEdge).where(MeasurementEdge.revision_id == rid).order_by(MeasurementEdge.sort))).scalars().all()


async def _pens(db, rid):
    return (await db.execute(select(MeasurementPenetration).where(MeasurementPenetration.revision_id == rid).order_by(MeasurementPenetration.sort))).scalars().all()


async def _sketch_struct_ids(db, rid):
    rows = await ssvc.list_sketches(db, str(rid))
    return {sk["structure_id"] for sk in rows}


async def _photo_count(db, rtype, rid):
    return len((await db.execute(select(Photo).where(Photo.record_type == rtype, Photo.record_id == str(rid)))).scalars().all())


def _add_photo(db, rtype, rid):
    db.add(Photo(object_path=f"{PHOTO_TAG}/{_uuid.uuid4().hex}.jpg", content_type="image/jpeg",
                 record_type=rtype, record_id=str(rid), uploaded_by=PHOTO_TAG))


async def _scenario():
    async with SessionLocal() as db:
        prop = await seed_property(db)
        prop2 = await seed_property(db)
        user = FakeUser(id=None, role="owner", email="survival@roofspan.test")
        set_ids = []
        try:
            rev = await msvc.create_revision(db, MeasurementRevisionIn(
                property_id=str(prop.id),
                structures=[StructureIn(ref="s1", name="Main", structure_type="main_house"),
                            StructureIn(ref="s2", name="Garage", structure_type="detached_garage")],
                facets=[FacetIn(ref="f1", structure_ref="s1", facet_label="F1", area_sqft=100, pitch_rise=6),
                        FacetIn(ref="f2", structure_ref="s2", facet_label="F2", area_sqft=50, pitch_rise=4)],
                edges=[EdgeIn(facet_ref="f1", edge_type="eave", length_ft=20),
                       EdgeIn(facet_ref="f2", edge_type="ridge", length_ft=10)],
                penetrations=[PenetrationIn(ref="p1", facet_ref="f1", pen_type="pipe_boot", quantity=2)],
            ), user)
            await db.flush()
            set_ids.append(rev.set_id)

            structs = await _structs(db, rev.id)
            s1_id, s2_id = str(structs[0].id), str(structs[1].id)
            facets = await _facets(db, rev.id)
            fmap = {f.facet_label: str(f.id) for f in facets}
            f1_id, f2_id = fmap["F1"], fmap["F2"]
            edges = await _edges(db, rev.id)
            e_by_type = {e.edge_type: str(e.id) for e in edges}
            e1_id, e2_id = e_by_type["eave"], e_by_type["ridge"]
            pens = await _pens(db, rev.id)
            p1_id = str(pens[0].id)

            # sketches on both structures
            await ssvc.save_sketch(db, str(rev.id), s1_id, edit_mode="connected_graph", document=dict(DOC), schema_version=1, expected_version=None, user=user)
            await ssvc.save_sketch(db, str(rev.id), s2_id, edit_mode="connected_graph", document=dict(DOC), schema_version=1, expected_version=None, user=user)
            # photos on children
            _add_photo(db, "measurement_structure", s1_id)
            _add_photo(db, "measurement_structure", s2_id)
            _add_photo(db, "measurement_facet", f1_id)
            _add_photo(db, "measurement_penetration", p1_id)
            await db.flush()

            # ---------- 1) NORMAL SAVE: everything sent back by UUID ref ----------
            await msvc.replace_children(db, rev, MeasurementRevisionIn(
                property_id=str(prop.id),
                structures=[StructureIn(ref=s1_id, name="Main RENAMED", structure_type="main_house"),
                            StructureIn(ref=s2_id, name="Garage", structure_type="detached_garage")],
                facets=[FacetIn(ref=f1_id, structure_ref=s1_id, facet_label="F1", area_sqft=120, pitch_rise=6),
                        FacetIn(ref=f2_id, structure_ref=s2_id, facet_label="F2", area_sqft=50, pitch_rise=4)],
                edges=[EdgeIn(ref=e1_id, facet_ref=f1_id, edge_type="eave", length_ft=25),
                       EdgeIn(ref=e2_id, facet_ref=f2_id, edge_type="ridge", length_ft=10)],
                penetrations=[PenetrationIn(ref=p1_id, facet_ref=f1_id, pen_type="pipe_boot", quantity=3)],
            ))
            await db.flush()

            assert {str(x.id) for x in await _structs(db, rev.id)} == {s1_id, s2_id}, "structure UUIDs must be preserved on normal save"
            assert {str(x.id) for x in await _facets(db, rev.id)} == {f1_id, f2_id}
            assert {str(x.id) for x in await _edges(db, rev.id)} == {e1_id, e2_id}, "edge UUIDs must be preserved (EdgeIn.ref)"
            assert {str(x.id) for x in await _pens(db, rev.id)} == {p1_id}
            renamed = {s.id: s.name for s in await _structs(db, rev.id)}
            assert renamed[_uuid.UUID(s1_id)] == "Main RENAMED"
            # both sketches survive, still bound to the SAME structure UUIDs
            assert await _sketch_struct_ids(db, rev.id) == {s1_id, s2_id}, "sketches must survive a normal save"
            # photos untouched — still on the SAME entity UUIDs, nothing moved to the revision
            assert await _photo_count(db, "measurement_structure", s1_id) == 1
            assert await _photo_count(db, "measurement_facet", f1_id) == 1
            assert await _photo_count(db, "measurement_penetration", p1_id) == 1
            assert await _photo_count(db, "measurement_revision", rev.id) == 0, "surviving-child photos must NOT be moved"

            # ---------- 2) INTENTIONAL DELETE: omit structure s2 ----------
            await msvc.replace_children(db, rev, MeasurementRevisionIn(
                property_id=str(prop.id),
                structures=[StructureIn(ref=s1_id, name="Main RENAMED", structure_type="main_house")],
                facets=[FacetIn(ref=f1_id, structure_ref=s1_id, facet_label="F1", area_sqft=120, pitch_rise=6)],
                edges=[EdgeIn(ref=e1_id, facet_ref=f1_id, edge_type="eave", length_ft=25)],
                penetrations=[PenetrationIn(ref=p1_id, facet_ref=f1_id, pen_type="pipe_boot", quantity=3)],
            ))
            await db.flush()

            assert {str(x.id) for x in await _structs(db, rev.id)} == {s1_id}
            assert {str(x.id) for x in await _facets(db, rev.id)} == {f1_id}
            # s2 sketch CASCADE-deleted; s1 sketch survives
            assert await _sketch_struct_ids(db, rev.id) == {s1_id}, "deleted structure's sketch must be cascade-removed"
            # s1 photo stays; s2 (deleted) photo retained on the revision, not orphaned
            assert await _photo_count(db, "measurement_structure", s1_id) == 1
            assert await _photo_count(db, "measurement_structure", s2_id) == 0
            assert await _photo_count(db, "measurement_revision", rev.id) == 1, "deleted-child photo must be retained on the revision"

            # ---------- 3) MIXED add + update + delete ----------
            await msvc.replace_children(db, rev, MeasurementRevisionIn(
                property_id=str(prop.id),
                structures=[StructureIn(ref=s1_id, name="Main FINAL", structure_type="main_house"),
                            StructureIn(ref="new-struct", name="Addition", structure_type="addition")],
                facets=[FacetIn(ref=f1_id, structure_ref=s1_id, facet_label="F1", area_sqft=120, pitch_rise=6),
                        FacetIn(ref="new-facet", structure_ref="new-struct", facet_label="F9", area_sqft=33, pitch_rise=5)],
                edges=[EdgeIn(ref=e1_id, facet_ref=f1_id, edge_type="eave", length_ft=25),
                       EdgeIn(facet_ref="new-facet", edge_type="rake", length_ft=8)],
                penetrations=[PenetrationIn(ref=p1_id, facet_ref=f1_id, pen_type="pipe_boot", quantity=3)],
            ))
            await db.flush()

            structs3 = await _structs(db, rev.id)
            ids3 = {str(x.id) for x in structs3}
            assert s1_id in ids3 and len(ids3) == 2, "s1 preserved + one new structure"
            new_struct_id = next(i for i in ids3 if i != s1_id)
            assert new_struct_id not in (s1_id, s2_id), "new structure gets a fresh UUID"
            assert {s.id: s.name for s in structs3}[_uuid.UUID(s1_id)] == "Main FINAL"
            # s1 sketch still present after a mixed save
            assert s1_id in await _sketch_struct_ids(db, rev.id)
            # new facet linked to the new structure
            new_facet = next(f for f in await _facets(db, rev.id) if f.facet_label == "F9")
            assert str(new_facet.structure_id) == new_struct_id

            # ---------- 4) cross-revision / stale ref rejection (409, no silent insert) ----------
            rev_other = await msvc.create_revision(db, MeasurementRevisionIn(
                property_id=str(prop2.id),
                structures=[StructureIn(ref="o1", name="Other House", structure_type="main_house")],
            ), user)
            await db.flush()
            set_ids.append(rev_other.set_id)
            other_struct_id = str((await _structs(db, rev_other.id))[0].id)
            other_facet = MeasurementFacet(revision_id=rev_other.id, facet_label="OF", area_sqft=10)
            db.add(other_facet)
            await db.flush()
            other_facet_id = str(other_facet.id)

            # Each rejection runs inside a SAVEPOINT so its partial writes roll back on the 409 while the
            # committed happy-path state (via the outer transaction) stays intact — no full rollback.
            # (a) structure ref that belongs to ANOTHER revision -> 409
            with pytest.raises(HTTPException) as ei:
                async with db.begin_nested():
                    await msvc.replace_children(db, rev, MeasurementRevisionIn(
                        property_id=str(prop.id),
                        structures=[StructureIn(ref=other_struct_id, name="hijack")],
                    ))
            assert ei.value.status_code == 409

            # (b) random stale UUID -> 409 (never inserted as new)
            with pytest.raises(HTTPException) as ei:
                async with db.begin_nested():
                    await msvc.replace_children(db, rev, MeasurementRevisionIn(
                        property_id=str(prop.id),
                        structures=[StructureIn(ref=str(_uuid.uuid4()), name="ghost")],
                    ))
            assert ei.value.status_code == 409

            # (c) direct facet_id fallback pointing at a foreign facet -> 409 (no ownership bypass)
            with pytest.raises(HTTPException) as ei:
                async with db.begin_nested():
                    await msvc.replace_children(db, rev, MeasurementRevisionIn(
                        property_id=str(prop.id),
                        structures=[StructureIn(ref=s1_id, name="Main FINAL", structure_type="main_house"),
                                    StructureIn(ref=new_struct_id, name="Addition", structure_type="addition")],
                        facets=[FacetIn(ref=f1_id, structure_ref=s1_id, facet_label="F1", area_sqft=120)],
                        edges=[EdgeIn(facet_id=other_facet_id, edge_type="eave", length_ft=5)],
                    ))
            assert ei.value.status_code == 409

            # after all rejections, revision rev is intact & unchanged (s1 + new struct still there)
            assert {str(x.id) for x in await _structs(db, rev.id)} == ids3
            assert s1_id in await _sketch_struct_ids(db, rev.id)
        finally:
            # Nothing was committed — the whole scenario ran in one transaction. Rolling back leaves the
            # database exactly as found (fully hermetic); teardown then verifies against a wrong DB.
            await db.rollback()
            await teardown(db, set_ids=[], property_ids=[])


def test_measurement_sketch_survival():
    run_isolated(_scenario)


if __name__ == "__main__":
    run_isolated(_scenario)
    print("MEASUREMENT SKETCH SURVIVAL TESTS PASSED")
