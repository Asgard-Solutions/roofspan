"""Pytest coverage for Roof Measurement Increment A - lifecycle, mobile, DELETE rules."""
import os, uuid, pytest, requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://roofspan-cloud-test.preview.emergentagent.com").rstrip("/")
EMAIL = "pjacobsen@asgardsolution.io"
PW = "RoofSpan#Owner2026"


@pytest.fixture(scope="module")
def auth():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PW}, timeout=30)
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def property_id(auth):
    r = requests.get(f"{BASE_URL}/api/properties?limit=1", headers=auth, timeout=30)
    items = r.json()
    items = items if isinstance(items, list) else (items.get("items") or items.get("properties"))
    assert items, "need at least one property"
    return items[0]["id"]


def _payload(pid):
    return {
        "property_id": pid, "source": "field", "reported_area_sqft": 2912,
        "structures": [
            {"ref": "s1", "name": "Main House", "structure_type": "main_house", "stories": 2},
            {"ref": "s2", "name": "Detached Garage", "structure_type": "detached_garage", "stories": 1},
        ],
        "facets": [
            {"ref": "F1", "structure_ref": "s1", "facet_label": "F1", "pitch_rise": 6, "area_sqft": 1200},
            {"ref": "F2", "structure_ref": "s1", "facet_label": "F2", "pitch_rise": 6, "area_sqft": 1000},
            {"ref": "F3", "structure_ref": "s1", "facet_label": "F3", "pitch_rise": 4.5, "area_sqft": 400},
            {"ref": "F4", "structure_ref": "s2", "facet_label": "F4", "pitch_rise": 4, "area_sqft": 246},
        ],
        "edges": [
            {"edge_type": "eave", "length_ft": 120, "facet_ref": "F1"},
            {"edge_type": "rake", "length_ft": 80, "facet_ref": "F1"},
            {"edge_type": "ridge", "length_ft": 60},
            {"edge_type": "valley", "length_ft": 24, "facet_ref": "F1", "facet_ref_secondary": "F2"},
            {"edge_type": "hip", "length_ft": 18},
        ],
        "penetrations": [
            {"pen_type": "pipe_boot", "quantity": 3, "diameter_in": 3, "facet_ref": "F1"},
            {"pen_type": "skylight", "quantity": 1, "facet_ref": "F2"},
            {"pen_type": "chimney", "quantity": 1, "width_in": 24, "length_in": 36},
        ],
        "summary": {"existing_covering_type": "3-tab asphalt", "existing_layers": 2, "full_redeck": False,
                    "ridge_vent_lf": 40, "damaged_deck_sf": 64, "replacement_sheets": 2, "steep_access": True},
    }


# ---------- Office lifecycle ----------

