"""OPTIONAL live-environment smoke test for the roof sketch HTTP API.

This is NOT the primary contract test — the hermetic in-process contract lives in
`test_measurement_sketch_api.py` and runs in CI with 0 skips. This file only exercises a real,
running Office instance and therefore SKIPS unless explicitly configured:
    RS_TEST_API   (default http://localhost:8001)
    RS_TEST_EMAIL, RS_TEST_PW   (an owner/office account)
No credentials are committed; cleanup deletes only the MeasurementSet this test creates.
"""
import os
import pytest
import requests

API = os.environ.get("RS_TEST_API", "http://localhost:8001")
EMAIL = os.environ.get("RS_TEST_EMAIL")
PW = os.environ.get("RS_TEST_PW")
DOC = {"schema_version": 1, "edit_mode": "connected_graph", "vertices": [{"id": "v1", "x": 0, "y": 0}], "edges": [], "facets": []}


def _delete_set(headers, set_id):
    """Safe teardown of ONLY the created set — via the SAME DATABASE_URL the app uses.
    Guards against a wrong-DB cleanup no-op and never silently swallows a failure."""
    import asyncio, sys
    sys.path.insert(0, "backend")
    from dotenv import load_dotenv; load_dotenv("backend/.env")
    from sqlalchemy import delete, select
    from db import SessionLocal, engine
    from models import MeasurementSet

    async def go():
        try:
            async with SessionLocal() as db:
                exists = (await db.execute(select(MeasurementSet.id).where(MeasurementSet.id == set_id))).first()
                assert exists is not None, (
                    "Created MeasurementSet not visible via DATABASE_URL — the API under RS_TEST_API and this "
                    "cleanup session point at DIFFERENT databases; refusing to run a blind delete.")
                await db.execute(delete(MeasurementSet).where(MeasurementSet.id == set_id))
                await db.commit()
                gone = (await db.execute(select(MeasurementSet.id).where(MeasurementSet.id == set_id))).first()
                assert gone is None, "cleanup did not delete the MeasurementSet"
        finally:
            await engine.dispose()
    asyncio.run(go())


@pytest.mark.skipif(not (EMAIL and PW), reason="Live smoke: set RS_TEST_EMAIL/RS_TEST_PW to run against a real Office instance")
def test_sketch_api_live_smoke():
    tok = requests.post(f"{API}/api/auth/login", json={"email": EMAIL, "password": PW}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    d = requests.get(f"{API}/api/properties?limit=1", headers=h).json()
    pid = (d if isinstance(d, list) else (d.get("items") or d.get("properties")))[0]["id"]

    rev = requests.post(f"{API}/api/measurements", headers=h, json={"property_id": pid, "structures": [
        {"ref": "s1", "name": "Main House", "structure_type": "main_house"},
        {"ref": "s2", "name": "Garage", "structure_type": "detached_garage"}]}).json()
    rid, set_id = rev["id"], rev["set_id"]
    s1, s2 = rev["structures"][0]["id"], rev["structures"][1]["id"]
    try:
        r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": DOC, "expected_version": None})
        assert r.status_code == 200 and r.json()["document_version"] == 1

        r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": DOC, "expected_version": 1})
        assert r.status_code == 200 and r.json()["document_version"] == 2

        r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": DOC, "expected_version": 1})
        assert r.status_code == 409 and r.json()["detail"]["server"]["document_version"] == 2

        bad = dict(DOC); bad["structure_id"] = "00000000-0000-0000-0000-000000000000"
        r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": bad, "expected_version": 2})
        assert r.status_code == 422

        r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s2}", headers=h, json={"schema_version": 1, "edit_mode": "manual_polygon", "document": {"edit_mode": "manual_polygon"}, "expected_version": None})
        assert r.status_code == 200 and r.json()["document_version"] == 1
        assert len(requests.get(f"{API}/api/mobile/measurements/{rid}/sketches", headers=h).json()) == 2

        for to in ["field_complete", "office_verified", "locked"]:
            assert requests.post(f"{API}/api/measurements/{rid}/status", headers=h, json={"to": to}).status_code == 200
        r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": DOC, "expected_version": 2})
        assert r.status_code == 409 and "locked" in r.json()["detail"].lower()
    finally:
        _delete_set(h, set_id)
