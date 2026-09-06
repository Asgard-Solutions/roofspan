"""Backend acceptance tests for Mobile RoofSpan Field sync (iteration 88).

Covers:
- Canonical measurement-set resolver parity (Office list, Field list by lead_id/property_id, watermark)
- build_out sketch metadata parity (has_sketch, sketch_document_version, sketch_updated_at)
- Update SUCCESS returns a NEW server token (updated_at rotates)
- Update CONFLICT (409) preserves both versions (detail.server present with id + updated_at)
- Update VALIDATION failure (422)
"""
import os
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def property_id(hdr):
    suffix = uuid.uuid4().hex[:8]
    r = requests.post(f"{BASE_URL}/api/properties", headers=hdr, json={
        "address_line1": f"TEST_{suffix} 123 Main St",
        "city": "Testville", "state": "TX", "zip_code": "75001",
        "latitude": 32.7, "longitude": -96.8, "property_type": "residential",
    }, timeout=30)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def lead_id(hdr, property_id):
    r = requests.post(f"{BASE_URL}/api/mobile/leads", headers=hdr,
                      json={"name": f"TEST_lead_{uuid.uuid4().hex[:6]}", "property_id": property_id}, timeout=30)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def measurement(hdr, lead_id):
    payload = {
        "lead_id": lead_id,
        "structures": [{"name": "Main", "structure_type": "main_house", "ref": "s1"}],
    }
    r = requests.post(f"{BASE_URL}/api/mobile/measurements", headers=hdr, json=payload, timeout=30)
    assert r.status_code == 201, r.text
    return r.json()


# --- Acceptance 1: Office↔Field parity via canonical resolver ---
class TestRevisionFamilyParity:
    def test_office_and_field_return_same_revision(self, hdr, lead_id, property_id, measurement):
        rev_id = measurement["id"]
        set_id = measurement["set_id"]

        # Office list (mounted at /api/measurements)
        r_office = requests.get(f"{BASE_URL}/api/measurements", headers=hdr,
                                params={"lead_id": lead_id}, timeout=30)
        assert r_office.status_code == 200, r_office.text
        office_ids = sorted([x["id"] for x in r_office.json()])

        # Field list by lead_id
        r_field_lead = requests.get(f"{BASE_URL}/api/mobile/measurements", headers=hdr,
                                    params={"lead_id": lead_id}, timeout=30)
        assert r_field_lead.status_code == 200, r_field_lead.text
        field_lead_ids = sorted([x["id"] for x in r_field_lead.json()])

        # Field list by property_id
        r_field_prop = requests.get(f"{BASE_URL}/api/mobile/measurements", headers=hdr,
                                    params={"property_id": property_id}, timeout=30)
        assert r_field_prop.status_code == 200, r_field_prop.text
        field_prop_ids = sorted([x["id"] for x in r_field_prop.json()])

        assert rev_id in office_ids
        assert office_ids == field_lead_ids == field_prop_ids, (
            f"Office={office_ids} FieldLead={field_lead_ids} FieldProp={field_prop_ids}")

        # Watermark by property_id must resolve same measurement_set_id
        r_wm = requests.get(f"{BASE_URL}/api/mobile/measurements/watermark", headers=hdr,
                            params={"property_id": property_id}, timeout=30)
        assert r_wm.status_code == 200, r_wm.text
        assert r_wm.json()["measurement_set_id"] == set_id

        # Watermark by lead_id also same set
        r_wm2 = requests.get(f"{BASE_URL}/api/mobile/measurements/watermark", headers=hdr,
                             params={"lead_id": lead_id}, timeout=30)
        assert r_wm2.status_code == 200
        assert r_wm2.json()["measurement_set_id"] == set_id


