# KISS Round 4: Materials quick filters (counts vs filtered lists vs reorder suggestions vs job plans)
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
SALES = {"email": "sales_bk@example.com", "password": "SalesBk#2026"}
KEYS = ("short_for_jobs", "needs_ordering", "on_order", "arriving_week")


def _login(creds):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {creds['email']}: {r.status_code}")
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


@pytest.fixture(scope="module")
def owner():
    return _login(OWNER)


@pytest.fixture(scope="module")
def sales():
    return _login(SALES)


def _counts(s):
    r = s.get(f"{BASE_URL}/api/materials/quick-counts", timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


# Quick counts shape + count/list agreement
class TestQuickCounts:
    def test_shape(self, owner):
        d = _counts(owner)
        assert set(d["counts"].keys()) == set(KEYS)
        assert all(isinstance(v, int) for v in d["counts"].values())
        assert isinstance(d["short_for_jobs_ids"], list)
        assert len(d["short_for_jobs_ids"]) == d["counts"]["short_for_jobs"]
        print("COUNTS", d["counts"])

    def test_counts_match_lists(self, owner):
        # Concurrent suites create/receive materials and POs; per key, only compare a list read whose count
        # was identical immediately before and after it (a tight window instead of one spanning every key).
        for k in KEYS:
            for _ in range(8):
                before = _counts(owner)
                r = owner.get(f"{BASE_URL}/api/materials", params={"quick": k, "active": "true"}, timeout=120)
                assert r.status_code == 200, r.text
                after = _counts(owner)
                if before["counts"][k] == after["counts"][k] and before.get("short_for_jobs_ids") == after.get("short_for_jobs_ids"):
                    break
            else:
                pytest.skip(f"{k} kept changing under concurrent suites; no stable snapshot")
            lst, d = r.json(), before
            assert len(lst) == d["counts"][k], f"{k}: list {len(lst)} != count {d['counts'][k]}"
            if k == "short_for_jobs":
                assert sorted(m["id"] for m in lst) == sorted(d["short_for_jobs_ids"])

    def test_short_subset_of_needs_ordering(self, owner):
        d = _counts(owner)
        need = {m["id"] for m in owner.get(f"{BASE_URL}/api/materials", params={"quick": "needs_ordering"}, timeout=120).json()}
        assert set(d["short_for_jobs_ids"]) <= need
        arr = {m["id"] for m in owner.get(f"{BASE_URL}/api/materials", params={"quick": "arriving_week"}, timeout=120).json()}
        oo = {m["id"] for m in owner.get(f"{BASE_URL}/api/materials", params={"quick": "on_order"}, timeout=120).json()}
        assert arr <= oo

    def test_invalid_key_422(self, owner):
        r = owner.get(f"{BASE_URL}/api/materials", params={"quick": "bogus"}, timeout=30)
        assert r.status_code == 422

    def test_sales_can_read_counts(self, sales):
        d = _counts(sales)
        assert set(d["counts"].keys()) == set(KEYS)

    def test_reorder_suggestions_agree(self, owner):
        d = _counts(owner)
        sugg = owner.get(f"{BASE_URL}/api/inventory/reorder-suggestions", timeout=180).json()["suggestions"]
        sugg_ids = {s["material_id"] for s in sugg}
        need = {m["id"] for m in owner.get(f"{BASE_URL}/api/materials", params={"quick": "needs_ordering"}, timeout=120).json()}
        missing = sugg_ids - need
        assert not missing, f"reorder suggestions not in needs_ordering: {missing}"
        # needs_ordering == short ∪ reorder suggestions
        assert need == sugg_ids | set(d["short_for_jobs_ids"]), (need ^ (sugg_ids | set(d["short_for_jobs_ids"])))

    def test_short_matches_job_plans(self, owner):
        d = _counts(owner)
        jobs = owner.get(f"{BASE_URL}/api/jobs", timeout=60).json()
        excluded = {"completed", "cancelled", "closed", "archived", "lost"}
        short_from_plans = set()
        checked = 0
        for j in jobs:
            if j.get("status") in excluded:
                continue
            p = owner.get(f"{BASE_URL}/api/jobs/{j['id']}/material-plan", timeout=60)
            if p.status_code != 200:
                continue
            checked += 1
            for row in p.json()["materials"]:
                if (row.get("shortage") or 0) > 0:
                    short_from_plans.add(row["material_id"])
        print(f"checked {checked} active jobs; plan-short={len(short_from_plans)}")
        # Walking every job plan takes a while and concurrent suites create/plan materials meanwhile, so judge
        # against the counts read before AND after the walk (a material may only appear/disappear in between).
        after = _counts(owner)
        before_ids, after_ids = set(d["short_for_jobs_ids"]), set(after["short_for_jobs_ids"])
        assert (before_ids & after_ids) <= short_from_plans
        diff = short_from_plans - (before_ids | after_ids)
        if diff:
            # any extras must be inactive materials
            for mid in diff:
                m = owner.get(f"{BASE_URL}/api/materials/{mid}/detail", timeout=30).json()
                assert m.get("active") is False or m.get("material", {}).get("active") is False, f"{mid} short on plan but not in quick"


# Create TEST material + PO -> counts move consistently
class TestQuickLifecycle:
    state = {}

    def test_create_and_po(self, owner):
        base = _counts(owner)["counts"]
        name = f"TEST_KISS4_{uuid.uuid4().hex[:6]}"
        r = owner.post(f"{BASE_URL}/api/materials", json={"name": name, "reorder_threshold": 50, "quantity_on_hand": 5}, timeout=30)
        assert r.status_code == 201, r.text
        mid = r.json()["id"]
        self.state["mid"] = mid
        c1 = _counts(owner)["counts"]
        assert c1["needs_ordering"] == base["needs_ordering"] + 1
        sup = owner.get(f"{BASE_URL}/api/suppliers", timeout=30).json()
        exp = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        po = owner.post(f"{BASE_URL}/api/purchase-orders", json={
            "supplier_id": sup[0]["id"] if sup else None, "supplier_name": None if sup else "TEST_Supplier",
            "expected_date": exp, "notes": "TEST_KISS4",
            "items": [{"material_id": mid, "description": name, "quantity": 10, "unit_cost": 1}]}, timeout=30)
        assert po.status_code == 201, po.text
        self.state["po"] = po.json()
        c2 = _counts(owner)["counts"]
        assert c2["on_order"] == c1["on_order"] + 1
        assert c2["arriving_week"] == c1["arriving_week"] + 1
        # 5 + 10 < 50 -> still needs ordering
        assert c2["needs_ordering"] == c1["needs_ordering"]
        lst = owner.get(f"{BASE_URL}/api/materials", params={"quick": "arriving_week", "q": name}, timeout=60).json()
        assert [m["id"] for m in lst] == [mid]

    def test_receive_full_clears_on_order(self, owner):
        po = self.state.get("po")
        if not po:
            pytest.skip("no po")
        line = po["items"][0]
        # move to ordered first if needed
        owner.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/status", json={"status": "ordered"}, timeout=30)
        r = owner.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/receive",
                       json={"items": [{"po_item_id": line["id"], "quantity": 10}]}, timeout=30)
        assert r.status_code == 200, r.text
        name_ids = {m["id"] for m in owner.get(f"{BASE_URL}/api/materials", params={"quick": "on_order"}, timeout=120).json()}
        assert self.state["mid"] not in name_ids
        arr = {m["id"] for m in owner.get(f"{BASE_URL}/api/materials", params={"quick": "arriving_week"}, timeout=120).json()}
        assert self.state["mid"] not in arr

    def test_cleanup(self, owner):
        mid = self.state.get("mid")
        if not mid:
            pytest.skip("nothing")
        # deactivate -> excluded from counts, then try delete
        owner.patch(f"{BASE_URL}/api/materials/{mid}", json={"active": False}, timeout=30)
        need = {m["id"] for m in owner.get(f"{BASE_URL}/api/materials", params={"quick": "needs_ordering"}, timeout=120).json()}
        assert mid not in need
        r = owner.delete(f"{BASE_URL}/api/materials/{mid}", timeout=30)
        print("delete material", r.status_code, r.text[:200])


