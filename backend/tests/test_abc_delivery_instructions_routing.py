"""P1: Delivery instructions routing into ABC deliveryAppointment.instructions (<=255)
with overflow appended to orderComments as {code:'D', ...}. Nothing gets lost.

Two layers:
  A. End-to-end via /api/purchase-orders/{po_id}/abc-submit — verify the ABC mock accepts
     (a) short instructions with no appointment type, (b) instructions + TR appointment,
     (c) >255-char instructions (D overflow), and (d) combined H order comment + D overflow.
     Regression: no instructions + no appointment still submits.
  B. Direct builder-level assertions on _build_delivery_appointment(...) — the exact
     payload shape (255 cap + overflow) doesn't require touching the network.
"""
import os
import sys
import uuid
import pytest
import requests

# Make backend/ importable for white-box builder tests.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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
    requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=owner_headers,
                 json={"environment": "sandbox", "client_id": CLIENT_ID}, timeout=30)
    requests.put(f"{BASE_URL}/api/integrations/abc/config/secret", headers=owner_headers,
                 json={"client_secret": CLIENT_SECRET}, timeout=30)
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
    st = requests.get(f"{BASE_URL}/api/integrations/abc/status",
                      headers=owner_headers, timeout=30).json()
    assert st.get("status") == "connected", st
    requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=owner_headers,
                 json={"default_ship_to_number": "1163698", "default_branch_number": "18"},
                 timeout=30)
    yield


def _abc_line():
    return {
        "description": "Shingle", "quantity": 10, "unit": "SQ", "unit_cost": 135.36,
        "integration_provider": "abc_supply", "abc_item_number": "MOCK-SHINGLE-ARCH-WW",
        "abc_branch_number": "18", "abc_ship_to_number": "1163698", "abc_uom": "SQ",
        "abc_price": 135.36, "abc_price_status": "priced", "pricing_source": "abc",
    }


def _create_po(headers):
    payload = {
        "supplier_name": "ABC Supply", "integration_provider": "abc_supply",
        "abc_ship_to_number": "1163698", "abc_branch_number": "18",
        "notes": "TEST_P1_INSTR", "items": [_abc_line()],
    }
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=headers, json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text[:300]
    return r.json()


def _submit(headers, po_id, body):
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/abc-submit",
                      headers=headers, json=body, timeout=60)
    assert r.status_code == 200, r.text[:300]
    return r.json()


class TestEndToEndInstructionsRouting:
    def _base(self):
        return {"submission_key": f"p1-instr-{uuid.uuid4().hex}"}

    def test_short_instructions_no_appt_confirms(self, owner_headers):
        """Short instruction, no appointment_type -> AT + instructions in deliveryAppointment."""
        po = _create_po(owner_headers)
        body = self._base()
        body["delivery"] = {"instructions": "Leave pallet in driveway; call 555-1234"}
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "confirmed", data
        assert data.get("confirmation_number", "").startswith("MOCK-CONF-"), data

    def test_instructions_with_TR_appointment_confirms(self, owner_headers):
        po = _create_po(owner_headers)
        body = self._base()
        body["delivery"] = {
            "instructions": "Deliver to rear yard",
            "appointment_type": "TR",
            "appointment_from": "09:00", "appointment_to": "12:00",
        }
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "confirmed", data

    def test_instructions_over_255_overflows_to_orderComments_D(self, owner_headers):
        """Instructions >255 chars must be truncated in deliveryAppointment.instructions and
        the remainder pushed into orderComments as a D entry. Mock accepts both shapes; if
        the builder had left the full text in the appointment (>255) the mock would 400."""
        po = _create_po(owner_headers)
        body = self._base()
        long_text = "A" * 260 + "OVERFLOW-TAIL"  # 273 chars; overflow = last 18
        body["delivery"] = {"instructions": long_text}
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "confirmed", data

    def test_order_comment_H_plus_instructions_overflow_D(self, owner_headers):
        po = _create_po(owner_headers)
        body = self._base()
        body["order_comments"] = "Deliver only if a foreman is present."
        body["delivery"] = {"instructions": "B" * 400}  # 400 chars: 255 + 145 overflow
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "confirmed", data

    def test_regression_no_instructions_no_appt(self, owner_headers):
        po = _create_po(owner_headers)
        data = _submit(owner_headers, po["id"], self._base())
        assert data.get("status") == "confirmed", data


