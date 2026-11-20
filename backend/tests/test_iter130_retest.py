"""Iteration 130: retest of iter129 fixes - sales cost gating on material-plan, assignment checks, UUID parsing."""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
SALES_BK = ("sales_bk@example.com", "SalesBk#2026")


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
def sales_id(sales):
    return requests.get(f"{API}/auth/me", headers=sales, timeout=20).json()["id"]


@pytest.fixture(scope="module")
def jobs_pair(owner, sales_id):
    """Pick a job with materials, assign it to sales_bk; another job not assigned to sales_bk. Restore after."""
    jobs = requests.get(f"{API}/jobs", headers=owner, timeout=60).json()
    mine = next((j for j in jobs if j["status"] not in ("completed", "cancelled")
                 and requests.get(f"{API}/jobs/{j['id']}/material-plan", headers=owner, timeout=30).json().get("materials")), None)
    if not mine:
        pytest.skip("need a job with materials")
    other = next((j for j in jobs if j["id"] != mine["id"] and j.get("assigned_user_id") != sales_id), None)
    if not other:
        pytest.skip("need another job")
    orig = requests.get(f"{API}/jobs/{mine['id']}", headers=owner, timeout=20).json().get("assigned_user_id")
    r = requests.put(f"{API}/jobs/{mine['id']}/assign", json={"user_id": sales_id}, headers=owner, timeout=20)
    assert r.status_code == 200, r.text
    yield mine["id"], other["id"]
    requests.put(f"{API}/jobs/{mine['id']}/assign", json={"user_id": orig}, headers=owner, timeout=20)


def _rows(body):
    if isinstance(body, list):
        return body
    for k in ("materials", "rows", "items"):
        if k in body:
            return body[k]
    return []


# Cost gating on the material plan
class TestSalesCostGating:
    def test_owner_sees_best_cost(self, owner, jobs_pair):
        rows = _rows(requests.get(f"{API}/jobs/{jobs_pair[0]}/material-plan", headers=owner, timeout=30).json())
        assert rows and all("best_known_cost" in r for r in rows)

    def test_sales_no_best_cost_on_own_job(self, sales, jobs_pair):
        r = requests.get(f"{API}/jobs/{jobs_pair[0]}/material-plan", headers=sales, timeout=30)
        assert r.status_code == 200, r.text
        rows = _rows(r.json())
        assert rows
        assert all("best_known_cost" not in x for x in rows)
        assert "best_known_cost" not in r.text

    def test_sales_own_job_materials_ok(self, sales, jobs_pair):
        assert requests.get(f"{API}/jobs/{jobs_pair[0]}/materials", headers=sales, timeout=30).status_code == 200

    def test_sales_other_job_forbidden(self, sales, jobs_pair):
        assert requests.get(f"{API}/jobs/{jobs_pair[1]}/material-plan", headers=sales, timeout=30).status_code == 403
        assert requests.get(f"{API}/jobs/{jobs_pair[1]}/materials", headers=sales, timeout=30).status_code == 403


# Non-UUID ids
class TestUuidParsing:
    def test_crew_put_delete_bad(self, owner):
        assert requests.put(f"{API}/crews/not-a-uuid", json={"name": "TEST_x"}, headers=owner, timeout=20).status_code == 404
        assert requests.delete(f"{API}/crews/not-a-uuid", headers=owner, timeout=20).status_code == 404

    def test_job_get_bad(self, owner):
        assert requests.get(f"{API}/jobs/not-a-uuid", headers=owner, timeout=20).status_code == 404

    def test_patch_crew_garbage(self, owner, jobs_pair):
        r = requests.patch(f"{API}/jobs/{jobs_pair[1]}", json={"crew_id": "garbage"}, headers=owner, timeout=20)
        assert r.status_code == 422, r.text

    def test_assign_bad_user(self, owner, jobs_pair):
        r = requests.put(f"{API}/jobs/{jobs_pair[1]}/assign", json={"user_id": "not-a-uuid"}, headers=owner, timeout=20)
        assert r.status_code == 422, r.text

    def test_bad_job_id_other_endpoints(self, owner):
        """Extra: non-UUID job id on other job endpoints should not 500."""
        codes = {
            "assign": requests.put(f"{API}/jobs/not-a-uuid/assign", json={"user_id": None}, headers=owner, timeout=20).status_code,
            "patch": requests.patch(f"{API}/jobs/not-a-uuid", json={"notes": "x"}, headers=owner, timeout=20).status_code,
            "plan": requests.get(f"{API}/jobs/not-a-uuid/material-plan", headers=owner, timeout=20).status_code,
            "materials": requests.get(f"{API}/jobs/not-a-uuid/materials", headers=owner, timeout=20).status_code,
        }
        print(codes)
        assert all(c < 500 for c in codes.values()), codes
