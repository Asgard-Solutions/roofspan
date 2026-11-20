# Round 2: quote authz for sales, lead workflow stage, material shortage counts, jobs perf
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
SALES = {"email": "sales_bk@example.com", "password": "SalesBk#2026"}


def _login(creds):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds)
    if r.status_code != 200:
        pytest.skip(f"login failed {creds['email']}: {r.status_code}")
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    s.me = s.get(f"{BASE_URL}/api/auth/me").json()
    return s


@pytest.fixture(scope="module")
def owner():
    return _login(OWNER)


@pytest.fixture(scope="module")
def sales():
    return _login(SALES)


@pytest.fixture(scope="module")
def created():
    return {"leads": [], "quotes": [], "estimates": [], "invoices": [], "jobs": [], "customers": []}


def _mk_lead(owner, created, name):
    r = owner.post(f"{BASE_URL}/api/mobile/leads", json={"name": f"TEST_{name}_{uuid.uuid4().hex[:6]}", "address": "1 Test St", "phone": "555-000-0000", "email": "test@example.com"})
    assert r.status_code in (200, 201), r.text
    lid = r.json()["id"]
    created["leads"].append(lid)
    return lid


def _wf(s, lid):
    r = s.get(f"{BASE_URL}/api/leads/{lid}/workflow")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def setup(owner, sales, created):
    """Lead A (unassigned / owner) + Lead B (assigned to sales_bk), each with customer, estimate, quote."""
    out = {}
    for key, assign in (("other", None), ("mine", sales.me["id"])):
        lid = _mk_lead(owner, created, key)
        if assign:
            r = owner.put(f"{BASE_URL}/api/leads/{lid}/assign", json={"user_id": assign})
            assert r.status_code == 200, r.text
        c = owner.post(f"{BASE_URL}/api/customers/from-lead/{lid}")
        assert c.status_code in (200, 201), c.text
        lead = owner.get(f"{BASE_URL}/api/leads/{lid}").json()
        e = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": lead["customer_id"], "tax_rate": 0,
                                                          "items": [{"description": "TEST shingles", "quantity": 10, "unit": "sq", "unit_price": 100}]})
        assert e.status_code in (200, 201), e.text
        created["estimates"].append(e.json()["id"])
        q = owner.post(f"{BASE_URL}/api/quotes", json={"estimate_id": e.json()["id"]})
        assert q.status_code == 201, q.text
        created["quotes"].append(q.json()["id"])
        out[key] = {"lead": lid, "estimate": e.json()["id"], "quote": q.json()["id"], "customer": lead["customer_id"]}
    return out


GET_ROUTES = ["", "/document", "/pdf", "/proposal", "/proposal.pdf", "/share-link", "/site-plan", "/site-plan.pdf"]


class TestQuoteAuthz:
    @pytest.mark.parametrize("suffix", GET_ROUTES)
    def test_sales_get_other_quote_403(self, sales, setup, suffix):
        r = sales.get(f"{BASE_URL}/api/quotes/{setup['other']['quote']}{suffix}")
        assert r.status_code == 403, f"{suffix}: {r.status_code} {r.text[:200]}"

    def test_sales_mutations_other_quote_403(self, sales, setup):
        qid = setup["other"]["quote"]
        res = {
            "put": sales.put(f"{BASE_URL}/api/quotes/{qid}", json={"terms": "x"}).status_code,
            "accept": sales.post(f"{BASE_URL}/api/quotes/{qid}/accept", json={"acceptance_name": "x"}).status_code,
            "decline": sales.post(f"{BASE_URL}/api/quotes/{qid}/decline").status_code,
            "send": sales.post(f"{BASE_URL}/api/quotes/{qid}/send", json={}).status_code,
            "delete": sales.delete(f"{BASE_URL}/api/quotes/{qid}").status_code,
        }
        assert all(v == 403 for v in res.values()), res

    @pytest.mark.parametrize("suffix", ["", "/proposal", "/pdf", "/share-link", "/document", "/proposal.pdf"])
    def test_sales_get_own_quote_ok(self, sales, setup, suffix):
        r = sales.get(f"{BASE_URL}/api/quotes/{setup['mine']['quote']}{suffix}")
        assert r.status_code == 200, f"{suffix}: {r.status_code} {r.text[:200]}"

    def test_sales_put_own_quote_ok(self, sales, setup):
        r = sales.put(f"{BASE_URL}/api/quotes/{setup['mine']['quote']}", json={"terms": "TEST terms"})
        assert r.status_code == 200, r.text
        assert sales.get(f"{BASE_URL}/api/quotes/{setup['mine']['quote']}").json().get("terms") == "TEST terms"

    @pytest.mark.parametrize("suffix", GET_ROUTES)
    def test_owner_all_get(self, owner, setup, suffix):
        r = owner.get(f"{BASE_URL}/api/quotes/{setup['other']['quote']}{suffix}")
        ok = (200, 404) if suffix == "/site-plan.pdf" else (200,)  # 404 = no saved site plan (not authz)
        assert r.status_code in ok, f"{suffix}: {r.status_code} {r.text[:200]}"

    def test_sales_create_quote_unassigned_403(self, sales, setup):
        assert sales.post(f"{BASE_URL}/api/quotes", json={"estimate_id": setup["other"]["estimate"]}).status_code == 403
        assert sales.post(f"{BASE_URL}/api/quotes", json={"lead_id": setup["other"]["lead"], "items": []}).status_code == 403
        assert sales.post(f"{BASE_URL}/api/quotes", json={"items": []}).status_code == 403

    def test_sales_create_quote_own_ok(self, sales, setup, created):
        r = sales.post(f"{BASE_URL}/api/quotes", json={"estimate_id": setup["mine"]["estimate"]})
        assert r.status_code == 201, r.text
        created["quotes"].append(r.json()["id"])
        assert r.json()["lead_id"] == setup["mine"]["lead"]

    def test_sales_list_only_own(self, sales, setup):
        r = sales.get(f"{BASE_URL}/api/quotes")
        assert r.status_code == 200
        ids = {q["id"] for q in r.json()}
        assert setup["mine"]["quote"] in ids
        assert setup["other"]["quote"] not in ids
        leads = {q["lead_id"] for q in r.json()}
        for lid in list(leads)[:15]:
            assert sales.get(f"{BASE_URL}/api/leads/{lid}").status_code == 200
        r2 = sales.get(f"{BASE_URL}/api/quotes?lead_id={setup['other']['lead']}")
        assert r2.status_code == 200 and r2.json() == []


