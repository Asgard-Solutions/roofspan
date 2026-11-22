"""Iteration 131: job closeout - assignable type-ahead (active only), job assign validation, sales PO cost redaction."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
SALES_BK = ("sales_bk@example.com", "SalesBk#2026")
SALES2 = ("sales2_7ad4f5cd@example.com", "Sales2#2026")
PW = "TestPw#2026x"


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
def sales2():
    return _login(*SALES2)


@pytest.fixture(scope="module")
def sales_id(sales):
    return requests.get(f"{API}/auth/me", headers=sales, timeout=20).json()["id"]


@pytest.fixture(scope="module")
def made_users(owner):
    """office + admin + inactive test users (cleanup-pattern emails); deleted after module."""
    h = uuid.uuid4().hex[:8]
    out = {}
    for key, role in (("office", "office"), ("admin", "administrator"), ("inactive", "office")):
        email = f"test_{key}_{h}@example.com"
        r = requests.post(f"{API}/users", json={"email": email, "full_name": f"TEST {key} Zq{h}", "password": PW, "role": role},
                          headers=owner, timeout=20)
        assert r.status_code == 201, r.text
        out[key] = r.json()
    r = requests.patch(f"{API}/users/{out['inactive']['id']}", json={"is_active": False}, headers=owner, timeout=20)
    assert r.status_code == 200 and r.json()["is_active"] is False
    out["hex"] = h
    yield out
    for key in ("office", "admin", "inactive"):
        requests.delete(f"{API}/users/{out[key]['id']}", headers=owner, timeout=20)


@pytest.fixture(scope="module")
def po_job(owner, sales_id):
    """A job with a PO (unassigned), temporarily assigned to sales_bk; restored after."""
    pos = requests.get(f"{API}/purchase-orders", headers=owner, timeout=60).json()
    jobs = {j["id"]: j for j in requests.get(f"{API}/jobs", headers=owner, timeout=60).json()}
    pick = None
    for p in pos:
        j = jobs.get(p.get("job_id"))
        if j and not j.get("assigned_user_id") and p.get("total") and p.get("items"):
            pick = (j["id"], p["id"])
            break
    if not pick:
        pytest.skip("no job with a costed PO")
    r = requests.put(f"{API}/jobs/{pick[0]}/assign", json={"user_id": sales_id}, headers=owner, timeout=20)
    assert r.status_code == 200, r.text
    other_po = next(p["id"] for p in pos if p.get("job_id") != pick[0]
                    and not (jobs.get(p.get("job_id")) or {}).get("assigned_user_id"))
    yield pick[0], pick[1], other_po
    requests.put(f"{API}/jobs/{pick[0]}/assign", json={"user_id": None}, headers=owner, timeout=20)


# ---- Assignable type-ahead ----
class TestAssignable:
    def test_sales_forbidden(self, sales):
        assert requests.get(f"{API}/users/assignable", headers=sales, timeout=20).status_code == 403

    def test_search_active_only(self, owner, made_users):
        h = made_users["hex"]
        r = requests.get(f"{API}/users/assignable", params={"q": f"zq{h}"}, headers=owner, timeout=20)
        assert r.status_code == 200
        ids = {u["id"] for u in r.json()}
        assert made_users["office"]["id"] in ids and made_users["admin"]["id"] in ids
        assert made_users["inactive"]["id"] not in ids
        assert all(u["is_active"] for u in r.json())
        # email, upper-case
        r = requests.get(f"{API}/users/assignable", params={"q": f"TEST_INACTIVE_{h}".upper()}, headers=owner, timeout=20)
        assert r.json() == []
        r = requests.get(f"{API}/users/assignable", params={"q": f"TEST_OFFICE_{h}"}, headers=owner, timeout=20)
        assert [u["id"] for u in r.json()] == [made_users["office"]["id"]]

    def test_no_q_all_active_and_limit(self, owner, made_users):
        r = requests.get(f"{API}/users/assignable", headers=owner, timeout=20)
        ids = {u["id"] for u in r.json()}
        emails = {u["email"] for u in r.json()}
        assert {"pjacobsen@asgardsolution.io", "sales_bk@example.com"} <= emails
        assert made_users["inactive"]["id"] not in ids
        r = requests.get(f"{API}/users/assignable", params={"limit": 2}, headers=owner, timeout=20)
        assert r.status_code == 200 and len(r.json()) == 2
        assert requests.get(f"{API}/users/assignable", params={"limit": 0}, headers=owner, timeout=20).status_code == 422

    def test_office_can_search(self, made_users):
        h = _login(made_users["office"]["email"], PW)
        r = requests.get(f"{API}/users/assignable", params={"q": "sales_bk"}, headers=h, timeout=20)
        assert r.status_code == 200 and [u["email"] for u in r.json()] == ["sales_bk@example.com"]

    def test_wildcard_chars(self, owner):
        r = requests.get(f"{API}/users/assignable", params={"q": "%"}, headers=owner, timeout=20)
        print("q=% returns", len(r.json()))
        assert r.status_code == 200


# ---- Job assign validation ----
class TestAssign:
    def test_inactive_user_422(self, owner, made_users, po_job):
        jid = po_job[0]
        r = requests.put(f"{API}/jobs/{jid}/assign", json={"user_id": made_users["inactive"]["id"]}, headers=owner, timeout=20)
        assert r.status_code == 422
        r = requests.put(f"{API}/jobs/{jid}/assign", json={"user_id": str(uuid.uuid4())}, headers=owner, timeout=20)
        assert r.status_code == 422
        r = requests.post(f"{API}/mobile/jobs/{jid}/assign", json={"user_id": made_users["inactive"]["id"]}, headers=owner, timeout=20)
        assert r.status_code == 422

    def test_sales_cannot_assign(self, sales, po_job, sales_id):
        r = requests.put(f"{API}/jobs/{po_job[0]}/assign", json={"user_id": sales_id}, headers=sales, timeout=20)
        assert r.status_code == 403


# ---- Sales PO restrictions ----
class TestSalesPO:
    def test_list_only_own_and_redacted(self, sales, po_job):
        jid, pid, _ = po_job
        r = requests.get(f"{API}/purchase-orders", headers=sales, timeout=30)
        assert r.status_code == 200
        lst = r.json()
        mine = {j["id"] for j in requests.get(f"{API}/jobs", headers=sales, timeout=60).json()}
        assert lst and any(p["job_id"] == jid for p in lst)
        assert all(p["job_id"] in mine for p in lst), [p["job_id"] for p in lst]
        for p in lst:
            assert p["total"] is None
            for i in p["items"]:
                assert i["unit_cost"] is None and i["line_total"] is None and i.get("abc_price") is None
        # filter by other job returns nothing
        assert requests.get(f"{API}/purchase-orders", params={"status": "received"}, headers=sales, timeout=30).status_code == 200

    def test_get_and_history(self, sales, po_job):
        jid, pid, other = po_job
        r = requests.get(f"{API}/purchase-orders/{pid}", headers=sales, timeout=20)
        assert r.status_code == 200 and r.json()["total"] is None
        assert all(i["unit_cost"] is None for i in r.json()["items"])
        assert requests.get(f"{API}/purchase-orders/{pid}/status-history", headers=sales, timeout=20).status_code == 200
        assert requests.get(f"{API}/purchase-orders/{other}", headers=sales, timeout=20).status_code == 404
        assert requests.get(f"{API}/purchase-orders/{other}/status-history", headers=sales, timeout=20).status_code == 404

    def test_owner_full(self, owner, po_job):
        jid, pid, _ = po_job
        lst = requests.get(f"{API}/purchase-orders", headers=owner, timeout=60).json()
        assert len(lst) > 100
        p = requests.get(f"{API}/purchase-orders/{pid}", headers=owner, timeout=20).json()
        assert p["total"] is not None and p["items"][0]["unit_cost"] is not None

    def test_job_detail_po_keys(self, owner, sales, po_job):
        jid = po_job[0]
        s = requests.get(f"{API}/jobs/{jid}", headers=sales, timeout=20).json()
        assert s["purchase_orders"]
        for p in s["purchase_orders"]:
            assert "total" not in p
            assert {"number", "status", "supplier_name", "expected_date"} <= set(p)
        o = requests.get(f"{API}/jobs/{jid}", headers=owner, timeout=20).json()
        assert all("total" in p for p in o["purchase_orders"])

    def test_other_sales_forbidden(self, sales2, po_job):
        jid, pid, _ = po_job
        assert requests.get(f"{API}/jobs/{jid}", headers=sales2, timeout=20).status_code == 403
        assert requests.get(f"{API}/purchase-orders/{pid}", headers=sales2, timeout=20).status_code == 404

    def test_sales_po_writes_forbidden(self, sales, po_job):
        pid = po_job[1]
        assert requests.post(f"{API}/purchase-orders/{pid}/status", json={"status": "sent"}, headers=sales, timeout=20).status_code in (403, 405)


# ---- Mobile / crew regression ----
class TestMobileCrew:
    def test_mobile_job_crew_fields(self, owner):
        jobs = requests.get(f"{API}/jobs", headers=owner, timeout=60).json()
        ca = [j for j in jobs if j.get("crew_name") == "Crew A"]
        assert ca, "expected at least one Crew A job"
        for j in ca[:3]:
            d = requests.get(f"{API}/jobs/{j['id']}", headers=owner, timeout=20)
            assert d.status_code == 200 and d.json()["crew_name"] == "Crew A"
            m = requests.get(f"{API}/mobile/jobs/{j['id']}", headers=owner, timeout=20).json()
            assert m["assigned_to"] == "Crew A" and m["crew_name"] == "Crew A" and m["crew_id"] == j["crew_id"]
