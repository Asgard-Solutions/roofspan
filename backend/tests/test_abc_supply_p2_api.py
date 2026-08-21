"""ABC Supply Phase 2 — HTTP integration tests against running app (public URL).

Covers:
  - Owner connects ABC (mock) for the test session
  - Product search + branch availability filter
  - Product details (isDimensional)
  - Pricing: standard, $0 as unavailable, dimensional variation-required, unknown-item
  - Purchase order create (ABC): metadata echoed, pricing_warning message
  - Refresh price: apply=true updates line unit_cost/PO total; non-ABC line returns 400
  - Regression: generic non-ABC PO still works, pricing_warning null, integration_provider null
  - RBAC: sales -> 403 on /products/search and /pricing
"""
import os
import pytest
import requests

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
    tok = _login(*OWNER)
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def sales_headers():
    try:
        tok = _login(*SALES)
    except AssertionError:
        pytest.skip("Sales test user not available")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module", autouse=True)
def _ensure_connected(owner_headers):
    """Ensure ABC is connected (mock) for the whole module."""
    # Configure
    requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=owner_headers,
                 json={"environment": "sandbox", "client_id": CLIENT_ID}, timeout=30)
    requests.put(f"{BASE_URL}/api/integrations/abc/config/secret", headers=owner_headers,
                 json={"client_secret": CLIENT_SECRET}, timeout=30)
    st = requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=owner_headers, timeout=30).json()
    if st.get("status") != "connected":
        # Do OAuth mock flow
        requests.post(f"{BASE_URL}/api/integrations/abc/disconnect", headers=owner_headers, timeout=30)
        r = requests.post(f"{BASE_URL}/api/integrations/abc/connect", headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:200]
        authorize_url = r.json()["authorize_url"]
        s = requests.Session()
        r1 = s.get(authorize_url, allow_redirects=False, timeout=30)
        assert r1.status_code == 302
        cb = r1.headers["location"]
        if cb.startswith("/"):
            cb = BASE_URL + cb
        r2 = s.get(cb, allow_redirects=False, timeout=30)
        assert r2.status_code == 302
        st = requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=owner_headers, timeout=30).json()
        assert st["status"] == "connected", st
    # Set defaults
    requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=owner_headers,
                 json={"default_ship_to_number": "1163698", "default_branch_number": "18"}, timeout=30)
    yield