class TestBuilderInstructionsShape:
    """White-box: _build_delivery_appointment enforces 255-char cap and returns overflow."""

    def test_short_defaults_to_AT(self):
        from routers.purchasing import _build_delivery_appointment
        appt, overflow = _build_delivery_appointment({"instructions": "hello"})
        assert appt == {"instructionsTypeCode": "AT", "instructions": "hello"}
        assert overflow is None

    def test_exactly_255_no_overflow(self):
        from routers.purchasing import _build_delivery_appointment
        s = "x" * 255
        appt, overflow = _build_delivery_appointment({"instructions": s})
        assert appt["instructions"] == s
        assert len(appt["instructions"]) == 255
        assert overflow is None

    def test_over_255_overflows(self):
        from routers.purchasing import _build_delivery_appointment
        s = "A" * 255 + "TAIL"
        appt, overflow = _build_delivery_appointment({"instructions": s})
        assert appt["instructions"] == "A" * 255
        assert len(appt["instructions"]) == 255
        assert overflow == "TAIL"

    def test_no_instructions_no_appt_returns_none(self):
        from routers.purchasing import _build_delivery_appointment
        appt, overflow = _build_delivery_appointment({})
        assert appt is None and overflow is None

    def test_TR_with_times_and_instructions(self):
        from routers.purchasing import _build_delivery_appointment
        appt, overflow = _build_delivery_appointment({
            "appointment_type": "TR", "appointment_from": "09:00",
            "appointment_to": "12:00", "instructions": "call ahead",
        })
        assert appt["instructionsTypeCode"] == "TR"
        assert appt["fromTime"] == "09:00"
        assert appt["toTime"] == "12:00"
        assert appt["instructions"] == "call ahead"
        assert overflow is None


class TestMockRejectsBadInstructions:
    """Sanity: the mock still 400s on a >255-char instructions payload — proving the E2E
    'confirmed' outcomes above are only possible because the builder truncates + overflows."""

    @pytest.fixture(scope="class")
    def mock_bearer(self):
        r = requests.post(f"{BASE_URL}/api/abc-mock/oauth2/v1/token",
                          data={"grant_type": "client_credentials", "scope": "order.write"},
                          timeout=30)
        if r.status_code != 200:
            pytest.skip(f"ABC mock not reachable: {r.status_code}")
        return r.json()["access_token"]

    def _base_order(self):
        return {
            "requestId": f"mock-req-{uuid.uuid4().hex}",
            "purchaseOrder": "P1-INSTR", "branchNumber": "18",
            "typeCode": "SO", "currency": "USD",
            "shipTo": {"number": "1163698", "name": "TEST"},
            "lines": [{"id": "1", "itemNumber": "MOCK-SHINGLE-ARCH-WW",
                       "itemDescription": "Shingle",
                       "orderedQty": {"value": 1, "uom": "SQ"},
                       "unitPrice": {"value": 135.36, "uom": "SQ"}}],
        }

    def _post(self, mock_bearer, order):
        return requests.post(f"{BASE_URL}/api/abc-mock/api/order/v2/orders",
                             headers={"Authorization": f"Bearer {mock_bearer}"},
                             json=[order], timeout=30)

    def test_mock_rejects_instructions_over_255(self, mock_bearer):
        order = self._base_order()
        order["deliveryAppointment"] = {"instructionsTypeCode": "AT",
                                        "instructions": "z" * 256}
        r = self._post(mock_bearer, order)
        assert r.status_code == 400, r.text[:200]

    def test_mock_accepts_instructions_exactly_255_plus_D_comment(self, mock_bearer):
        order = self._base_order()
        order["deliveryAppointment"] = {"instructionsTypeCode": "AT",
                                        "instructions": "y" * 255}
        order["orderComments"] = [
            {"code": "H", "description": "header note"},
            {"code": "D", "description": "Delivery instructions (continued): tail"},
        ]
        r = self._post(mock_bearer, order)
        assert r.status_code == 200, r.text[:200]
