"""Full clone-remapping contract for roof sketches (Plan 1 foundation hardening).

Runnable: PYTHONPATH=backend pytest -q backend/tests/test_measurement_sketch_clone.py
Proves clone_revision -> clone_sketches remaps EVERY relational reference embedded in a sketch
(structure id, facet relational ids, penetration relational ids, proposal target ids) to the cloned
revision's new rows, while STABLE sketch-graph ids (vertices/edges/facet drawing ids) stay identical.
"""
import sys
sys.path.insert(0, "backend")

from sqlalchemy import select
from db import SessionLocal
from models import MeasurementStructure, MeasurementFacet, MeasurementPenetration
from schemas_measurements import MeasurementRevisionIn, StructureIn, FacetIn, PenetrationIn
from services import measurements as msvc
from services import measurement_sketches as ssvc

from _sketch_fixtures import FakeUser, seed_property, teardown, run_isolated


async def _scenario():
    async with SessionLocal() as db:
        prop = await seed_property(db)
        user = FakeUser(id=None, role="owner")
        set_id = None
        try:
            rev = await msvc.create_revision(db, MeasurementRevisionIn(
                property_id=str(prop.id),
                structures=[StructureIn(ref="s1", name="Main House", structure_type="main_house")],
                facets=[FacetIn(ref="f1", structure_ref="s1", facet_label="F1", area_sqft=100, pitch_rise=6)],
                penetrations=[PenetrationIn(ref="p1", facet_ref="f1", pen_type="pipe_boot", quantity=2)],
            ), user)
            await db.flush()
            set_id = rev.set_id

            old_struct = (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == rev.id))).scalars().first()
            old_facet = (await db.execute(select(MeasurementFacet).where(MeasurementFacet.revision_id == rev.id))).scalars().first()
            old_pen = (await db.execute(select(MeasurementPenetration).where(MeasurementPenetration.revision_id == rev.id))).scalars().first()
            os_id, of_id, op_id = str(old_struct.id), str(old_facet.id), str(old_pen.id)

            # A sketch that embeds relational references + stable drawing-graph ids.
            document = {
                "schema_version": 1, "edit_mode": "connected_graph", "structure_id": os_id,
                "vertices": [
                    {"id": "v1", "x": 0, "y": 0}, {"id": "v2", "x": 10, "y": 0},
                    {"id": "v3", "x": 10, "y": 8}, {"id": "v4", "x": 0, "y": 8}],
                "edges": [
                    {"id": "e1", "v1": "v1", "v2": "v2"}, {"id": "e2", "v1": "v2", "v2": "v3"},
                    {"id": "e3", "v1": "v3", "v2": "v4"}, {"id": "e4", "v1": "v4", "v2": "v1"}],
                "facets": [{"id": "f1", "edgeIds": ["e1", "e2", "e3", "e4"], "vertexIds": ["v1", "v2", "v3", "v4"],
                            "measurement_facet_id": of_id, "pitch_rise": 6}],
                "penetrations": [{"id": "pen-graph-1", "facet": "f1", "measurement_penetration_id": op_id}],
                "proposal_decisions": [
                    {"target_type": "facet", "target_id": of_id, "metric": "area_sqft", "decision": "accept"},
                    {"target_type": "penetration", "target_id": op_id, "decision": "keep_current"},
                    {"target_type": "structure", "target_id": os_id, "decision": "note"},
                ],
            }
            await ssvc.save_sketch(db, str(rev.id), os_id, edit_mode="connected_graph", document=document, schema_version=1, expected_version=None, user=user)

            new = await msvc.clone_revision(db, rev, user)
            await db.flush()

            new_struct = (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == new.id))).scalars().first()
            new_facet = (await db.execute(select(MeasurementFacet).where(MeasurementFacet.revision_id == new.id))).scalars().first()
            new_pen = (await db.execute(select(MeasurementPenetration).where(MeasurementPenetration.revision_id == new.id))).scalars().first()
            ns_id, nf_id, np_id = str(new_struct.id), str(new_facet.id), str(new_pen.id)
            # sanity: clone produced genuinely new relational ids
            assert {ns_id, nf_id, np_id}.isdisjoint({os_id, of_id, op_id})

            sketches = await ssvc.list_sketches(db, str(new.id))
            assert len(sketches) == 1
            doc = sketches[0]["document"]

            # --- relational references remapped to the clone's new rows ---
            assert doc["structure_id"] == ns_id
            assert doc["facets"][0]["measurement_facet_id"] == nf_id
            assert doc["penetrations"][0]["measurement_penetration_id"] == np_id
            dec = {d["target_type"]: d["target_id"] for d in doc["proposal_decisions"]}
            assert dec["facet"] == nf_id
            assert dec["penetration"] == np_id
            assert dec["structure"] == ns_id
            # no OLD relational id survives anywhere
            for old in (os_id, of_id, op_id):
                assert old not in str(doc)

            # --- STABLE drawing-graph ids are untouched ---
            assert [v["id"] for v in doc["vertices"]] == ["v1", "v2", "v3", "v4"]
            assert [e["id"] for e in doc["edges"]] == ["e1", "e2", "e3", "e4"]
            assert doc["facets"][0]["id"] == "f1"
            assert doc["facets"][0]["edgeIds"] == ["e1", "e2", "e3", "e4"]
            assert doc["penetrations"][0]["id"] == "pen-graph-1"
            assert sketches[0]["document_version"] == 1

            # --- canonical normalization AFTER remap: embedded metadata agrees with the row columns ---
            assert doc["structure_id"] == sketches[0]["structure_id"] == ns_id
            assert doc["edit_mode"] == sketches[0]["edit_mode"] == "connected_graph"
            assert doc["schema_version"] == sketches[0]["schema_version"] == 1
        finally:
            await teardown(db, set_ids=[set_id] if set_id else [], property_ids=[prop.id])


def test_clone_remapping_contract():
    run_isolated(_scenario)


if __name__ == "__main__":
    run_isolated(_scenario)
    print("SKETCH CLONE REMAPPING TESTS PASSED")