# ---------- Product search ----------
class TestProductSearch:
    def test_search_branch_18_returns_items(self, owner_headers):
        r = requests.post(f"{BASE_URL}/api/integrations/abc/products/search", headers=owner_headers,
                          json={"query": "Mock", "branch_number": "18"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        items = data.get("items") if isinstance(data, dict) else data
        assert items and isinstance(items, list)
        nums = [i.get("item_number") or i.get("itemNumber") for i in items]
        assert "MOCK-SHINGLE-ARCH-WW" in nums
        # available_at_branch flag present + True
        for it in items:
            avail = it.get("available_at_branch")
            assert avail is True, f"item {it} not marked available_at_branch=True"
            # No raw stock quantity numbers should leak
            for k in ("stock_quantity", "stockQuantity", "quantity_on_hand", "onHand"):
                assert k not in it, f"stock qty field {k} leaked in {it}"

    def test_branch_409_filters_underlayment(self, owner_headers):
        r = requests.post(f"{BASE_URL}/api/integrations/abc/products/search", headers=owner_headers,
                          json={"query": "Underlayment", "branch_number": "409"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        items = data.get("items") if isinstance(data, dict) else data
        assert items == [] or len(items) == 0, f"expected 0 items at branch 409, got {items}"


# ---------- Product details ----------
class TestProductDetails:
    def test_dimensional_flag(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/products/MOCK-DRIP-EDGE-DIM",
                         headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        # accept either snake or camel
        is_dim = data.get("is_dimensional")
        if is_dim is None:
            is_dim = data.get("isDimensional")
        assert is_dim is True, data


# ---------- Pricing ----------
def _price(headers, lines, ship_to="1163698", branch="18"):
    r = requests.post(f"{BASE_URL}/api/integrations/abc/pricing", headers=headers,
                      json={"ship_to_number": ship_to, "branch_number": branch, "lines": lines}, timeout=30)
    return r


class TestPricing:
    def test_standard_priced(self, owner_headers):
        r = _price(owner_headers, [{"id": "1", "item_number": "MOCK-SHINGLE-ARCH-WW", "quantity": 10, "uom": "SQ"}])
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        lines = data.get("lines") if isinstance(data, dict) else data
        assert lines and lines[0]["price_status"] == "priced"
        assert lines[0]["unit_price"] == 135.36

    def test_zero_price_unavailable(self, owner_headers):
        r = _price(owner_headers, [{"id": "1", "item_number": "MOCK-RIDGE-CAP-NOPRICE", "quantity": 5, "uom": "BD"}])
        assert r.status_code == 200
        lines = r.json().get("lines") or r.json()
        assert lines[0]["unit_price"] == 0.0
        assert lines[0]["price_status"] == "unavailable"

    def test_dimensional_requires_length(self, owner_headers):
        r = _price(owner_headers, [{"id": "1", "item_number": "MOCK-DRIP-EDGE-DIM", "quantity": 4, "uom": "PC"}])
        lines = r.json().get("lines") or r.json()
        assert lines[0]["price_status"] == "unavailable"
        msg = (lines[0].get("status_message") or lines[0].get("message") or "").lower()
        assert "length" in msg or "variation" in msg or "dimension" in msg

        r2 = _price(owner_headers, [{"id": "1", "item_number": "MOCK-DRIP-EDGE-DIM", "quantity": 4, "uom": "PC",
                                      "length_value": 10, "length_uom": "ft"}])
        lines2 = r2.json().get("lines") or r2.json()
        assert lines2[0]["price_status"] == "priced"
        assert lines2[0]["unit_price"] == 65.0

    def test_unknown_item_unavailable(self, owner_headers):
        r = _price(owner_headers, [{"id": "1", "item_number": "NOPE-XYZ", "quantity": 1}])
        lines = r.json().get("lines") or r.json()
        assert lines[0]["price_status"] == "unavailable"


# ---------- RBAC ----------
class TestRBACPhase2:
    def test_sales_forbidden_search(self, sales_headers):
        r = requests.post(f"{BASE_URL}/api/integrations/abc/products/search", headers=sales_headers,
                          json={"query": "Mock", "branch_number": "18"}, timeout=30)
        assert r.status_code == 403, r.text[:200]

    def test_sales_forbidden_pricing(self, sales_headers):
        r = requests.post(f"{BASE_URL}/api/integrations/abc/pricing", headers=sales_headers,
                          json={"ship_to_number": "1163698", "branch_number": "18",
                                "lines": [{"id": "1", "item_number": "MOCK-SHINGLE-ARCH-WW", "quantity": 1}]}, timeout=30)
        assert r.status_code == 403


# ---------- Purchase Order (ABC) create + refresh ----------
class TestAbcPO:
    _po_id = None
    _shingle_line_id = None
    _ridge_line_id = None

    def test_01_create_abc_po(self, owner_headers):
        payload = {
            "supplier_name": "ABC Supply",
            "integration_provider": "abc_supply",
            "abc_ship_to_number": "1163698",
            "abc_branch_number": "18",
            "notes": "TEST_ABC P2",
            "items": [
                {"description": "Mock Shingle Architectural", "quantity": 10, "unit": "SQ", "unit_cost": 135.36,
                 "integration_provider": "abc_supply", "abc_item_number": "MOCK-SHINGLE-ARCH-WW",
                 "abc_branch_number": "18", "abc_ship_to_number": "1163698", "abc_uom": "SQ",
                 "abc_price": 135.36, "abc_price_status": "priced", "pricing_source": "abc"},
                {"description": "Mock Ridge Cap (no price)", "quantity": 5, "unit": "BD", "unit_cost": 0,
                 "integration_provider": "abc_supply", "abc_item_number": "MOCK-RIDGE-CAP-NOPRICE",
                 "abc_branch_number": "18", "abc_ship_to_number": "1163698", "abc_uom": "BD",
                 "abc_price": 0.0, "abc_price_status": "unavailable", "pricing_source": "abc"},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=owner_headers, json=payload, timeout=30)
        assert r.status_code in (200, 201), r.text[:300]
        data = r.json()
        assert data["integration_provider"] == "abc_supply"
        assert data["abc_ship_to_number"] == "1163698"
        assert data["abc_branch_number"] == "18"
        assert data.get("pricing_warning")
        assert "1" in data["pricing_warning"] and "pricing" in data["pricing_warning"].lower()
        assert len(data["items"]) == 2
        for it in data["items"]:
            assert it["abc_item_number"] in ("MOCK-SHINGLE-ARCH-WW", "MOCK-RIDGE-CAP-NOPRICE")
            assert it["pricing_source"] == "abc"
            assert it["abc_price_status"] in ("priced", "unavailable")
        TestAbcPO._po_id = data["id"]
        for it in data["items"]:
            if it["abc_item_number"] == "MOCK-SHINGLE-ARCH-WW":
                TestAbcPO._shingle_line_id = it["id"]
            else:
                TestAbcPO._ridge_line_id = it["id"]

    def test_02_refresh_price_apply(self, owner_headers):
        assert TestAbcPO._po_id and TestAbcPO._shingle_line_id
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{TestAbcPO._po_id}/refresh-price",
                          headers=owner_headers,
                          json={"po_item_id": TestAbcPO._shingle_line_id, "apply": True}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["price_status"] == "priced"
        assert data["applied"] is True
        assert data["abc_price"] == 135.36
        # Get PO and verify unit_cost updated
        r2 = requests.get(f"{BASE_URL}/api/purchase-orders/{TestAbcPO._po_id}", headers=owner_headers, timeout=30)
        assert r2.status_code == 200
        po = r2.json()
        line = next(i for i in po["items"] if i["id"] == TestAbcPO._shingle_line_id)
        assert line["unit_cost"] == 135.36

    def test_03_refresh_non_abc_returns_400(self, owner_headers):
        # Create a generic (non-ABC) PO with a line
        payload = {"supplier_name": "TEST_Generic", "items": [
            {"description": "Nails", "quantity": 2, "unit": "box", "unit_cost": 25}
        ]}
        r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=owner_headers, json=payload, timeout=30)
        assert r.status_code in (200, 201)
        po = r.json()
        line_id = po["items"][0]["id"]
        r2 = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/refresh-price",
                           headers=owner_headers,
                           json={"po_item_id": line_id, "apply": False}, timeout=30)
        assert r2.status_code == 400, r2.text[:200]


# ---------- Regression: Generic PO ----------
class TestGenericPORegression:
    def test_create_generic_po(self, owner_headers):
        payload = {"supplier_name": "Generic Roofing Supply",
                   "items": [{"description": "Nails", "quantity": 2, "unit": "box", "unit_cost": 25}]}
        r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=owner_headers, json=payload, timeout=30)
        assert r.status_code in (200, 201), r.text[:300]
        data = r.json()
        assert data["supplier_name"] == "Generic Roofing Supply"
        assert data.get("integration_provider") in (None, "")
        assert data.get("pricing_warning") in (None, "")
        assert data["total"] == 50.0
        assert data["items"][0]["pricing_source"] in (None, "")

    def test_list_purchase_orders(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/purchase-orders", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
