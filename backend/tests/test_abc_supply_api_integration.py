"""ABC Supply Phase 1 — HTTP integration tests against the running app (public URL).

Covers:
  - RBAC (owner allowed, sales 403 on all endpoints)
  - Config + secret round-trip
  - OAuth (mock) connect -> authorize -> callback -> status=connected
  - Accounts (retired filtered), branches by ship_to and by state
  - Defaults persisted
  - Test connection (connected + client-credentials paths)
  - Disconnect resets state
  - Regression: /api/purchase-orders GET + POST
"""
import os
import re
import requests
import pytest

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


# ---------- RBAC ----------
class TestRBAC:
    def test_owner_can_get_status(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        assert "status" in r.json()

    @pytest.mark.parametrize("method,path,payload", [
        ("GET", "/api/integrations/abc/status", None),
        ("PUT", "/api/integrations/abc/config", {"environment": "sandbox"}),
        ("PUT", "/api/integrations/abc/config/secret", {"client_secret": "x"}),
        ("POST", "/api/integrations/abc/connect", None),
        ("POST", "/api/integrations/abc/disconnect", None),
        ("PUT", "/api/integrations/abc/defaults", {"default_ship_to_number": "1"}),
        ("GET", "/api/integrations/abc/accounts", None),
        ("GET", "/api/integrations/abc/branches", None),
        ("POST", "/api/integrations/abc/test", None),
    ])
    def test_sales_forbidden(self, sales_headers, method, path, payload):
        r = requests.request(method, f"{BASE_URL}{path}", headers=sales_headers, json=payload, timeout=30)
        assert r.status_code == 403, f"{method} {path} expected 403, got {r.status_code}: {r.text[:120]}"


# ---------- End-to-end connect flow ----------
class TestConnectFlow:
    def test_01_configure(self, owner_headers):
        r = requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=owner_headers,
                         json={"environment": "sandbox", "client_id": CLIENT_ID}, timeout=30)
        assert r.status_code == 200
        assert r.json()["has_client_id"] is True

        r = requests.put(f"{BASE_URL}/api/integrations/abc/config/secret", headers=owner_headers,
                         json={"client_secret": CLIENT_SECRET}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["has_client_id"] is True
        assert data["has_client_secret"] is True
        assert data["is_mock"] is True

    def test_02_disconnect_first_for_clean_state(self, owner_headers):
        requests.post(f"{BASE_URL}/api/integrations/abc/disconnect", headers=owner_headers, timeout=30)

    def test_03_test_connection_when_not_connected(self, owner_headers):
        r = requests.post(f"{BASE_URL}/api/integrations/abc/test", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True, data
        assert "Location API reachable" in data["message"] or "credentials valid" in data["message"].lower()

    def test_04_connect_and_callback(self, owner_headers):
        r = requests.post(f"{BASE_URL}/api/integrations/abc/connect", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        authorize_url = r.json()["authorize_url"]
        assert "/abc-mock/oauth2/v1/authorize" in authorize_url
        assert "code_challenge=" in authorize_url and "S256" in authorize_url

        # Follow authorize -> should 302 to /api/integrations/abc/callback
        s = requests.Session()
        # Use cookies from browser session not required (callback identifies via state)
        r1 = s.get(authorize_url, allow_redirects=False, timeout=30)
        assert r1.status_code == 302, r1.text[:200]
        cb_url = r1.headers["location"]
        assert "/api/integrations/abc/callback" in cb_url
        # Absolute or relative?
        if cb_url.startswith("/"):
            cb_url = BASE_URL + cb_url
        r2 = s.get(cb_url, allow_redirects=False, timeout=30)
        assert r2.status_code == 302
        assert "abc=connected" in r2.headers["location"]

        # Verify status
        r3 = requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=owner_headers, timeout=30)
        assert r3.status_code == 200
        st = r3.json()
        assert st["status"] == "connected"
        assert st["connected_identity"] is not None
        scopes = st.get("token_scopes") or ""
        assert "account.read" in scopes and "offline_access" in scopes

    def test_05_accounts_filters_retired(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/accounts", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        accs = r.json()
        nums = [a["number"] for a in accs]
        assert "1163698" in nums                         # active, has branches
        assert not any(a["number"] == "9999999" for a in accs)  # retired (empty branches) filtered out
        assert all(a.get("branches") for a in accs)      # only non-retired accounts returned

    def test_06_branches_by_ship_to(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/branches?ship_to=1163698", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        branches = r.json()
        nums = [b["number"] for b in branches]
        assert "18" in nums and "409" in nums
        home = [b for b in branches if b["number"] == "18"]
        assert home and home[0].get("home_branch") is True

    def test_06b_branches_when_shipto_detail_omits_branches(self, owner_headers):
        # Regression: ABC Ship-To DETAIL sometimes omits the branch list even though the account
        # SEARCH result (which populated the picker) had branches. Ship-To 2010466-2 models this in
        # the mock. The branch picker must NOT come back empty.
        r = requests.get(f"{BASE_URL}/api/integrations/abc/branches?ship_to=2010466-2", headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:200]
        branches = r.json()
        assert len(branches) >= 1, "branch picker must resolve branches even when Ship-To detail omits them"
        assert "18" in [b["number"] for b in branches]

    def test_07_branches_by_state(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/branches?state=WI", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_08_defaults_persist(self, owner_headers):
        r = requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=owner_headers,
                         json={"default_ship_to_number": "1163698", "default_branch_number": "18"}, timeout=30)
        assert r.status_code == 200
        r2 = requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=owner_headers, timeout=30)
        st = r2.json()
        assert st["default_ship_to_number"] == "1163698"
        assert st["default_branch_number"] == "18"

    def test_09_test_connection_when_connected(self, owner_headers):
        r = requests.post(f"{BASE_URL}/api/integrations/abc/test", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "ship-to" in data["message"].lower()

    def test_10_disconnect(self, owner_headers):
        r = requests.post(f"{BASE_URL}/api/integrations/abc/disconnect", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        assert r.json()["status"] == "not_connected"
        r2 = requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=owner_headers, timeout=30)
        assert r2.json()["status"] == "not_connected"


# ---------- Regression: Purchase Orders ----------
class TestPurchaseOrdersRegression:
    def test_list_purchase_orders(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/purchase-orders", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_purchase_order(self, owner_headers):
        payload = {"supplier_name": "TEST_ABC Regression Supplier", "notes": "TEST_ regression"}
        r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=owner_headers, json=payload, timeout=30)
        # accept 200 or 201 depending on backend
        assert r.status_code in (200, 201), r.text[:200]
        data = r.json()
        assert data.get("supplier_name") == payload["supplier_name"]
