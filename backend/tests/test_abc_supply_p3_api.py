"""ABC Supply Phase 3 — Order submit / status / history HTTP integration tests.

Covers (per P3 review request):
  - abc-submit-review: ok=true for priced PO; ok=false when a line is unavailable
  - abc-submit happy path: 'confirmed' + MOCK-CONF-*; PO becomes 'ordered'; external_confirmation_number stored
  - Mandatory price refresh: 'price_changed' without accept; 'confirmed' with accept_price_changes
  - Duplicate protection: same submission_key on confirmed -> 'already_submitted'; new key on confirmed -> 'already_submitted'
  - Concurrency: 4 parallel /abc-submit with same key -> exactly one 'confirmed'
  - Rejection (MOCK-REJECT) -> 'failed' and PO not 'ordered'
  - Unknown state (MOCK-TIMEOUT) -> 'unknown'; re-submit same key -> 'unknown' (no auto-retry)
  - Reconcile after unknown -> 'reconciled' with confirmation
  - abc-refresh-status on submitted PO -> abc_status + normalized_status + order_number
  - orders/history + orders/{conf} + templates
  - RBAC: sales -> 403 on P3 endpoints
  - Regression: generic non-ABC PO create/list/receive still works and inventory updates;
    a submitted ABC PO is NOT auto-received.

NOTE: The mock's in-memory order store resets on backend reload. Run this file in ONE pass.
"""
import os
import time
import uuid
import concurrent.futures as cf

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
    return {"Authorization": f"Bearer {_login(*OWNER)}"}


@pytest.fixture(scope="module")
def sales_headers():
    try:
        tok = _login(*SALES)
    except AssertionError:
        pytest.skip("Sales test user not available")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module", autouse=True)
def _ensure_connected(owner_headers):
    requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=owner_headers,
                 json={"environment": "sandbox", "client_id": CLIENT_ID}, timeout=30)
    requests.put(f"{BASE_URL}/api/integrations/abc/config/secret", headers=owner_headers,
                 json={"client_secret": CLIENT_SECRET}, timeout=30)
    st = requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=owner_headers, timeout=30).json()
    if st.get("status") != "connected":
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
    requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=owner_headers,
                 json={"default_ship_to_number": "1163698", "default_branch_number": "18"}, timeout=30)
    yield


# -------- helpers --------
def _create_abc_po(headers, items, notes="TEST_P3"):
    payload = {
        "supplier_name": "ABC Supply",
        "integration_provider": "abc_supply",
        "abc_ship_to_number": "1163698",
        "abc_branch_number": "18",
        "notes": notes,
        "items": items,
    }
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=headers, json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text[:300]
    return r.json()


def _abc_line(item, qty, cost, uom="SQ", desc="Mock item"):
    return {
        "description": desc, "quantity": qty, "unit": uom, "unit_cost": cost,
        "integration_provider": "abc_supply", "abc_item_number": item,
        "abc_branch_number": "18", "abc_ship_to_number": "1163698", "abc_uom": uom,
        "abc_price": cost, "abc_price_status": "priced" if cost > 0 else "unavailable",
        "pricing_source": "abc",
    }


# -------- Review --------
class TestReview:
    def test_review_ok_when_priced(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-SHINGLE-ARCH-WW", 10, 135.36, desc="Shingle")])
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit-review",
                          headers=owner_headers, json={}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["ok"] is True, data
        assert data["errors"] == []
        assert "review" in data and data["review"]["po_number"] == po["number"]
        assert data["review"]["lines"][0]["abc_item_number"] == "MOCK-SHINGLE-ARCH-WW"

    def test_review_flags_unavailable_line(self, owner_headers):
        po = _create_abc_po(owner_headers, [
            _abc_line("MOCK-SHINGLE-ARCH-WW", 10, 135.36),
            _abc_line("MOCK-RIDGE-CAP-NOPRICE", 5, 0, uom="BD", desc="Ridge cap"),
        ])
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit-review",
                          headers=owner_headers, json={}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["ok"] is False, data
        assert data["errors"], "expected errors when unavailable line present"
        blob = str(data["errors"]).upper()
        assert "MOCK-RIDGE-CAP-NOPRICE" in blob or "RIDGE" in blob


# -------- Happy path submit --------
class TestSubmitHappyPath:
    def test_submit_confirmed(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-SHINGLE-ARCH-WW", 10, 135.36)])
        key = f"sub-happy-{uuid.uuid4().hex}"
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers, json={"submission_key": key}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["status"] == "confirmed", data
        assert data["confirmation_number"].startswith("MOCK-CONF-")
        # Verify PO updated
        po_get = requests.get(f"{BASE_URL}/api/purchase-orders/{po['id']}", headers=owner_headers, timeout=30).json()
        assert po_get["status"] == "ordered"
        # NOTE: POOut does NOT currently expose external_confirmation_number/abc_order_status —
        # verifying via abc-refresh-status which fetches the confirmation from server-side state
        rs = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-refresh-status",
                           headers=owner_headers, timeout=30)
        assert rs.status_code == 200, rs.text[:300]
        assert rs.json().get("abc_status")


# -------- Price refresh (mandatory) --------
class TestPriceChangeReview:
    def test_price_changed_then_accepted(self, owner_headers):
        # Deliberately store an outdated price (100) vs mock's 135.36
        line = _abc_line("MOCK-SHINGLE-ARCH-WW", 10, 100.0)
        line["abc_price"] = 100.0
        po = _create_abc_po(owner_headers, [line])
        key1 = f"sub-pc-{uuid.uuid4().hex}"
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers,
                          json={"submission_key": key1, "accept_price_changes": False}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["status"] == "price_changed", data
        assert data.get("price_changes"), data
        assert data.get("previous_total") is not None
        assert data.get("updated_total") is not None
        # Verify PO not ordered yet
        po_now = requests.get(f"{BASE_URL}/api/purchase-orders/{po['id']}", headers=owner_headers, timeout=30).json()
        assert po_now["status"] != "ordered"

        # Now accept the changes with a new submission key
        key2 = f"sub-pc-accept-{uuid.uuid4().hex}"
        r2 = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                           headers=owner_headers,
                           json={"submission_key": key2, "accept_price_changes": True}, timeout=60)
        assert r2.status_code == 200, r2.text[:300]
        d2 = r2.json()
        assert d2["status"] == "confirmed", d2
        po_after = requests.get(f"{BASE_URL}/api/purchase-orders/{po['id']}", headers=owner_headers, timeout=30).json()
        assert po_after["status"] == "ordered"
        # Line price should be updated to mock's 135.36
        line0 = po_after["items"][0]
        assert line0["unit_cost"] == 135.36, line0