# --- Acceptance 2: build_out sketch metadata parity ---
class TestSketchMetadataParity:
    def test_initial_no_sketch(self, hdr, measurement):
        r = requests.get(f"{BASE_URL}/api/mobile/measurements/{measurement['id']}", headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        structs = r.json()["structures"]
        assert len(structs) == 1
        s = structs[0]
        assert s["has_sketch"] is False
        assert s["sketch_document_version"] is None
        assert s.get("sketch_updated_at") in (None, "")

    def test_after_put_sketch_metadata_updated(self, hdr, measurement):
        rev_id = measurement["id"]
        # get structure id
        r = requests.get(f"{BASE_URL}/api/mobile/measurements/{rev_id}", headers=hdr, timeout=30)
        struct_id = r.json()["structures"][0]["id"]

        payload = {
            "schema_version": 1,
            "edit_mode": "connected_graph",
            "document": {"edit_mode": "connected_graph", "vertices": [], "edges": [], "facets": [], "penetrations": []},
            "expected_version": 0,
        }
        r_put = requests.put(f"{BASE_URL}/api/mobile/measurements/{rev_id}/sketches/{struct_id}",
                             headers=hdr, json=payload, timeout=30)
        assert r_put.status_code == 200, r_put.text
        put_body = r_put.json()
        put_version = put_body.get("document_version")
        assert put_version == 1

        # Re-GET measurement - metadata should be updated
        r2 = requests.get(f"{BASE_URL}/api/mobile/measurements/{rev_id}", headers=hdr, timeout=30)
        assert r2.status_code == 200
        s = r2.json()["structures"][0]
        assert s["has_sketch"] is True, s
        assert s["sketch_document_version"] == 1
        assert s["sketch_updated_at"] is not None

        # Confirm sketches list parity
        r_list = requests.get(f"{BASE_URL}/api/mobile/measurements/{rev_id}/sketches", headers=hdr, timeout=30)
        assert r_list.status_code == 200
        docs = r_list.json()
        assert len(docs) == 1
        assert str(docs[0]["structure_id"]) == str(struct_id)
        assert docs[0]["document_version"] == 1


# --- Acceptance 3+4: Update SUCCESS rotates token; stale If-Match => 409 with detail.server ---
class TestUpdateTokenAndConflict:
    def test_update_success_returns_new_token(self, hdr, lead_id, measurement):
        rev_id = measurement["id"]
        # fresh GET to get current updated_at
        r0 = requests.get(f"{BASE_URL}/api/mobile/measurements/{rev_id}", headers=hdr, timeout=30)
        current_updated_at = r0.json()["updated_at"]

        payload = {
            "lead_id": lead_id,
            "structures": [{"name": "Main Updated", "structure_type": "main_house"}],
        }
        headers = dict(hdr); headers["If-Match"] = current_updated_at
        r = requests.put(f"{BASE_URL}/api/mobile/measurements/{rev_id}", headers=headers, json=payload, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated_at"] != current_updated_at
        # persist new token for next test
        pytest.new_token = body["updated_at"]

    def test_update_conflict_preserves_both(self, hdr, lead_id, measurement):
        rev_id = measurement["id"]
        stale = "2020-01-01T00:00:00+00:00"
        payload = {
            "lead_id": lead_id,
            "structures": [{"name": "Should not save", "structure_type": "main_house"}],
        }
        headers = dict(hdr); headers["If-Match"] = stale
        r = requests.put(f"{BASE_URL}/api/mobile/measurements/{rev_id}", headers=headers, json=payload, timeout=30)
        assert r.status_code == 409, r.text
        body = r.json()
        detail = body.get("detail")
        assert isinstance(detail, dict), f"detail must be object: {body}"
        server = detail.get("server")
        assert isinstance(server, dict), f"detail.server must be object: {detail}"
        assert server.get("id") == rev_id
        assert server.get("updated_at") is not None


# --- Acceptance 5: Update VALIDATION failure (422) ---
class TestUpdateValidation:
    def test_invalid_facet_pitch_rise_returns_422(self, hdr, lead_id):
        # Create fresh revision to keep isolation
        rc = requests.post(f"{BASE_URL}/api/mobile/measurements", headers=hdr,
                           json={"lead_id": lead_id,
                                 "structures": [{"name": "V", "structure_type": "main_house", "ref": "s1"}]},
                           timeout=30)
        assert rc.status_code == 201, rc.text
        rev = rc.json()
        payload = {
            "lead_id": lead_id,
            "structures": [{"name": "V", "structure_type": "main_house", "ref": "s1"}],
            "facets": [{
                "structure_ref": "s1",
                "facet_label": "F1",
                "pitch_rise": "not-a-number",  # invalid — should be numeric
                "area_sqft": 100,
            }],
        }
        headers = dict(hdr); headers["If-Match"] = rev["updated_at"]
        r = requests.put(f"{BASE_URL}/api/mobile/measurements/{rev['id']}",
                         headers=headers, json=payload, timeout=30)
        assert r.status_code in (400, 422), f"Expected 4xx, got {r.status_code}: {r.text}"
        # Body must NOT be a successful revision (has no top-level 'structures')
        body = r.json()
        assert "detail" in body