class TestWorkflow:
    def test_sales_unassigned_workflow_403(self, sales, setup):
        assert sales.get(f"{BASE_URL}/api/leads/{setup['other']['lead']}/workflow").status_code == 403
        assert sales.get(f"{BASE_URL}/api/leads/{setup['mine']['lead']}/workflow").status_code == 200

    def test_workflow_full_progression(self, owner, created):
        lid = _mk_lead(owner, created, "wf")
        w = _wf(owner, lid)
        assert w["stage"] == "overview" and w["stages"] == ["overview", "inspection", "estimate", "production", "billing"]
        assert w["stage_index"] == 0 and w["facts"]["has_customer"] is False
        assert _wf(owner, lid)["stage"] == "overview"  # deterministic
        owner.post(f"{BASE_URL}/api/customers/from-lead/{lid}")
        lead = owner.get(f"{BASE_URL}/api/leads/{lid}").json()
        assert _wf(owner, lid)["stage"] == "inspection"
        ins = owner.post(f"{BASE_URL}/api/inspections", json={"lead_id": lid, "customer_id": lead["customer_id"], "roof_condition": "Fair"})
        assert ins.status_code in (200, 201), ins.text
        w = _wf(owner, lid)
        assert w["stage"] == "inspection" and w["facts"]["inspections"] == 1
        e = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": lead["customer_id"], "tax_rate": 0,
                                                          "items": [{"description": "TEST", "quantity": 1, "unit": "ea", "unit_price": 500}]})
        created["estimates"].append(e.json()["id"])
        assert _wf(owner, lid)["stage"] == "estimate"
        q = owner.post(f"{BASE_URL}/api/quotes", json={"estimate_id": e.json()["id"]}).json()
        created["quotes"].append(q["id"])
        w = _wf(owner, lid)
        assert w["stage"] == "estimate" and w["facts"]["quotes_draft"] == 1
        a = owner.post(f"{BASE_URL}/api/quotes/{q['id']}/accept", json={"acceptance_name": "TEST Signer"})
        assert a.status_code == 200, a.text
        w = _wf(owner, lid)
        assert w["stage"] == "production" and w["facts"]["jobs"] == 1 and w["facts"]["first_job_id"]
        inv = owner.post(f"{BASE_URL}/api/invoices", json={"quote_id": q["id"]})
        assert inv.status_code in (200, 201), inv.text
        created["invoices"].append(inv.json()["id"])
        w = _wf(owner, lid)
        assert w["stage"] == "billing" and w["facts"]["invoices"] == 1 and w["stage_index"] == 4

    def test_example_production_lead(self, owner):
        w = _wf(owner, "e7b41ad7-cc50-4a56-ae70-30558c974c4a")
        assert w["stage"] in ("production", "billing"), w


class TestMaterials:
    def test_jobs_perf_and_shortage_match(self, owner):
        t = time.time()
        r = owner.get(f"{BASE_URL}/api/jobs")
        el = time.time() - t
        assert r.status_code == 200
        print(f"/api/jobs {len(r.json())} jobs in {el:.2f}s")
        assert el < 1.0, el
        jobs = r.json()
        active_short = [j for j in jobs if j["status"] in ("created", "scheduled", "in_progress", "active") and j.get("material_status") == "short"]
        d = owner.get(f"{BASE_URL}/api/dashboard/purchasing").json()
        assert d["cards"]["jobs_needing_materials"] == len(active_short), (d["cards"]["jobs_needing_materials"], len(active_short))
        # per-job plan parity on a sample
        sample = [j for j in jobs if j.get("material_status") in ("short", "ready")][:8]
        for j in sample:
            plan = owner.get(f"{BASE_URL}/api/jobs/{j['id']}/material-plan").json()
            tot = sum(float(m.get("shortage") or 0) for m in plan["materials"])
            exp = "short" if tot > 0 and j["status"] not in ("completed", "cancelled") else "ready"
            assert j["material_status"] == exp, (j["id"], j["material_status"], tot)


@pytest.fixture(scope="module", autouse=True)
def cleanup(created, owner):
    yield
    for i in created["invoices"]:
        owner.post(f"{BASE_URL}/api/invoices/{i}/status", json={"status": "void"})
    for q in created["quotes"]:
        owner.delete(f"{BASE_URL}/api/quotes/{q}")
    for e in created["estimates"]:
        owner.delete(f"{BASE_URL}/api/estimates/{e}")
    # no lead delete endpoint exists; TEST_ leads remain (archived via status if possible)
