# UX Round 1: dashboard attention + jobs list enrichment + RBAC (read-only tests)
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
SALES = {"email": "sales_bk@example.com", "password": "SalesBk#2026"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {creds['email']}: {r.status_code}")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    s.user = r.json().get("user", {})
    return s


@pytest.fixture(scope="module")
def owner():
    return _login(OWNER)


@pytest.fixture(scope="module")
def sales():
    return _login(SALES)


# Attention dashboard
class TestAttention:
    def test_owner_shape(self, owner):
        r = owner.get(f"{BASE_URL}/api/dashboard/attention", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("follow_ups", "inspections", "proposals", "jobs"):
            assert isinstance(d[k]["count"], int)
            assert isinstance(d[k]["items"], list)
            assert len(d[k]["items"]) <= 6
            for it in d[k]["items"]:
                assert it["link"].startswith("/")
        assert "total" in d["proposals"]
        m = d["money"]
        assert m is not None
        for k in ("open_count", "open_total", "overdue_count", "overdue_total", "items"):
            assert k in m
        assert m["overdue_count"] <= m["open_count"]

    def test_owner_money_matches_invoices(self, owner):
        d = owner.get(f"{BASE_URL}/api/dashboard/attention", timeout=30).json()
        invs = owner.get(f"{BASE_URL}/api/invoices", timeout=30).json()
        issued = [i for i in invs if i["status"] == "issued"]
        assert d["money"]["open_count"] == len(issued)
        assert abs(d["money"]["open_total"] - sum(float(i["total"] or 0) for i in issued)) < 0.02

    def test_owner_proposals_match_quotes(self, owner):
        # Sales follow-up round: the card lists draft/sent proposals on open leads that need attention.
        d = owner.get(f"{BASE_URL}/api/dashboard/attention", timeout=30).json()
        qs = {q["id"]: q for q in owner.get(f"{BASE_URL}/api/quotes", timeout=30).json()}
        assert d["proposals"]["count"] >= len(d["proposals"]["items"])
        for p in d["proposals"]["items"]:
            assert qs[p["id"]]["status"] in ("draft", "sent") and p["reason"]

    def test_sales_scoped(self, sales):
        r = sales.get(f"{BASE_URL}/api/dashboard/attention", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["money"] is None
        jobs = sales.get(f"{BASE_URL}/api/jobs", timeout=30).json()
        active = [j for j in jobs if j["status"] in ("scheduled", "in_progress")]
        assert d["jobs"]["count"] == len(active)

    def test_unauth(self):
        r = requests.get(f"{BASE_URL}/api/dashboard/attention", timeout=30)
        assert r.status_code in (401, 403)


# Jobs list enrichment
class TestJobsList:
    def test_fields(self, owner):
        r = owner.get(f"{BASE_URL}/api/jobs", timeout=60)
        assert r.status_code == 200, r.text
        jobs = r.json()
        assert isinstance(jobs, list)
        for j in jobs:
            for k in ("scheduled_start", "assigned_to", "customer_name", "property_address", "material_status"):
                assert k in j, f"missing {k}"
            assert j["material_status"] in ("ready", "short", "none")

    def test_sales_only_assigned(self, sales):
        r = sales.get(f"{BASE_URL}/api/jobs", timeout=60)
        assert r.status_code == 200
        uid = sales.user.get("id")
        for j in r.json():
            assert j.get("assigned_user_id") == uid


# Regression of APIs behind moved screens
class TestRegressionApis:
    @pytest.mark.parametrize("path", ["/api/quotes", "/api/invoices", "/api/dashboard/purchasing",
                                      "/api/admin/backups/health", "/api/version", "/api/suppliers"])
    def test_owner_reads(self, owner, path):
        r = owner.get(f"{BASE_URL}{path}", timeout=60)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
