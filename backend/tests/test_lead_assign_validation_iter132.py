"""Iteration 132: Field-app (and Office) lead assignment validation, audit, Office/Field sync, no partial updates."""
import os
import uuid

import pytest
import requests

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
SALES_BK = ("sales_bk@example.com", "SalesBk#2026")
PW = "TestPass#2026"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def owner():
    return _login(*OWNER)


@pytest.fixture(scope="module")
def sales():
    return _login(*SALES_BK)


@pytest.fixture(scope="module")
def users(owner):
    h = uuid.uuid4().hex[:8]
    out = {}
    for key in ("active", "inactive"):
        r = requests.post(f"{API}/users", json={"email": f"test_lassign_{key}_{h}@example.com", "full_name": f"TEST LA {key} {h}",
                                                "password": PW, "role": "sales"}, headers=owner, timeout=20)
        assert r.status_code == 201, r.text
        out[key] = r.json()
    assert requests.patch(f"{API}/users/{out['inactive']['id']}", json={"is_active": False}, headers=owner, timeout=20).status_code == 200
    yield out
    for u in out.values():
        requests.delete(f"{API}/users/{u['id']}", headers=owner, timeout=20)


@pytest.fixture(scope="module")
def lead(owner):
    r = requests.post(f"{API}/properties", json={"address_line1": f"{uuid.uuid4().hex[:6]} TEST_Assign Way", "city": "Austin", "state": "TX",
                                                 "zip_code": "78701", "latitude": 30.27, "longitude": -97.74}, headers=owner, timeout=20)
    assert r.status_code in (200, 201), r.text
    r = requests.post(f"{API}/properties/{r.json()['id']}/convert-to-lead", json={"name": "TEST_AssignLead"}, headers=owner, timeout=20)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _assigned(owner, lead_id):
    return requests.get(f"{API}/leads/{lead_id}", headers=owner, timeout=20).json().get("assigned_user_id")


@pytest.mark.parametrize("path", ["mobile", "office"])
def test_invalid_assignees_rejected_and_lead_unchanged(owner, users, lead, path):
    before = _assigned(owner, lead["id"])
    for bad in (users["inactive"]["id"], str(uuid.uuid4()), "not-a-uuid", "12345"):
        r = (requests.post(f"{API}/mobile/leads/{lead['id']}/assign", json={"user_id": bad}, headers=owner, timeout=20) if path == "mobile"
             else requests.put(f"{API}/leads/{lead['id']}/assign", json={"user_id": bad}, headers=owner, timeout=20))
        assert r.status_code == 422, f"{path} {bad} -> {r.status_code} {r.text[:200]}"
        assert _assigned(owner, lead["id"]) == before


def test_malformed_lead_id_404(owner, users):
    r = requests.post(f"{API}/mobile/leads/not-a-uuid/assign", json={"user_id": users["active"]["id"]}, headers=owner, timeout=20)
    assert r.status_code == 404
    r = requests.put(f"{API}/leads/not-a-uuid/assign", json={"user_id": users["active"]["id"]}, headers=owner, timeout=20)
    assert r.status_code == 404


def test_sales_cannot_assign(sales, users, lead, owner):
    before = _assigned(owner, lead["id"])
    r = requests.post(f"{API}/mobile/leads/{lead['id']}/assign", json={"user_id": users["active"]["id"]}, headers=sales, timeout=20)
    assert r.status_code == 403
    assert _assigned(owner, lead["id"]) == before


def test_valid_assign_audited_and_synced(owner, users, lead):
    uid = users["active"]["id"]
    r = requests.post(f"{API}/mobile/leads/{lead['id']}/assign", json={"user_id": uid}, headers=owner, timeout=20)
    assert r.status_code == 200 and r.json()["assigned_user_id"] == uid
    # Office sees the Field change
    assert _assigned(owner, lead["id"]) == uid
    # Field sees it; the assignee can open the lead in both apps
    ah = _login(users["active"]["email"], PW)
    assert requests.get(f"{API}/leads/{lead['id']}", headers=ah, timeout=20).status_code == 200
    assert any(x["id"] == lead["id"] for x in requests.get(f"{API}/mobile/leads", headers=ah, timeout=30).json())
    logs = requests.get(f"{API}/audit", params={"action": "lead.assign", "limit": 200}, headers=owner, timeout=20)
    assert logs.status_code == 200
    assert any(i["entity_id"] == lead["id"] and (i.get("detail") or {}).get("via") == "mobile"
               and (i.get("detail") or {}).get("assigned_user_id") == uid for i in logs.json()["items"])
    # Office change is visible to the Field app
    r = requests.put(f"{API}/leads/{lead['id']}/assign", json={"user_id": None}, headers=owner, timeout=20)
    assert r.status_code == 200
    assert all(x["id"] != lead["id"] for x in requests.get(f"{API}/mobile/leads", headers=ah, timeout=30).json())
