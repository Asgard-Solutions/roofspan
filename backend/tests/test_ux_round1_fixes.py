# UX Round 1 retest: sales scoping of quotes + purchasing dashboard, jobs material_status batching (read-only)
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


@pytest.fixture(scope="module")
def owner_quotes(owner):
    r = owner.get(f"{BASE_URL}/api/quotes", timeout=60)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def owner_jobs(owner):
    r = owner.get(f"{BASE_URL}/api/jobs", timeout=90)
    assert r.status_code == 200
    return r.json()


# Quotes scoping
class TestQuotesScoping:
    def test_owner_sees_all(self, owner_quotes):
        assert len(owner_quotes) > 100  # iteration_117 saw 866

    def test_sales_only_assigned_leads(self, owner, sales, owner_quotes):
        r = sales.get(f"{BASE_URL}/api/quotes", timeout=60)
        assert r.status_code == 200
        sq = r.json()
        assert len(sq) < len(owner_quotes)
        uid = sales.user["id"]
        for q in sq[:30]:
            assert q.get("lead_id")
            lr = owner.get(f"{BASE_URL}/api/leads/{q['lead_id']}", timeout=30)
            assert lr.status_code == 200
            assert lr.json().get("assigned_user_id") == uid
        print("sales quotes:", len(sq), "owner quotes:", len(owner_quotes))

    def test_sales_lead_filter_own_and_foreign(self, owner, sales, owner_quotes):
        uid = sales.user["id"]
        sq = sales.get(f"{BASE_URL}/api/quotes", timeout=60).json()
        if sq:
            lid = sq[0]["lead_id"]
            r = sales.get(f"{BASE_URL}/api/quotes", params={"lead_id": lid}, timeout=30)
            assert r.status_code == 200 and len(r.json()) >= 1
            assert all(q["lead_id"] == lid for q in r.json())
        # foreign lead -> empty
        for q in owner_quotes[:60]:
            if q.get("lead_id"):
                l = owner.get(f"{BASE_URL}/api/leads/{q['lead_id']}", timeout=30).json()
                if l.get("assigned_user_id") != uid:
                    r = sales.get(f"{BASE_URL}/api/quotes", params={"lead_id": q["lead_id"]}, timeout=30)
                    assert r.status_code == 200 and r.json() == []
                    return
        pytest.skip("no foreign lead found")

    def test_attention_proposals_consistent(self, sales):
        d = sales.get(f"{BASE_URL}/api/dashboard/attention", timeout=30).json()
        sq = {q["id"]: q for q in sales.get(f"{BASE_URL}/api/quotes", timeout=60).json()}
        for p in d["proposals"]["items"]:  # only the rep's own draft/sent proposals that need attention
            assert p["id"] in sq and sq[p["id"]]["status"] in ("draft", "sent")


# Purchasing dashboard scoping
class TestPurchasingScoping:
    def test_sales_only_own_shortages_no_po(self, sales):
        r = sales.get(f"{BASE_URL}/api/dashboard/purchasing", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        acts = d.get("action_required", [])
        assert not any(a["type"].startswith("po_") for a in acts)
        own = {j["id"] for j in sales.get(f"{BASE_URL}/api/jobs", timeout=60).json()}
        for a in acts:
            if a["type"] == "job_shortage":
                assert a["link"].split("/")[-1] in own
        print("sales actions:", len(acts), "keys:", list(d.keys()))

    def test_owner_unchanged(self, owner):
        r = owner.get(f"{BASE_URL}/api/dashboard/purchasing", timeout=60)
        assert r.status_code == 200
        acts = r.json().get("action_required", [])
        assert any(a["type"] == "job_shortage" for a in acts)
        print("owner actions:", len(acts), {a["type"] for a in acts})


# Jobs material_status after batching
class TestJobsMaterialStatus:
    def test_values(self, owner_jobs):
        vals = {j["material_status"] for j in owner_jobs}
        assert vals <= {"none", "ready", "short"}
        print("counts:", {v: sum(1 for j in owner_jobs if j["material_status"] == v) for v in vals})

    def test_shortage_jobs_marked_short(self, owner, owner_jobs):
        byid = {j["id"]: j for j in owner_jobs}
        acts = owner.get(f"{BASE_URL}/api/dashboard/purchasing", timeout=60).json().get("action_required", [])
        ids = [a["link"].split("/")[-1] for a in acts if a["type"] == "job_shortage"]
        assert ids
        for i in ids:
            assert byid[i]["material_status"] == "short", i

    def test_none_means_no_materials(self, owner, owner_jobs):
        # cancelled jobs are reported as "none" by design even if they still carry JobMaterial rows
        nones = [j for j in owner_jobs if j["material_status"] == "none" and j.get("status") != "cancelled"][:5]
        for j in nones:
            d = owner.get(f"{BASE_URL}/api/jobs/{j['id']}", timeout=30).json()
            assert d["materials"] == []
        withm = [j for j in owner_jobs if j["material_status"] != "none"][:5]
        for j in withm:
            d = owner.get(f"{BASE_URL}/api/jobs/{j['id']}", timeout=30).json()
            assert len(d["materials"]) > 0


# Positive scoping: sales1 creates a TEST quote on own lead, sees it in /api/quotes + lead detail; cleaned up
SALES1 = {"email": "sales1_38f545f9@example.com", "password": "Sales1#2026"}
SALES1_LEAD = "68e4968b-ec51-46f7-b60e-331322a123e9"


class TestSalesOwnQuote:
    def test_own_quote_visible_other_sales_not(self, owner, sales):
        s1 = _login(SALES1)
        r = s1.post(f"{BASE_URL}/api/quotes", json={"lead_id": SALES1_LEAD, "terms": "TEST_scoping",
                    "items": [{"description": "TEST_item", "quantity": 1, "unit_price": 10}]}, timeout=30)
        assert r.status_code == 201, r.text
        qid = r.json()["id"]
        try:
            ids = [q["id"] for q in s1.get(f"{BASE_URL}/api/quotes", timeout=30).json()]
            assert qid in ids
            ids2 = [q["id"] for q in s1.get(f"{BASE_URL}/api/quotes", params={"lead_id": SALES1_LEAD}, timeout=30).json()]
            assert qid in ids2
            assert qid not in [q["id"] for q in sales.get(f"{BASE_URL}/api/quotes", timeout=30).json()]
            assert qid in [q["id"] for q in owner.get(f"{BASE_URL}/api/quotes", params={"lead_id": SALES1_LEAD}, timeout=30).json()]
        finally:
            d = owner.delete(f"{BASE_URL}/api/quotes/{qid}", timeout=30)
            assert d.status_code == 200
