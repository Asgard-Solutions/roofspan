"""P0 contract fix: ABC Supply order comments must be arrays of {code, description}.

Covers:
  1. RoofSpan /api/purchase-orders/{po_id}/abc-submit with order_comments (H) succeeds
     -- proving the payload builder produces orderComments as an array of {code,description}
     objects (the mock now rejects the legacy `comments` string shape).
  2. Same, with per-line line_comments (D) - order still confirms.
  3. Regression: submit with NO comments still confirms.
  4. Direct mock validation: POST /api/abc-mock/api/order/v2/orders
       - bare top-level `comments` string -> HTTP 400
       - orderComments entry missing description -> HTTP 400
       - orderComments entry with invalid code -> HTTP 400
       - line comments as bare string -> HTTP 400
       - proper H/F/D shape -> succeeds
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
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def owner_headers():
    return {"Authorization": f"Bearer {_login(*OWNER)}"}


@pytest.fixture(scope="module", autouse=True)
def _ensure_connected(owner_headers):
    """Make sure ABC integration is connected to the mock, mirroring test_abc_supply_p3_api."""
    requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=owner_headers,
                 json={"environment": "sandbox", "client_id": CLIENT_ID}, timeout=30)
    requests.put(f"{BASE_URL}/api/integrations/abc/config/secret", headers=owner_headers,
                 json={"client_secret": CLIENT_SECRET}, timeout=30)
    # Always force a fresh reconnect: some prior test run may have left the mock's
    # in-memory token store cleared while the DB still shows "connected".
    requests.post(f"{BASE_URL}/api/integrations/abc/disconnect",
                  headers=owner_headers, timeout=30)
    r = requests.post(f"{BASE_URL}/api/integrations/abc/connect",
                      headers=owner_headers, timeout=30)
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
    st = requests.get(f"{BASE_URL}/api/integrations/abc/status",
                      headers=owner_headers, timeout=30).json()
    assert st.get("status") == "connected", st
    requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=owner_headers,
                 json={"default_ship_to_number": "1163698", "default_branch_number": "18"},
                 timeout=30)
    yield


# ------------ helpers ------------
def _abc_line(item="MOCK-SHINGLE-ARCH-WW", qty=10, cost=135.36, uom="SQ", desc="Shingle"):
    return {
        "description": desc, "quantity": qty, "unit": uom, "unit_cost": cost,
        "integration_provider": "abc_supply", "abc_item_number": item,
        "abc_branch_number": "18", "abc_ship_to_number": "1163698", "abc_uom": uom,
        "abc_price": cost, "abc_price_status": "priced", "pricing_source": "abc",
    }


def _create_abc_po(headers, items, notes="TEST_P0_COMMENTS"):
    payload = {
        "supplier_name": "ABC Supply", "integration_provider": "abc_supply",
        "abc_ship_to_number": "1163698", "abc_branch_number": "18",
        "notes": notes, "items": items,
    }
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=headers,
                      json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text[:300]
    return r.json()


def _submit(headers, po_id, body):
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/abc-submit",
                      headers=headers, json=body, timeout=60)
    assert r.status_code == 200, r.text[:300]
    return r.json()


# ============ RoofSpan payload-builder end-to-end (via abc-submit) ============
class TestRoofSpanBuildsCorrectShape:
    """If RoofSpan sent the OLD shape (`order[\"comments\"]=<string>`), the tightened
    mock validator would return 400 -> status=failed. Confirmed status is the proof
    that RoofSpan built the correct orderComments array of {code, description}."""

    def test_order_level_comment_succeeds(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line()])
        data = _submit(owner_headers, po["id"], {
            "submission_key": f"p0-oc-{uuid.uuid4().hex}",
            "order_comments": "Please deliver by 8am; call site foreman first.",
        })
        assert data.get("status") == "confirmed", data
        assert data.get("confirmation_number", "").startswith("MOCK-CONF-"), data

    def test_line_level_comment_succeeds(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line()])
        first_item_id = po["items"][0]["id"]
        data = _submit(owner_headers, po["id"], {
            "submission_key": f"p0-lc-{uuid.uuid4().hex}",
            "line_comments": {str(first_item_id): "Stack bundles on driveway, not roof."},
        })
        assert data.get("status") == "confirmed", data
        assert data.get("confirmation_number", "").startswith("MOCK-CONF-"), data

    def test_no_comments_regression(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line()])
        data = _submit(owner_headers, po["id"], {
            "submission_key": f"p0-none-{uuid.uuid4().hex}",
        })
        assert data.get("status") == "confirmed", data
        assert data.get("confirmation_number", "").startswith("MOCK-CONF-"), data

    def test_both_order_and_line_comments_succeed(self, owner_headers):
        po = _create_abc_po(owner_headers, [_abc_line(), _abc_line(desc="Shingle B")])
        first_id = po["items"][0]["id"]
        data = _submit(owner_headers, po["id"], {
            "submission_key": f"p0-both-{uuid.uuid4().hex}",
            "order_comments": "Header note for driver.",
            "line_comments": {str(first_id): "Detail note on line 1."},
        })
        assert data.get("status") == "confirmed", data


# ============ Direct mock validator contract ============
class TestMockValidatorRejectsLegacyShape:
    """Post directly to the mock's POST /api/order/v2/orders using the mock's own
    client_credentials token to verify _validate_comments rejects the old wire shapes."""

    @pytest.fixture(scope="class")
    def mock_bearer(self):
        # The mock's OAuth token endpoint is under /api/abc-mock/oauth2/v1/token
        r = requests.post(f"{BASE_URL}/api/abc-mock/oauth2/v1/token",
                          data={"grant_type": "client_credentials",
                                "scope": "order.write"}, timeout=30)
        if r.status_code != 200:
            pytest.skip(f"ABC mock not enabled/reachable: {r.status_code} {r.text[:120]}")
        return r.json()["access_token"]

    def _post(self, mock_bearer, order):
        return requests.post(
            f"{BASE_URL}/api/abc-mock/api/order/v2/orders",
            headers={"Authorization": f"Bearer {mock_bearer}"},
            json=[order], timeout=30)

    def _base_order(self):
        return {
            "requestId": f"mock-req-{uuid.uuid4().hex}",
            "purchaseOrder": "P0-TEST",
            "branchNumber": "18",
            "typeCode": "SO", "currency": "USD",
            "shipTo": {"number": "1163698", "name": "TEST"},
            "lines": [{
                "id": "1", "itemNumber": "MOCK-SHINGLE-ARCH-WW",
                "itemDescription": "Shingle",
                "orderedQty": {"value": 1, "uom": "SQ"},
                "unitPrice": {"value": 135.36, "uom": "SQ"},
            }],
        }

    def test_reject_bare_comments_string_at_order_level(self, mock_bearer):
        order = self._base_order()
        order["comments"] = "This is the LEGACY wrong shape."
        r = self._post(mock_bearer, order)
        assert r.status_code == 400, r.text[:300]
        body = r.json()
        msg = str(body).lower()
        assert "ordercomments" in msg or "comments" in msg
        assert "array" in msg or "not a `comments` string" in msg or "code" in msg

    def test_reject_ordercomments_missing_description(self, mock_bearer):
        order = self._base_order()
        order["orderComments"] = [{"code": "H", "description": ""}]
        r = self._post(mock_bearer, order)
        assert r.status_code == 400, r.text[:300]
        assert "description" in r.text.lower() or "code" in r.text.lower()

    def test_reject_ordercomments_invalid_code(self, mock_bearer):
        order = self._base_order()
        order["orderComments"] = [{"code": "X", "description": "bad code"}]
        r = self._post(mock_bearer, order)
        assert r.status_code == 400, r.text[:300]
        assert "code" in r.text.lower()

    def test_reject_line_comments_as_bare_string(self, mock_bearer):
        order = self._base_order()
        order["lines"][0]["comments"] = "legacy bare string"
        r = self._post(mock_bearer, order)
        assert r.status_code == 400, r.text[:300]
        assert "line" in r.text.lower() or "array" in r.text.lower()

    def test_reject_line_comment_invalid_code(self, mock_bearer):
        order = self._base_order()
        order["lines"][0]["comments"] = [{"code": "Z", "description": "bad"}]
        r = self._post(mock_bearer, order)
        assert r.status_code == 400, r.text[:300]

    def test_accept_correct_shape_H_order_D_line(self, mock_bearer):
        order = self._base_order()
        order["orderComments"] = [{"code": "H", "description": "Header note"}]
        order["lines"][0]["comments"] = [{"code": "D", "description": "Detail note"}]
        r = self._post(mock_bearer, order)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["orders"][0]["confirmationNumber"].startswith("MOCK-CONF-"), body

    def test_accept_footer_code_F(self, mock_bearer):
        order = self._base_order()
        order["orderComments"] = [
            {"code": "H", "description": "Header"},
            {"code": "F", "description": "Footer"},
        ]
        r = self._post(mock_bearer, order)
        assert r.status_code == 200, r.text[:300]

    def test_accept_no_comments(self, mock_bearer):
        r = self._post(mock_bearer, self._base_order())
        assert r.status_code == 200, r.text[:300]