class TestMeasurementLifecycle:
    created_ids = []

    def test_create_draft_and_derived_totals(self, auth, property_id):
        r = requests.post(f"{BASE_URL}/api/measurements", headers=auth, json=_payload(property_id), timeout=30)
        assert r.status_code == 201, r.text
        rev = r.json()
        TestMeasurementLifecycle.created_ids.append(rev["id"])
        t = rev["totals"]
        assert rev["status"] == "draft" and rev["editable"] is True
        assert abs(t["total_area_sqft"] - 2846) < 0.01
        assert abs(t["total_squares"] - 28.46) < 0.01
        assert t["facet_count"] == 4 and t["structure_count"] == 2
        assert t["predominant_pitch"] == 6
        assert t["edge_totals"]["eave_lf"] == 120
        assert t["edge_totals"]["valley_lf"] == 24
        assert t["penetration_total"] == 5
        assert t["reported_area_delta_sqft"] == round(2846 - 2912, 2)
        byp = {p["pitch"]: p["area_sqft"] for p in t["area_by_pitch"]}
        assert byp.get(6) == 2200 and byp.get(4.5) == 400 and byp.get(4) == 246
        assert any(f["structure_id"] for f in rev["facets"]), "facet->structure link missing"

    def test_get_and_list(self, auth, property_id):
        rid = TestMeasurementLifecycle.created_ids[0]
        g = requests.get(f"{BASE_URL}/api/measurements/{rid}", headers=auth, timeout=30)
        assert g.status_code == 200
        assert g.json()["totals"]["total_squares"] == 28.46
        lst = requests.get(f"{BASE_URL}/api/measurements?property_id={property_id}", headers=auth, timeout=30).json()
        assert any(x["id"] == rid for x in lst)

    def test_put_replaces_draft_and_recomputes(self, auth, property_id):
        rid = TestMeasurementLifecycle.created_ids[0]
        p = _payload(property_id)
        p["facets"][0]["area_sqft"] = 1300
        r = requests.put(f"{BASE_URL}/api/measurements/{rid}", headers=auth, json=p, timeout=30)
        assert r.status_code == 200, r.text
        assert abs(r.json()["totals"]["total_area_sqft"] - 2946) < 0.01

    def test_status_transitions_and_lock(self, auth):
        rid = TestMeasurementLifecycle.created_ids[0]
        for to in ["field_complete", "office_verified", "locked"]:
            s = requests.post(f"{BASE_URL}/api/measurements/{rid}/status", headers=auth, json={"to": to}, timeout=30)
            assert s.status_code == 200, (to, s.text)
            assert s.json()["status"] == to
        rev = requests.get(f"{BASE_URL}/api/measurements/{rid}", headers=auth, timeout=30).json()
        assert rev["is_immutable"] is True and rev["editable"] is False

    def test_put_on_locked_rejected_409(self, auth, property_id):
        rid = TestMeasurementLifecycle.created_ids[0]
        r = requests.put(f"{BASE_URL}/api/measurements/{rid}", headers=auth, json=_payload(property_id), timeout=30)
        assert r.status_code == 409

    def test_delete_on_locked_rejected_409(self, auth):
        rid = TestMeasurementLifecycle.created_ids[0]
        r = requests.delete(f"{BASE_URL}/api/measurements/{rid}", headers=auth, timeout=30)
        assert r.status_code == 409, r.status_code

    def test_new_revision_clones_from_locked(self, auth):
        rid = TestMeasurementLifecycle.created_ids[0]
        nr = requests.post(f"{BASE_URL}/api/measurements/{rid}/new-revision", headers=auth, timeout=30)
        assert nr.status_code == 201, nr.text
        nrev = nr.json()
        TestMeasurementLifecycle.created_ids.append(nrev["id"])
        assert nrev["status"] == "draft"
        assert nrev["editable"] is True
        assert nrev["supersedes_revision_id"] == rid
        assert nrev["revision_number"] >= 2
        assert nrev["totals"]["facet_count"] == 4

    def test_delete_draft_succeeds(self, auth):
        # delete the cloned draft
        rid = TestMeasurementLifecycle.created_ids[1]
        r = requests.delete(f"{BASE_URL}/api/measurements/{rid}", headers=auth, timeout=30)
        assert r.status_code in (200, 204), r.text


# ---------- Mobile endpoints ----------

class TestMobile:
    def test_mobile_create_idempotent_and_field_complete(self, auth, property_id):
        ik = f"meas-mobile-{uuid.uuid4().hex[:10]}"
        mh = {**auth, "Idempotency-Key": ik}
        payload = {"property_id": property_id,
                   "facets": [{"ref": "F1", "facet_label": "F1", "pitch_rise": 5, "area_sqft": 500}]}
        m1 = requests.post(f"{BASE_URL}/api/mobile/measurements", headers=mh, json=payload, timeout=30)
        assert m1.status_code == 201, m1.text
        mid = m1.json()["id"]
        # idempotent replay
        m2 = requests.post(f"{BASE_URL}/api/mobile/measurements", headers=mh, json={"property_id": property_id}, timeout=30)
        assert m2.status_code in (200, 201)
        assert m2.json()["id"] == mid
        assert m2.json().get("replayed") is True
        # list
        lst = requests.get(f"{BASE_URL}/api/mobile/measurements?property_id={property_id}", headers=auth, timeout=30)
        assert lst.status_code == 200
        assert any(x["id"] == mid for x in lst.json())
        # field-complete
        fc = requests.post(f"{BASE_URL}/api/mobile/measurements/{mid}/field-complete", headers=auth, timeout=30)
        assert fc.status_code == 200
        assert fc.json()["status"] == "field_complete"
        # cleanup: field_complete not draft -> delete should be rejected. transition back not possible; leave record.
        # Try to delete (may be 409 — acceptable).
        requests.delete(f"{BASE_URL}/api/measurements/{mid}", headers=auth, timeout=30)
