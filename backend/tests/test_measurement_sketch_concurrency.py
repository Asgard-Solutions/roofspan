"""True concurrent-writer contracts for the roof sketch CAS (Plan 1 foundation hardening).

Runnable: PYTHONPATH=backend pytest -q backend/tests/test_measurement_sketch_concurrency.py
Proves the optimistic concurrency guard at the DATABASE level using two independent sessions
(two connections / two transactions), not just sequential calls:
  1. existing-row race  -> row-lock serializes; the loser matches 0 rows -> SketchConflict
  2. first-create race   -> the UNIQUE(revision_id, structure_id) index serializes; the loser
                            hits IntegrityError, recovers in a savepoint -> SketchConflict
"""
import asyncio
import sys
sys.path.insert(0, "backend")

import pytest
from sqlalchemy import select
from db import SessionLocal
from models import MeasurementStructure
from schemas_measurements import MeasurementRevisionIn, StructureIn
from services import measurements as msvc
from services import measurement_sketches as ssvc

from _sketch_fixtures import FakeUser, seed_property, teardown

DOC = {"schema_version": 1, "edit_mode": "connected_graph", "vertices": [], "edges": [], "facets": []}


async def _make_revision(db, prop, user):
    rev = await msvc.create_revision(db, MeasurementRevisionIn(property_id=str(prop.id), structures=[
        StructureIn(ref="s1", name="Main House", structure_type="main_house")]), user)
    await db.flush()
    struct = (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == rev.id))).scalars().first()
    return rev, str(struct.id)


async def _existing_row_race():
    async with SessionLocal() as setup:
        prop = await seed_property(setup)
        user = FakeUser(id=None, role="owner")
        set_id = None
        try:
            rev, sid = await _make_revision(setup, prop, user)
            set_id = rev.set_id
            # seed a version-1 sketch and COMMIT so both racers read the same committed base
            await ssvc.save_sketch(setup, str(rev.id), sid, edit_mode="connected_graph", document=dict(DOC), schema_version=1, expected_version=None, user=user)
            await setup.commit()

            async with SessionLocal() as A, SessionLocal() as B:
                # A wins: CAS UPDATE runs + flush (row locked), NOT committed yet
                res_a = await ssvc.save_sketch(A, str(rev.id), sid, edit_mode="connected_graph", document=dict(DOC), schema_version=1, expected_version=1, user=user)
                assert res_a["document_version"] == 2

                # B races from the SAME base version -> its UPDATE ... WHERE document_version=1 blocks on A's lock
                task_b = asyncio.create_task(
                    ssvc.save_sketch(B, str(rev.id), sid, edit_mode="connected_graph", document=dict(DOC), schema_version=1, expected_version=1, user=user))
                await asyncio.sleep(0.6)  # let B reach and block on the row lock
                assert not task_b.done(), "second writer must block on the row lock until the winner commits"

                await A.commit()  # releases the lock; B's WHERE now matches 0 rows

                with pytest.raises(ssvc.SketchConflict) as ci:
                    await task_b
                assert ci.value.server["document_version"] == 2, "loser must see the winner's committed version"
                await B.rollback()
        finally:
            await teardown(setup, set_ids=[set_id] if set_id else [], property_ids=[prop.id])


async def _first_create_race():
    async with SessionLocal() as setup:
        prop = await seed_property(setup)
        user = FakeUser(id=None, role="owner")
        set_id = None
        try:
            rev, sid = await _make_revision(setup, prop, user)
            set_id = rev.set_id
            await setup.commit()  # NO sketch yet — both racers will try to create

            async with SessionLocal() as A, SessionLocal() as B:
                # A wins the create: INSERT + flush inside a savepoint, unique index entry locked
                res_a = await ssvc.save_sketch(A, str(rev.id), sid, edit_mode="connected_graph", document=dict(DOC), schema_version=1, expected_version=None, user=user)
                assert res_a["document_version"] == 1

                task_b = asyncio.create_task(
                    ssvc.save_sketch(B, str(rev.id), sid, edit_mode="connected_graph", document=dict(DOC), schema_version=1, expected_version=None, user=user))
                await asyncio.sleep(0.6)  # B's duplicate INSERT blocks on the unique index
                assert not task_b.done(), "second creator must block on the unique index until the winner commits"

                await A.commit()  # B's INSERT now fails with a duplicate key

                with pytest.raises(ssvc.SketchConflict):
                    await task_b
                await B.rollback()

                # exactly one row exists at version 1
                async with SessionLocal() as chk:
                    rows = await ssvc.list_sketches(chk, str(rev.id))
                    assert len(rows) == 1 and rows[0]["document_version"] == 1
        finally:
            await teardown(setup, set_ids=[set_id] if set_id else [], property_ids=[prop.id])


def test_existing_row_concurrent_writer():
    from _sketch_fixtures import run_isolated
    run_isolated(_existing_row_race)


def test_first_create_concurrent_writer():
    from _sketch_fixtures import run_isolated
    run_isolated(_first_create_race)


if __name__ == "__main__":
    from _sketch_fixtures import run_isolated
    run_isolated(_existing_row_race)
    run_isolated(_first_create_race)
    print("SKETCH CONCURRENCY TESTS PASSED")
