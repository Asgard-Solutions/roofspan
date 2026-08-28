"""Pytest contract tests for the roof sketch HTTP API (Plan 1 foundation corrections).

No credentials are committed. Integration runs require env vars:
    RS_TEST_API   (default http://localhost:8001)
    RS_TEST_EMAIL, RS_TEST_PW   (an owner/office account)
Without RS_TEST_EMAIL/RS_TEST_PW the test SKIPS (never hardcodes a real account).
Cleanup deletes only the MeasurementSet this test creates.
"""
import os
import pytest
import requests

API = os.environ.get("RS_TEST_API", "http://localhost:8001")
EMAIL = os.environ.get("RS_TEST_EMAIL")
PW = os.environ.get("RS_TEST_PW")
DOC = {"schema_version": 1, "edit_mode": "connected_graph", "vertices": [{"id": "v1", "x": 0, "y": 0}], "edges": [], "facets": []}


def _delete_set(headers, set_id):
    # best-effort safe teardown via a short-lived DB session (only the created set)
    try:
        import asyncio, sys
        sys.path.insert(0, "backend")
        from dotenv import load_dotenv; load_dotenv("backend/.env")
        from sqlalchemy import delete
        from db import SessionLocal
        from models import MeasurementSet

        async def go():
            async with SessionLocal() as db:
                await db.execute(delete(MeasurementSet).where(MeasurementSet.id == set_id))
                await db.commit()
        asyncio.run(go())
    except Exception:
        pass


@pytest.mark.skipif(not (EMAIL and PW), reason="Set RS_TEST_EMAIL/RS_TEST_PW to run the sketch API integration test")
def test_sketch_api_contract():
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

        # stale / concurrent same-version writer -> 409 with server payload
        r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": DOC, "expected_version": 1})
        assert r.status_code == 409 and r.json()["detail"]["server"]["document_version"] == 2

        # normalization rejects a contradictory embedded structure id
        bad = dict(DOC); bad["structure_id"] = "00000000-0000-0000-0000-000000000000"
        r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": bad, "expected_version": 2})
        assert r.status_code == 422

        # independent structure + field mirror
        r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s2}", headers=h, json={"schema_version": 1, "edit_mode": "manual_polygon", "document": {"edit_mode": "manual_polygon"}, "expected_version": None})
        assert r.status_code == 200 and r.json()["document_version"] == 1
        assert len(requests.get(f"{API}/api/mobile/measurements/{rid}/sketches", headers=h).json()) == 2

        # lock -> PUT rejected
        for to in ["field_complete", "office_verified", "locked"]:
            assert requests.post(f"{API}/api/measurements/{rid}/status", headers=h, json={"to": to}).status_code == 200
        r = requests.put(f"{API}/api/measurements/{rid}/sketches/{s1}", headers=h, json={"schema_version": 1, "edit_mode": "connected_graph", "document": DOC, "expected_version": 2})
        assert r.status_code == 409 and "locked" in r.json()["detail"].lower()
    finally:
        _delete_set(h, set_id)
