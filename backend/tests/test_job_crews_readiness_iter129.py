"""Iteration 129: Crews CRUD, job crew/manager assignment, readiness, schedule validation, quote->job manager."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
SALES1 = ("sales1_38f545f9@example.com", "Sales1#2026")
SALES1_ID = "d47710df-133f-4436-9ffd-b61a05a0060f"
SALES_BK = ("sales_bk@example.com", "SalesBk#2026")
CREW_A = "76dc5342-12e3-4809-bd5b-156ed4f99171"


def _short_job(owner):
    """An active job whose readiness reports a material shortage (picked dynamically)."""
    for j in requests.get(f"{API}/jobs", headers=owner, timeout=60).json():
        if any(x["code"] == "materials" for x in (j.get("readiness") or {}).get("reasons", [])):
            return j["id"]
    pytest.skip("no job with a material shortage")


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def owner():
    return _login(*OWNER)


@pytest.fixture(scope="module")
def sales():
    return _login(*SALES1)


@pytest.fixture(scope="module")
def sales_bk():
    return _login(*SALES_BK)


@pytest.fixture(scope="module")
def created():
    return {"crews": [], "jobs_restore": {}}


@pytest.fixture(scope="module", autouse=True)
def cleanup(owner, created):
    yield
    for jid, orig in created["jobs_restore"].items():
        requests.patch(f"{API}/jobs/{jid}", json=orig, headers=owner, timeout=20)
    for cid in created["crews"]:
        requests.delete(f"{API}/crews/{cid}", headers=owner, timeout=20)


def _any_job(owner, status_in=("created", "pending", "scheduled")):
    jobs = requests.get(f"{API}/jobs", headers=owner, timeout=30).json()
    for j in jobs:
        if j["status"] in status_in:
            return j
    pytest.skip("no job available")


def _snapshot(j):
    return {"crew_id": j.get("crew_id"), "scheduled_start": j.get("scheduled_start"), "scheduled_end": j.get("scheduled_end")}


# ---- Crews CRUD / RBAC ----
class TestCrews:
    def test_list_and_rbac(self, owner, sales):
        r = requests.get(f"{API}/crews", headers=owner, timeout=20)
        assert r.status_code == 200
        names = [c["name"] for c in r.json()]
        assert "Crew A" in names
        ca = next(c for c in r.json() if c["id"] == CREW_A)
        assert ca["job_count"] >= 1
        assert requests.get(f"{API}/crews", headers=sales, timeout=20).status_code == 403
        assert requests.post(f"{API}/crews", json={"name": "TEST_x"}, headers=sales, timeout=20).status_code == 403

    def test_create_duplicate_rename_delete(self, owner, created):
        name = f"TEST_Crew_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/crews", json={"name": name}, headers=owner, timeout=20)
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        created["crews"].append(cid)
        assert r.json()["active"] is True
        # duplicate case-insensitive
        r2 = requests.post(f"{API}/crews", json={"name": name.upper()}, headers=owner, timeout=20)
        assert r2.status_code == 409
        # empty
        assert requests.post(f"{API}/crews", json={"name": "  "}, headers=owner, timeout=20).status_code == 422
        # rename to crew A (case-insens) -> 409
        assert requests.put(f"{API}/crews/{cid}", json={"name": "crew a"}, headers=owner, timeout=20).status_code == 409
        # delete unused ok
        d = requests.delete(f"{API}/crews/{cid}", headers=owner, timeout=20)
        assert d.status_code == 200
        created["crews"].remove(cid)
        lst = requests.get(f"{API}/crews", headers=owner, timeout=20).json()
        assert all(c["id"] != cid for c in lst)

    def test_delete_used_crew_409(self, owner):
        assert requests.delete(f"{API}/crews/{CREW_A}", headers=owner, timeout=20).status_code == 409

    def test_unknown_and_invalid_crew_ids(self, owner):
        assert requests.put(f"{API}/crews/{uuid.uuid4()}", json={"notes": "x"}, headers=owner, timeout=20).status_code == 404
        r = requests.put(f"{API}/crews/not-a-uuid", json={"notes": "x"}, headers=owner, timeout=20)
        assert r.status_code in (404, 422), f"invalid uuid -> {r.status_code}"


# ---- Job crew assignment / readiness ----
class TestJobCrew:
    def test_assign_rename_sync_deactivate(self, owner, created):
        j = _any_job(owner)
        created["jobs_restore"].setdefault(j["id"], _snapshot(j))
        name = f"TEST_CrewJ_{uuid.uuid4().hex[:6]}"
        cid = requests.post(f"{API}/crews", json={"name": name}, headers=owner, timeout=20).json()["id"]
        created["crews"].append(cid)
        r = requests.patch(f"{API}/jobs/{j['id']}", json={"crew_id": cid}, headers=owner, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["crew_id"] == cid and d["crew_name"] == name and d["assigned_to"] == name
        # rename syncs assigned_to
        new = name + "_R"
        assert requests.put(f"{API}/crews/{cid}", json={"name": new}, headers=owner, timeout=20).status_code == 200
        g = requests.get(f"{API}/jobs/{j['id']}", headers=owner, timeout=20).json()
        assert g["assigned_to"] == new and g["crew_name"] == new
        # delete used -> 409
        assert requests.delete(f"{API}/crews/{cid}", headers=owner, timeout=20).status_code == 409
        # deactivate: job keeps it, re-patch same crew ok
        assert requests.put(f"{API}/crews/{cid}", json={"active": False}, headers=owner, timeout=20).json()["active"] is False
        g = requests.get(f"{API}/jobs/{j['id']}", headers=owner, timeout=20).json()
        assert g["crew_id"] == cid and g["crew_active"] is False
        assert requests.patch(f"{API}/jobs/{j['id']}", json={"crew_id": cid}, headers=owner, timeout=20).status_code == 200
        # other job can't newly get an inactive crew
        other = next(x for x in requests.get(f"{API}/jobs", headers=owner, timeout=30).json()
                     if x["id"] != j["id"] and x["status"] in ("created", "pending", "scheduled"))
        created["jobs_restore"].setdefault(other["id"], _snapshot(other))
        r = requests.patch(f"{API}/jobs/{other['id']}", json={"crew_id": cid}, headers=owner, timeout=20)
        assert r.status_code == 422
        # clear
        r = requests.patch(f"{API}/jobs/{j['id']}", json={"crew_id": None}, headers=owner, timeout=20)
        assert r.status_code == 200 and r.json()["crew_id"] is None and r.json()["assigned_to"] is None
        assert any(x["code"] == "crew" for x in r.json()["readiness"]["reasons"])

    def test_invalid_crew_id_patch(self, owner, created):
        j = _any_job(owner)
        created["jobs_restore"].setdefault(j["id"], _snapshot(j))
        assert requests.patch(f"{API}/jobs/{j['id']}", json={"crew_id": str(uuid.uuid4())}, headers=owner, timeout=20).status_code == 422
        r = requests.patch(f"{API}/jobs/{j['id']}", json={"crew_id": "garbage"}, headers=owner, timeout=20)
        assert r.status_code == 422, f"garbage crew_id -> {r.status_code} {r.text[:200]}"

    def test_legacy_assigned_to(self, owner, created):
        j = _any_job(owner)
        created["jobs_restore"].setdefault(j["id"], _snapshot(j))
        r = requests.patch(f"{API}/jobs/{j['id']}", json={"assigned_to": "crew a"}, headers=owner, timeout=20)
        assert r.status_code == 200 and r.json()["crew_id"] == CREW_A and r.json()["assigned_to"] == "Crew A"
        name = f"TEST_Legacy_{uuid.uuid4().hex[:6]}"
        r = requests.patch(f"{API}/jobs/{j['id']}", json={"assigned_to": name}, headers=owner, timeout=20)
        assert r.status_code == 200 and r.json()["crew_name"] == name
        created["crews"].append(r.json()["crew_id"])
        requests.patch(f"{API}/jobs/{j['id']}", json={"crew_id": None}, headers=owner, timeout=20)

    def test_readiness_states(self, owner, created):
        j = _any_job(owner)
        created["jobs_restore"].setdefault(j["id"], _snapshot(j))
        r = requests.patch(f"{API}/jobs/{j['id']}", json={"crew_id": None, "scheduled_start": None, "scheduled_end": None}, headers=owner, timeout=20)
        codes = {x["code"] for x in r.json()["readiness"]["reasons"]}
        assert {"schedule", "crew"} <= codes and r.json()["readiness"]["ready"] is False
        r = requests.patch(f"{API}/jobs/{j['id']}", json={"crew_id": CREW_A, "scheduled_start": "2026-03-10T12:00:00Z", "scheduled_end": "2026-03-12T12:00:00Z"}, headers=owner, timeout=20)
        d = r.json()
        codes = {x["code"] for x in d["readiness"]["reasons"]}
        assert "schedule" not in codes and "crew" not in codes
        plan = requests.get(f"{API}/jobs/{j['id']}/material-plan", headers=owner, timeout=30).json()
        short = sum(float(m.get("shortage") or 0) for m in plan["materials"])
        assert d["readiness"]["ready"] == (short <= 0)
        assert d["scheduled_start"].startswith("2026-03-10") and d["scheduled_end"].startswith("2026-03-12")
        # list view consistent
        lst = requests.get(f"{API}/jobs", headers=owner, timeout=30).json()
        row = next(x for x in lst if x["id"] == j["id"])
        assert row["readiness"] == d["readiness"] and row["crew_name"] == "Crew A" and "scheduled_end" in row

    def test_short_job_materials_reason(self, owner):
        d = requests.get(f"{API}/jobs/{_short_job(owner)}", headers=owner, timeout=20).json()
        codes = {x["code"] for x in d["readiness"]["reasons"]}
        assert "materials" in codes, d["readiness"]

    def test_closed_job_ready_null(self, owner):
        lst = requests.get(f"{API}/jobs", headers=owner, timeout=30).json()
        closed = [x for x in lst if x["status"] in ("completed", "cancelled")]
        if not closed:
            pytest.skip("no closed jobs")
        assert all(x["readiness"]["ready"] is None for x in closed)


# ---- Schedule validation ----
class TestSchedule:
    def test_inverted_dates_422(self, owner, created):
        j = _any_job(owner)
        created["jobs_restore"].setdefault(j["id"], _snapshot(j))
        r = requests.patch(f"{API}/jobs/{j['id']}", json={"scheduled_start": "2026-04-10T12:00:00Z", "scheduled_end": "2026-04-08T12:00:00Z"}, headers=owner, timeout=20)
        assert r.status_code == 422 and "end date" in r.text
        # same day ok
        r = requests.patch(f"{API}/jobs/{j['id']}", json={"scheduled_start": "2026-04-10T12:00:00Z", "scheduled_end": "2026-04-10T12:00:00Z"}, headers=owner, timeout=20)
        assert r.status_code == 200
        # only end before existing start -> 422
        r = requests.patch(f"{API}/jobs/{j['id']}", json={"scheduled_end": "2026-04-01T12:00:00Z"}, headers=owner, timeout=20)
        assert r.status_code == 422

    def test_mobile_inverted_422(self, owner, created):
        j = _any_job(owner)
        created["jobs_restore"].setdefault(j["id"], _snapshot(j))
        r = requests.patch(f"{API}/mobile/jobs/{j['id']}", json={"scheduled_start": "2026-05-10T12:00:00Z", "scheduled_end": "2026-05-01T12:00:00Z"}, headers=owner, timeout=20)
        assert r.status_code == 422, r.text

    def test_status_only_patch_skips_date_validation(self, owner):
        j = _any_job(owner)
        r = requests.patch(f"{API}/jobs/{j['id']}", json={"status": j["status"]}, headers=owner, timeout=20)
        assert r.status_code == 200, r.text
        r = requests.patch(f"{API}/mobile/jobs/{j['id']}", json={"status": j["status"]}, headers=owner, timeout=20)
        assert r.status_code == 200, r.text


# ---- Mobile assign + quote->job manager ----
class TestManager:
    def test_mobile_assign_validation(self, owner):
        j = _any_job(owner)
        orig = j.get("assigned_user_id")
        for bad in ("not-a-uuid", str(uuid.uuid4())):
            r = requests.post(f"{API}/mobile/jobs/{j['id']}/assign", json={"user_id": bad}, headers=owner, timeout=20)
            assert r.status_code == 422, f"{bad} -> {r.status_code}"
        r = requests.post(f"{API}/mobile/jobs/{j['id']}/assign", json={"user_id": SALES1_ID}, headers=owner, timeout=20)
        assert r.status_code == 200 and r.json()["assigned_user_id"] == SALES1_ID
        requests.post(f"{API}/mobile/jobs/{j['id']}/assign", json={"user_id": orig}, headers=owner, timeout=20)

    def test_office_assign_invalid_uuid(self, owner):
        j = _any_job(owner)
        r = requests.put(f"{API}/jobs/{j['id']}/assign", json={"user_id": "not-a-uuid"}, headers=owner, timeout=20)
        assert r.status_code == 422, f"office assign invalid uuid -> {r.status_code}"

    def test_quote_accept_job_manager(self, owner, sales, sales_bk):
        r = requests.post(f"{API}/properties", json={"address_line1": "1 TEST_Crew St", "city": "Austin", "state": "TX", "zip_code": "78701", "latitude": 30.2, "longitude": -97.7}, headers=owner, timeout=20)
        pid = r.json()["id"]
        lead = requests.post(f"{API}/properties/{pid}/convert-to-lead", json={"name": "TEST_CrewLead"}, headers=owner, timeout=20).json()
        assert requests.put(f"{API}/leads/{lead['id']}/assign", json={"user_id": SALES1_ID}, headers=owner, timeout=20).status_code == 200
        cust = requests.post(f"{API}/customers/from-lead/{lead['id']}", headers=owner, timeout=20).json()
        est = requests.post(f"{API}/estimates", json={"lead_id": lead["id"], "customer_id": cust["id"], "tax_rate": 0, "items": [{"description": "Roof", "quantity": 1, "unit": "ea", "unit_price": 100}]}, headers=owner, timeout=20).json()
        quo = requests.post(f"{API}/quotes", json={"estimate_id": est["id"]}, headers=owner, timeout=20).json()
        acc = requests.post(f"{API}/quotes/{quo['id']}/accept", json={"acceptance_name": "TEST_Cust"}, headers=owner, timeout=20)
        assert acc.status_code == 200, acc.text
        jid = acc.json()["job_id"]
        d = requests.get(f"{API}/jobs/{jid}", headers=owner, timeout=20).json()
        assert d["assigned_user_id"] == SALES1_ID
        assert d["readiness"]["ready"] is False
        assert requests.get(f"{API}/jobs/{jid}", headers=sales, timeout=20).status_code == 200
        assert any(x["id"] == jid for x in requests.get(f"{API}/jobs", headers=sales, timeout=30).json())
        assert requests.get(f"{API}/jobs/{jid}", headers=sales_bk, timeout=20).status_code == 403
        # sales cannot patch crew
        assert requests.patch(f"{API}/jobs/{jid}", json={"crew_id": CREW_A}, headers=sales, timeout=20).status_code == 403
        print("QUOTE_JOB_ID", jid)
