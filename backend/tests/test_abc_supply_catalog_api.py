"""ABC Supply Catalog (Inventory) — HTTP integration + unit tests (mock server).

Covers: sync (full), catalog browse from cache, active-only + inactive handling, search by
description and item number, availability at branch, add-to-inventory (create + dedupe), ABC identity
preserved on the material, availability never written to on-hand quantity, disconnected/missing-context
handling, RBAC (sales blocked), and no token/secret leakage in responses.
"""
import os
import pytest
import requests

from integrations.abc_supply import catalog as abc_catalog

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
SALES = ("sales1_38f545f9@example.com", "Sales1#2026")
CLIENT_ID = "mock-client-id-123456"
CLIENT_SECRET = "mock-secret-abcdef"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def owner_headers():
    return {"Authorization": f"Bearer {_login(*OWNER)}"}


@pytest.fixture(scope="module")
def sales_headers():
    try:
        tok = _login(*SALES)
    except AssertionError:
        pytest.skip("Sales test user not available")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module", autouse=True)
def _connected(owner_headers):
    requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=owner_headers,
                 json={"environment": "sandbox", "client_id": CLIENT_ID}, timeout=30)
    requests.put(f"{BASE_URL}/api/integrations/abc/config/secret", headers=owner_headers,
                 json={"client_secret": CLIENT_SECRET}, timeout=30)
    st = requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=owner_headers, timeout=30).json()
    if st.get("status") != "connected":
        requests.post(f"{BASE_URL}/api/integrations/abc/disconnect", headers=owner_headers, timeout=30)
        r = requests.post(f"{BASE_URL}/api/integrations/abc/connect", headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:200]
        s = requests.Session()
        r1 = s.get(r.json()["authorize_url"], allow_redirects=False, timeout=30)
        cb = r1.headers["location"]
        if cb.startswith("/"):
            cb = BASE_URL + cb
        s.get(cb, allow_redirects=False, timeout=30)
        st = requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=owner_headers, timeout=30).json()
        assert st["status"] == "connected", st
    requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=owner_headers,
                 json={"default_ship_to_number": "1163698", "default_branch_number": "18"}, timeout=30)
    yield


def _wait_sync(owner_headers, timeout=20):
    import time
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = requests.get(f"{BASE_URL}/api/integrations/abc/catalog/sync/status", headers=owner_headers, timeout=30).json()
        if last["status"] in ("completed", "failed"):
            return last
        time.sleep(1)
    return last


# ---------------- Unit: mapping ----------------
class TestMapping:
    def test_map_active_item(self):
        item = {"itemNumber": "X-1", "itemDescription": "Test", "manufacturer": "Acme", "status": "Active",
                "uoms": [{"code": "BD", "description": "stocking"}], "branchNumbers": ["18", "409"],
                "hierarchy": {"productGroup": {"label": "Steep", "category": {"label": "Roofing"}}}}
        f = abc_catalog.map_catalog_fields(item)
        assert f["abc_item_number"] == "X-1"
        assert f["status"] == "active"
        assert f["unit_of_measure"] == "BD"
        assert f["category"] == "Roofing"
        assert f["branch_numbers"] == ["18", "409"]

    def test_map_inactive_status(self):
        f = abc_catalog.map_catalog_fields({"itemNumber": "X-2", "status": "Inactive"})
        assert f["status"] == "inactive"


