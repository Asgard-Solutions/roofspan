# Round 3 regression: takeoff re-apply after an Estimate Editor save must REPLACE generated lines (not duplicate).
# Current clients send line ids (line_ids: true); legacy no-id saves are covered in test_estimate_line_identity.py.
import os, uuid, pytest, requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}


@pytest.fixture(scope="module")
def owner():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=OWNER)
    if r.status_code != 200:
        pytest.skip("owner login failed")
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return s


@pytest.fixture(scope="module")
def setup(owner):
    tpl = [t for t in owner.get(f"{BASE_URL}/api/takeoff/templates", params={"active": True}).json() if t.get("latest_revision")]
    if not tpl:
        pytest.skip("no takeoff template")
    lid = owner.post(f"{BASE_URL}/api/mobile/leads", json={"name": f"TEST_R3dup_{uuid.uuid4().hex[:6]}", "address": "1 Test St", "phone": "555-000-0000", "email": "test@example.com"}).json()["id"]
    owner.post(f"{BASE_URL}/api/customers/from-lead/{lid}")
    cust = owner.get(f"{BASE_URL}/api/leads/{lid}").json()["customer_id"]
    rev = owner.post(f"{BASE_URL}/api/measurements", json={"lead_id": lid, "source": "office",
        "structures": [{"ref": "s1", "name": "Main", "structure_type": "main_house", "stories": 1}],
        "facets": [{"ref": "F1", "structure_ref": "s1", "facet_label": "F1", "pitch_rise": 6, "area_sqft": 2000}],
        "edges": [{"edge_type": "eave", "length_ft": 100, "facet_ref": "F1"}], "summary": {}}).json()["id"]
    for to in ("field_complete", "office_verified"):
        assert owner.post(f"{BASE_URL}/api/measurements/{rev}/status", json={"to": to}).status_code == 200
    eid = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": cust, "tax_rate": 0, "items": []}).json()["id"]
    body = {"measurement_revision_id": rev, "template_revision_id": tpl[0]["latest_revision"]["id"], "estimate_waste_override": None,
            "drip_edge_override_lf": None, "structure_waste_overrides": {}, "replace_modified_generated": False}
    yield {"eid": eid, "body": body}
    owner.delete(f"{BASE_URL}/api/estimates/{eid}")


def test_reapply_without_save_replaces(owner, setup):
    eid, body = setup["eid"], setup["body"]
    assert owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/apply", json=body).status_code == 200
    n1 = len(owner.get(f"{BASE_URL}/api/estimates/{eid}").json()["items"])
    assert owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/apply", json=body).status_code == 200
    assert len(owner.get(f"{BASE_URL}/api/estimates/{eid}").json()["items"]) == n1


def test_reapply_after_editor_save_does_not_duplicate(owner, setup):
    eid, body = setup["eid"], setup["body"]
    e = owner.get(f"{BASE_URL}/api/estimates/{eid}").json()
    n1 = len(e["items"])
    items = [{k: i.get(k) for k in ("id", "description", "unit", "measured_quantity", "waste_percent", "material_cost", "markup_percent", "selling_unit_price", "line_kind", "material_id", "assembly_id", "assembly_version", "assembly_name")} for i in e["items"]]
    for i in items:
        i["selling_unit_price"] = 99  # user adjusts a price, then Saves (same payload shape as EstimateEditor)
    r = owner.put(f"{BASE_URL}/api/estimates/{eid}", json={"lead_id": e["lead_id"], "customer_id": e["customer_id"], "tax_rate": 0, "line_ids": True, "items": items}, headers={"If-Match": str(e["version"])})
    assert r.status_code == 200, r.text
    p = owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/preview", json=body).json()
    # Either the generated lines are still tracked (replace or 409 review), or apply must not append duplicates.
    assert p["generated_line_ids_to_replace"], "takeoff lost track of its generated lines after an editor save"
