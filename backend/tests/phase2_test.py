"""RoofSpan Phase 2 - Property Acquisition backend tests.

Covers:
- Territory CRUD + RBAC + delete-preserves-properties
- Import preview (sample mode) + RBAC
- Import run + idempotency (same run creates 0, updates all)
- Properties list / geojson / detail
- Do Not Knock PATCH (sales allowed)
- Visits (do_not_knock outcome flips property) + convert-to-lead (fallback to owner name)
- Change password (wrong -> 400, correct -> ok -> revert)
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def owner_headers():
    r = requests.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def sales_headers(owner_headers):
    email = f"TEST_sales_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "SalesTemp#2026"
    r = requests.post(f"{API}/users", json={"email": email, "full_name": "TEST Sales", "password": pwd, "role": "sales"}, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    lr = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=15)
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}


# Reasonably-sized polygon around Nashville, TN (small area to keep sample gen fast)
SAMPLE_POLY = {
    "type": "Polygon",
    "coordinates": [[
        [-86.790, 36.155],
        [-86.780, 36.155],
        [-86.780, 36.165],
        [-86.790, 36.165],
        [-86.790, 36.155],
    ]],
}


@pytest.fixture(scope="module")
def territory(owner_headers):
    payload = {"name": f"TEST_Territory_{uuid.uuid4().hex[:6]}", "description": "phase2 test", "color": "#22C55E", "geometry": SAMPLE_POLY, "active": True}
    r = requests.post(f"{API}/territories", json=payload, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- Territories CRUD + RBAC ----------
def test_territory_create_and_list(owner_headers, territory):
    r = requests.get(f"{API}/territories", headers=owner_headers, timeout=15)
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert territory["id"] in ids
    match = next(t for t in r.json() if t["id"] == territory["id"])
    assert "property_count" in match
    assert match["name"] == territory["name"]


def test_territory_update(owner_headers, territory):
    new_name = territory["name"] + "_upd"
    r = requests.put(f"{API}/territories/{territory['id']}", json={"name": new_name, "color": "#FF00AA"}, headers=owner_headers, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == new_name
    assert d["color"] == "#FF00AA"


def test_territory_rbac_sales_forbidden(sales_headers):
    # GET allowed
    r = requests.get(f"{API}/territories", headers=sales_headers, timeout=15)
    assert r.status_code == 200
    # POST forbidden
    r = requests.post(f"{API}/territories", json={"name": "X", "geometry": SAMPLE_POLY}, headers=sales_headers, timeout=15)
    assert r.status_code == 403


def test_territory_invalid_polygon_422(owner_headers):
    r = requests.post(f"{API}/territories", json={"name": "bad", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}}, headers=owner_headers, timeout=15)
    assert r.status_code == 422


# ---------- Import preview ----------
def test_import_preview_sample_mode(owner_headers, territory):
    r = requests.post(f"{API}/territories/{territory['id']}/import/preview", json={"max_records": 25}, headers=owner_headers, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["mode"] == "sample"
    assert d["rentcast_configured"] is False
    assert d["estimated_properties"] > 0
    assert isinstance(d["sample"], list) and len(d["sample"]) > 0
    # sample entries should carry source='sample'
    assert d["sample"][0].get("source") == "sample"


def test_import_preview_forbidden_for_sales(sales_headers, territory):
    r = requests.post(f"{API}/territories/{territory['id']}/import/preview", json={"max_records": 5}, headers=sales_headers, timeout=15)
    assert r.status_code == 403


# ---------- Import run + idempotency ----------
def _wait_for_job(job_id, headers, timeout=45):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(f"{API}/imports/{job_id}", headers=headers, timeout=15)
        if r.status_code == 200:
            last = r.json()
            if last["status"] in ("completed", "failed"):
                return last
        time.sleep(1.0)
    return last


@pytest.fixture(scope="module")
def imported_territory(owner_headers, territory):
    r = requests.post(f"{API}/territories/{territory['id']}/import", json={"max_records": 20}, headers=owner_headers, timeout=15)
    assert r.status_code == 202, r.text
    job = r.json()
    final = _wait_for_job(job["id"], owner_headers)
    assert final is not None, "no job status"
    assert final["status"] == "completed", f"job did not complete: {final}"
    assert final["created_count"] > 0
    return {"territory_id": territory["id"], "first_job": final}


def test_import_creates_properties(owner_headers, imported_territory):
    tid = imported_territory["territory_id"]
    r = requests.get(f"{API}/properties", params={"territory_id": tid}, headers=owner_headers, timeout=15)
    assert r.status_code == 200
    props = r.json()
    assert len(props) == imported_territory["first_job"]["created_count"]


def test_import_is_idempotent(owner_headers, imported_territory):
    tid = imported_territory["territory_id"]
    # Snapshot property count before
    before = requests.get(f"{API}/properties", params={"territory_id": tid}, headers=owner_headers, timeout=15).json()
    n_before = len(before)

    r = requests.post(f"{API}/territories/{tid}/import", json={"max_records": 20}, headers=owner_headers, timeout=15)
    assert r.status_code == 202
    final = _wait_for_job(r.json()["id"], owner_headers)
    assert final["status"] == "completed"
    assert final["created_count"] == 0, f"expected 0 created on re-run, got {final['created_count']}"
    assert final["updated_count"] > 0

    after = requests.get(f"{API}/properties", params={"territory_id": tid}, headers=owner_headers, timeout=15).json()
    assert len(after) == n_before, "property count changed on re-run (not idempotent)"


def test_import_forbidden_for_sales(sales_headers, territory):
    r = requests.post(f"{API}/territories/{territory['id']}/import", json={"max_records": 5}, headers=sales_headers, timeout=15)
    assert r.status_code == 403


# ---------- Properties: list, geojson, detail ----------
def test_properties_geojson(owner_headers, imported_territory):
    tid = imported_territory["territory_id"]
    r = requests.get(f"{API}/properties/geojson", params={"territory_id": tid}, headers=owner_headers, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["type"] == "FeatureCollection"
    assert len(d["features"]) > 0
    f0 = d["features"][0]
    assert f0["geometry"]["type"] == "Point"
    assert "do_not_knock" in f0["properties"]


def test_property_detail(owner_headers, imported_territory):
    tid = imported_territory["territory_id"]
    props = requests.get(f"{API}/properties", params={"territory_id": tid}, headers=owner_headers, timeout=15).json()
    pid = props[0]["id"]
    r = requests.get(f"{API}/properties/{pid}", headers=owner_headers, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == pid
    assert "contacts" in d and "visits" in d
    # sample data includes an owner contact
    assert len(d["contacts"]) >= 1
    assert d["contacts"][0]["kind"] == "owner"


# ---------- Do Not Knock (sales allowed) ----------
def test_sales_can_toggle_dnk(sales_headers, owner_headers, imported_territory):
    tid = imported_territory["territory_id"]
    props = requests.get(f"{API}/properties", params={"territory_id": tid}, headers=owner_headers, timeout=15).json()
    pid = props[0]["id"]
    r = requests.patch(f"{API}/properties/{pid}", json={"do_not_knock": True, "do_not_knock_reason": "test"}, headers=sales_headers, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["do_not_knock"] is True
    # geojson reflects DNK
    gj = requests.get(f"{API}/properties/geojson", params={"territory_id": tid}, headers=owner_headers, timeout=15).json()
    hit = next(f for f in gj["features"] if f["properties"]["id"] == pid)
    assert hit["properties"]["do_not_knock"] is True
    # cleanup: reset
    requests.patch(f"{API}/properties/{pid}", json={"do_not_knock": False}, headers=sales_headers, timeout=15)


# ---------- Visits + Convert to lead ----------
def test_visit_with_dnk_outcome_flips_property(sales_headers, owner_headers, imported_territory):
    tid = imported_territory["territory_id"]
    props = requests.get(f"{API}/properties", params={"territory_id": tid}, headers=owner_headers, timeout=15).json()
    pid = props[1]["id"]
    r = requests.post(f"{API}/properties/{pid}/visits", json={"outcome": "do_not_knock", "notes": "TEST dnk visit"}, headers=sales_headers, timeout=15)
    assert r.status_code == 201, r.text
    assert r.json()["outcome"] == "do_not_knock"
    detail = requests.get(f"{API}/properties/{pid}", headers=owner_headers, timeout=15).json()
    assert detail["do_not_knock"] is True
    assert any(v["outcome"] == "do_not_knock" for v in detail["visits"])


def test_convert_to_lead_falls_back_to_owner_name(sales_headers, owner_headers, imported_territory):
    tid = imported_territory["territory_id"]
    props = requests.get(f"{API}/properties", params={"territory_id": tid}, headers=owner_headers, timeout=15).json()
    pid = props[2]["id"]
    # blank name -> should use owner contact name
    detail_before = requests.get(f"{API}/properties/{pid}", headers=owner_headers, timeout=15).json()
    owner_name = detail_before["contacts"][0]["name"] if detail_before["contacts"] else None

    r = requests.post(f"{API}/properties/{pid}/convert-to-lead", json={"name": "  ", "notes": "TEST lead"}, headers=sales_headers, timeout=15)
    assert r.status_code == 201, r.text
    lead = r.json()
    if owner_name:
        assert lead["name"] == owner_name
    assert lead["property_id"] == pid

    # Lead appears in /leads (checked as owner; sales visibility is now strict/assignment-based)
    leads = requests.get(f"{API}/leads", headers=owner_headers, timeout=15).json()
    assert any(l["id"] == lead["id"] for l in leads)


# ---------- Change password ----------
def test_change_password_wrong_current_400(owner_headers):
    r = requests.post(f"{API}/auth/change-password", json={"current_password": "definitelyWrong123", "new_password": "NewPass12345"}, headers=owner_headers, timeout=15)
    assert r.status_code == 400


def test_change_password_roundtrip_reverts():
    new_pwd = f"TmpPass_{uuid.uuid4().hex[:6]}"
    # login fresh (don't reuse module fixture — we'll re-login after change)
    r = requests.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=15)
    assert r.status_code == 200
    tok = r.json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    r = requests.post(f"{API}/auth/change-password", json={"current_password": OWNER_PASSWORD, "new_password": new_pwd}, headers=h, timeout=15)
    assert r.status_code == 200, r.text

    # login with new
    r = requests.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": new_pwd}, timeout=15)
    assert r.status_code == 200, "login with new password failed"
    tok2 = r.json()["access_token"]

    # revert
    h2 = {"Authorization": f"Bearer {tok2}"}
    r = requests.post(f"{API}/auth/change-password", json={"current_password": new_pwd, "new_password": OWNER_PASSWORD}, headers=h2, timeout=15)
    assert r.status_code == 200

    # verify original works again
    r = requests.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=15)
    assert r.status_code == 200, "REVERT FAILED - owner password not restored!"


# ---------- Territory delete preserves properties ----------
def test_delete_territory_preserves_properties(owner_headers, imported_territory):
    tid = imported_territory["territory_id"]
    props_before = requests.get(f"{API}/properties", params={"territory_id": tid}, headers=owner_headers, timeout=15).json()
    assert len(props_before) > 0
    kept_ids = [p["id"] for p in props_before]

    # sales cannot delete
    # (skip creating another sales call — just verify owner delete)
    r = requests.delete(f"{API}/territories/{tid}", headers=owner_headers, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("properties_preserved") is True

    # Properties still exist but territory_id is null
    for pid in kept_ids[:3]:
        d = requests.get(f"{API}/properties/{pid}", headers=owner_headers, timeout=15)
        assert d.status_code == 200
        assert d.json()["territory_id"] is None