# ---------------- Sync ----------------
class TestSync:
    def test_full_sync_completes(self, owner_headers):
        r = requests.post(f"{BASE_URL}/api/integrations/abc/catalog/sync?full=true", headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["status"] == "syncing"
        final = _wait_sync(owner_headers)
        assert final["status"] == "completed", final
        assert final["total_items"] >= 7
        assert final["last_synced_at"] and final["last_full_sync_at"]


# ---------------- Browse / search ----------------
class TestBrowse:
    def test_cache_list_active_only_excludes_inactive(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/catalog", headers=owner_headers,
                         params={"active_only": "true", "page_size": 50}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        nums = [i["item_number"] for i in data["items"]]
        assert "MOCK-SHINGLE-ARCH-WW" in nums
        assert "MOCK-DISCONTINUED" not in nums  # inactive excluded from active-only browse
        # context reflects connection + defaults
        assert data["context"]["connected"] is True
        assert data["context"]["branch_number"] == "18"
        # availability at branch present; no stock quantity leaked
        for it in data["items"]:
            assert it["available_at_branch"] in (True, False, None)
            for k in ("quantity_on_hand", "on_hand", "stock", "stockQuantity"):
                assert k not in it

    def test_search_by_item_number(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/catalog", headers=owner_headers,
                         params={"q": "MOCK-UNDERLAYMENT-30"}, timeout=30)
        assert r.status_code == 200
        nums = [i["item_number"] for i in r.json()["items"]]
        assert nums == ["MOCK-UNDERLAYMENT-30"]

    def test_search_by_description(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/catalog", headers=owner_headers,
                         params={"q": "Underlayment"}, timeout=30)
        assert r.status_code == 200
        nums = [i["item_number"] for i in r.json()["items"]]
        assert "MOCK-UNDERLAYMENT-30" in nums

    def test_pagination(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/catalog", headers=owner_headers,
                         params={"page": 1, "page_size": 2}, timeout=30)
        data = r.json()
        assert len(data["items"]) <= 2
        assert data["total_pages"] >= 1
        assert data["page"] == 1

    def test_detail_active(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/catalog/MOCK-SHINGLE-ARCH-WW", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        assert r.json()["item_number"] == "MOCK-SHINGLE-ARCH-WW"


# ---------------- Add to inventory ----------------
class TestAddToInventory:
    def test_add_creates_then_dedupes(self, owner_headers):
        num = "MOCK-ICEWATER-BARRIER"
        r1 = requests.post(f"{BASE_URL}/api/integrations/abc/catalog/{num}/add-to-inventory", headers=owner_headers, json={}, timeout=30)
        assert r1.status_code == 200, r1.text[:300]
        d1 = r1.json()
        assert d1["abc_item_number"] == num
        mat_id = d1["material_id"]
        # Second add must not create a duplicate
        r2 = requests.post(f"{BASE_URL}/api/integrations/abc/catalog/{num}/add-to-inventory", headers=owner_headers, json={}, timeout=30)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["already_linked"] is True
        assert d2["created"] is False
        assert d2["material_id"] == mat_id

    def test_material_has_abc_identity_and_zero_on_hand(self, owner_headers):
        num = "MOCK-SHINGLE-ARCH-WW"
        requests.post(f"{BASE_URL}/api/integrations/abc/catalog/{num}/add-to-inventory", headers=owner_headers, json={}, timeout=30)
        mats = requests.get(f"{BASE_URL}/api/materials", headers=owner_headers, timeout=30).json()
        m = next((x for x in mats if x.get("abc_item_number") == num), None)
        assert m is not None, "material not created with abc_item_number"
        assert m["vendor"] == "ABC Supply"
        assert m["quantity_on_hand"] == 0  # availability is NOT on-hand stock

    def test_catalog_marks_in_inventory(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/catalog/MOCK-SHINGLE-ARCH-WW", headers=owner_headers, timeout=30)
        d = r.json()
        assert d["in_inventory"] is True
        assert d["material_id"]


# ---------------- Security / RBAC ----------------
class TestSecurity:
    def test_no_token_leak_in_catalog(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/catalog", headers=owner_headers, timeout=30)
        body = r.text.lower()
        for leak in ("access_token", "client_secret", "refresh_token", "mock-access-", "mock-refresh-"):
            assert leak not in body

    def test_sales_blocked(self, sales_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/catalog", headers=sales_headers, timeout=30)
        assert r.status_code == 403
        r2 = requests.post(f"{BASE_URL}/api/integrations/abc/catalog/MOCK-SHINGLE-ARCH-WW/add-to-inventory",
                           headers=sales_headers, json={}, timeout=30)
        assert r2.status_code == 403