# Iteration 126: needs_ordering_ids returned by quick-counts and agreement with list
class TestNeedsOrderingIds:
    def test_ids_present_and_match_count(self, owner):
        d = _counts(owner)
        assert isinstance(d.get("needs_ordering_ids"), list)
        assert len(d["needs_ordering_ids"]) == d["counts"]["needs_ordering"]
        assert len(set(d["needs_ordering_ids"])) == len(d["needs_ordering_ids"])

    def test_ids_match_filtered_list(self, owner):
        d = _counts(owner)
        r = owner.get(f"{BASE_URL}/api/materials", params={"quick": "needs_ordering"}, timeout=120)
        assert r.status_code == 200
        assert {m["id"] for m in r.json()} == set(d["needs_ordering_ids"])

    def test_short_ids_subset_of_order_ids(self, owner):
        d = _counts(owner)
        assert set(d["short_for_jobs_ids"]) <= set(d["needs_ordering_ids"])

    def test_zero_threshold_zero_available_not_needs_ordering(self, owner):
        mid = "a9d6453c-497a-41c8-928c-8d0cfead2c4e"
        d = _counts(owner)
        r = owner.get(f"{BASE_URL}/api/materials/{mid}", timeout=60)
        if r.status_code == 404:
            pytest.skip("reference material missing")
        assert mid not in d["needs_ordering_ids"]
        assert mid not in d["short_for_jobs_ids"]

    def test_sales_gets_ids(self, sales):
        d = _counts(sales)
        assert "needs_ordering_ids" in d and "short_for_jobs_ids" in d
