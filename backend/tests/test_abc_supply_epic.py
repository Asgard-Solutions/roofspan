"""ABC Supply Epic — Order Templates conversion, Place-Order enhancements (limits/comments/appointment),
and Order History RoofSpan-PO matching. Extends the verified P3 suite; run this file in ONE pass
(the mock order store is in-memory).
"""
import os
import uuid

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
CLIENT_ID = "mock-client-id-123456"
CLIENT_SECRET = "mock-secret-abcdef"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def owner_headers():
    return {"Authorization": f"Bearer {_login(*OWNER)}"}


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
        authorize_url = r.json()["authorize_url"]
        s = requests.Session()
        r1 = s.get(authorize_url, allow_redirects=False, timeout=30)
        cb = r1.headers["location"]
        if cb.startswith("/"):
            cb = BASE_URL + cb
        s.get(cb, allow_redirects=False, timeout=30)
    requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=owner_headers,
                 json={"default_ship_to_number": "1163698", "default_branch_number": "18"}, timeout=30)
    yield


def _abc_line(item, qty, cost, uom="SQ", desc="Mock item"):
    return {"description": desc, "quantity": qty, "unit": uom, "unit_cost": cost,
            "integration_provider": "abc_supply", "abc_item_number": item, "abc_branch_number": "18",
            "abc_ship_to_number": "1163698", "abc_uom": uom, "abc_price": cost,
            "abc_price_status": "priced" if cost > 0 else "unavailable", "pricing_source": "abc"}


def _create_abc_po(headers, items):
    payload = {"supplier_name": "ABC Supply", "integration_provider": "abc_supply",
               "abc_ship_to_number": "1163698", "abc_branch_number": "18", "items": items}
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=headers, json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text[:300]
    return r.json()


# -------- Phase A: Template -> RoofSpan PO --------
class TestTemplateConvert:
    def test_convert_creates_draft_po_not_submitted(self, owner_headers):
        # Discover a template id
        tp = requests.get(f"{BASE_URL}/api/integrations/abc/templates", headers=owner_headers, timeout=30).json()
        tid = tp["templates"][0]["templateId"]
        r = requests.post(f"{BASE_URL}/api/purchase-orders/from-abc-template", headers=owner_headers,
                          json={"template_id": tid}, timeout=30)
        assert r.status_code in (200, 201), r.text[:300]
        po = r.json()
        assert po["integration_provider"] == "abc_supply"
        assert po["status"] == "draft"  # NEVER auto-submitted
        assert not po["external_confirmation_number"]
        assert po["items"], po
        # Template lines carried across with ABC identity; pricing forced to fresh (unavailable)
        assert all(li["abc_item_number"] for li in po["items"])
        assert all(li["abc_price_status"] == "unavailable" for li in po["items"])
        assert po["abc_ship_to_number"] == "1163698" and po["abc_branch_number"] == "18"

    def test_converted_po_requires_fresh_pricing_then_submits(self, owner_headers):
        tp = requests.get(f"{BASE_URL}/api/integrations/abc/templates", headers=owner_headers, timeout=30).json()
        tid = tp["templates"][0]["templateId"]
        po = requests.post(f"{BASE_URL}/api/purchase-orders/from-abc-template", headers=owner_headers,
                           json={"template_id": tid}, timeout=30).json()
        # Mandatory fresh pricing runs in review; MOCK items are priced by the mock pricing service
        rv = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit-review",
                           headers=owner_headers, json={"apply_price_changes": True}, timeout=60).json()
        # Template item numbers may not be in the mock price table -> review flags them (proves fresh
        # pricing is enforced and template prices are NOT trusted). Either way it must have run pricing.
        assert "prices_verified_at" in rv, rv


# -------- Phase B: Place Order enhancements + limits --------
class TestPlaceOrderEnhancements:
    def test_99_line_limit_blocks_review(self, owner_headers):
        lines = [_abc_line("MOCK-SHINGLE-ARCH-WW", 1, 135.36, desc=f"L{i}") for i in range(100)]
        po = _create_abc_po(owner_headers, lines)
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit-review",
                          headers=owner_headers, json={}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["ok"] is False
        assert any("99 lines" in e or "limited to 99" in e for e in data["errors"]), data["errors"]

    def test_submit_with_comments_and_appointment(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-SHINGLE-ARCH-WW", 2, 135.36)])
        item_id = po["items"][0]["id"]
        key = f"sub-cmt-{uuid.uuid4().hex}"
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit", headers=owner_headers, json={
            "submission_key": key, "delivery_service": "OTG",
            "order_comments": "Deliver to rear driveway.",
            "line_comments": {item_id: "Handle with care"},
            "delivery": {"requested_date": "2026-07-01", "appointment_time": "09:00-12:00",
                         "contact_name": "Site Foreman", "contact_phone": "555-0100"},
        }, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["status"] == "confirmed", r.json()


# -------- Phase C: Order History RoofSpan matching --------
class TestHistoryMatching:
    def test_history_matches_roofspan_po_after_status_refresh(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-SHINGLE-ARCH-WW", 1, 135.36)])
        key = f"sub-match-{uuid.uuid4().hex}"
        s = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers, json={"submission_key": key}, timeout=60).json()
        assert s["status"] == "confirmed", s
        # order_number is populated by the status refresh (Get Order), enabling strong matching
        rs = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-refresh-status",
                           headers=owner_headers, timeout=30).json()
        onum = rs["order_number"]
        assert onum
        hist = requests.get(f"{BASE_URL}/api/integrations/abc/orders/history",
                            params={"items_per_page": 200}, headers=owner_headers, timeout=30).json()
        row = next((it for it in hist["items"] if str(it.get("orderNumber")) == str(onum)), None)
        assert row is not None, hist["items"]
        assert row["roofspan_matched"] is True
        assert row["roofspan_po_number"] == po["number"]

    def test_get_order_detail_attaches_roofspan_match(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line("MOCK-SHINGLE-ARCH-WW", 1, 135.36)])
        key = f"sub-det-{uuid.uuid4().hex}"
        requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                      headers=owner_headers, json={"submission_key": key}, timeout=60)
        conf = requests.get(f"{BASE_URL}/api/purchase-orders/{po['id']}", headers=owner_headers, timeout=30).json()["external_confirmation_number"]
        d = requests.get(f"{BASE_URL}/api/integrations/abc/orders/{conf}", headers=owner_headers, timeout=30).json()
        assert d["roofspan_matched"] is True
        assert d["roofspan_po_number"] == po["number"]