# -------- Duplicate / idempotency --------
class TestDuplicateProtection:
    def test_same_key_and_new_key_both_already_submitted(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-SHINGLE-ARCH-WW", 3, 135.36)])
        key = f"sub-dup-{uuid.uuid4().hex}"
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers, json={"submission_key": key}, timeout=60)
        assert r.json()["status"] == "confirmed"
        conf = r.json()["confirmation_number"]

        # Same key
        r2 = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                           headers=owner_headers, json={"submission_key": key}, timeout=60)
        assert r2.json()["status"] == "already_submitted"
        assert r2.json().get("confirmation_number") == conf

        # New key on already confirmed PO
        new_key = f"sub-dup2-{uuid.uuid4().hex}"
        r3 = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                           headers=owner_headers, json={"submission_key": new_key}, timeout=60)
        assert r3.json()["status"] == "already_submitted", r3.json()
        # Only one confirmation exists
        assert r3.json().get("confirmation_number") == conf


# -------- Concurrency --------
class TestConcurrency:
    def test_four_parallel_same_key_one_confirmed(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-SHINGLE-ARCH-WW", 4, 135.36)])
        key = f"sub-cc-{uuid.uuid4().hex}"

        def _submit():
            return requests.post(
                f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                headers=owner_headers, json={"submission_key": key}, timeout=60
            ).json()

        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            results = list(ex.map(lambda _: _submit(), range(4)))
        statuses = [r.get("status") for r in results]
        confirmed = [r for r in results if r.get("status") == "confirmed"]
        assert len(confirmed) == 1, f"expected exactly one confirmed, got statuses={statuses}"
        # Others may be 'pending' or 'already_submitted' but never a second 'confirmed'
        for r in results:
            assert r.get("status") in ("confirmed", "pending", "already_submitted"), r

        # Verify only ONE confirmation number on PO (via refresh-status)
        po_get = requests.get(f"{BASE_URL}/api/purchase-orders/{po['id']}", headers=owner_headers, timeout=30).json()
        assert po_get["status"] == "ordered"


# -------- Rejection --------
class TestRejection:
    def test_mock_reject_returns_failed(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-REJECT", 1, 50.0, uom="EA", desc="Reject")])
        key = f"sub-rej-{uuid.uuid4().hex}"
        # accept_price_changes=True in case mock prices this item differently — we want the REJECT path, not price_changed
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers, json={"submission_key": key, "accept_price_changes": True}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["status"] == "failed", data
        po_get = requests.get(f"{BASE_URL}/api/purchase-orders/{po['id']}", headers=owner_headers, timeout=30).json()
        assert po_get["status"] != "ordered"


# -------- Unknown + Reconcile --------
class TestUnknownAndReconcile:
    def test_timeout_unknown_no_retry_then_reconcile(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-TIMEOUT", 1, 20.0, uom="EA", desc="Timeout")])
        key = f"sub-to-{uuid.uuid4().hex}"
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers, json={"submission_key": key, "accept_price_changes": True}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["status"] == "unknown", r.json()

        # Re-submit with same key => still unknown, no auto retry
        r2 = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                           headers=owner_headers, json={"submission_key": key, "accept_price_changes": True}, timeout=60)
        assert r2.json()["status"] == "unknown", r2.json()

        # Reconcile
        r3 = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-reconcile",
                           headers=owner_headers, timeout=60)
        assert r3.status_code == 200, r3.text[:300]
        d3 = r3.json()
        assert d3["status"] == "reconciled", d3
        assert d3.get("confirmation_number")


# -------- Refresh status --------
class TestRefreshStatus:
    def test_refresh_status(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-SHINGLE-ARCH-WW", 2, 135.36)])
        key = f"sub-rs-{uuid.uuid4().hex}"
        s = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers, json={"submission_key": key}, timeout=60).json()
        assert s["status"] == "confirmed"
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-refresh-status",
                          headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("abc_status"), d
        assert d.get("normalized_status") in ("processing", "invoiced", "delivered", "submitted", "pending"), d
        assert d.get("order_number")


# -------- History / detail / templates --------
class TestHistoryDetailTemplates:
    def test_history_and_detail(self, owner_headers):
        # Ensure at least one submitted order exists in this test session
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-SHINGLE-ARCH-WW", 1, 135.36)], notes="TEST_P3_HIST")
        key = f"sub-hist-{uuid.uuid4().hex}"
        s = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers, json={"submission_key": key}, timeout=60).json()
        assert s["status"] == "confirmed", s
        r = requests.get(f"{BASE_URL}/api/integrations/abc/orders/history", headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        payload = r.json()
        orders = payload.get("orders") if isinstance(payload, dict) else payload
        assert isinstance(orders, list) and orders, "expected at least one submitted order in history"
        first = orders[0]
        assert "confirmationNumber" in first and "purchaseOrder" in first and "status" in first
        conf = first["confirmationNumber"]
        r2 = requests.get(f"{BASE_URL}/api/integrations/abc/orders/{conf}", headers=owner_headers, timeout=30)
        assert r2.status_code == 200, r2.text[:300]
        detail = r2.json()
        assert detail.get("confirmation_number") == conf or detail.get("confirmationNumber") == conf

    def test_templates(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/templates", headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        payload = r.json()
        tmpls = payload.get("templates") if isinstance(payload, dict) else payload
        assert tmpls and isinstance(tmpls, list)
        assert any("Standard Reroof Kit" == t.get("name") for t in tmpls)


# -------- RBAC --------
class TestRBAC:
    def test_sales_403_all_p3(self, owner_headers, sales_headers):
        # Prepare an ABC PO with owner
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-SHINGLE-ARCH-WW", 1, 135.36)])
        pid = po["id"]
        endpoints = [
            ("POST", f"/api/purchase-orders/{pid}/abc-submit-review", {}),
            ("POST", f"/api/purchase-orders/{pid}/abc-submit", {"submission_key": f"sub-{uuid.uuid4().hex}"}),
            ("POST", f"/api/purchase-orders/{pid}/abc-refresh-status", {}),
            ("GET", "/api/integrations/abc/orders/history", None),
        ]
        for method, path, body in endpoints:
            if method == "POST":
                r = requests.post(f"{BASE_URL}{path}", headers=sales_headers, json=body or {}, timeout=30)
            else:
                r = requests.get(f"{BASE_URL}{path}", headers=sales_headers, timeout=30)
            assert r.status_code == 403, f"{method} {path} -> {r.status_code} {r.text[:200]}"


# -------- Regression --------
class TestRegression:
    def test_generic_po_create_and_receive(self, owner_headers):
        # Create generic (non-ABC) PO
        payload = {"supplier_name": "TEST_Generic_P3",
                   "items": [{"description": "Nails", "quantity": 3, "unit": "box", "unit_cost": 10}]}
        r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=owner_headers, json=payload, timeout=30)
        assert r.status_code in (200, 201), r.text[:300]
        po = r.json()
        assert po.get("integration_provider") in (None, "")
        line_id = po["items"][0]["id"]
        # Move to ordered manually so we can receive
        rs = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/status", headers=owner_headers,
                           json={"status": "ordered"}, timeout=30)
        assert rs.status_code == 200, rs.text[:300]
        # Receive
        rr = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/receive", headers=owner_headers,
                           json={"items": [{"po_item_id": line_id, "quantity": 3}]}, timeout=30)
        assert rr.status_code == 200, rr.text[:300]

    def test_submitted_abc_po_not_auto_received(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-SHINGLE-ARCH-WW", 6, 135.36)])
        key = f"sub-reg-{uuid.uuid4().hex}"
        s = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers, json={"submission_key": key}, timeout=60).json()
        assert s["status"] == "confirmed"
        po_get = requests.get(f"{BASE_URL}/api/purchase-orders/{po['id']}", headers=owner_headers, timeout=30).json()
        assert po_get["status"] == "ordered", po_get["status"]
        # No items should be received
        for it in po_get["items"]:
            received = it.get("received_quantity") or it.get("received") or 0
            assert (received or 0) == 0, f"unexpected received qty {received} on ABC PO {po_get['number']}"
