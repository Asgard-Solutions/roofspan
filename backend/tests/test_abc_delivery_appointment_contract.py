"""P0 contract: ABC deliveryAppointment object replaces legacy dates.deliveryAppointmentTime.

Two layers of assertions:
  A. End-to-end via /api/purchase-orders/{po_id}/abc-submit:
     - TR w/ from+to -> confirmed
     - ST w/ from -> confirmed
     - AT/AM/PM/FS w/ no times -> confirmed
     - No appointment -> confirmed
     - ST w/o from -> validation_failed
     - TR w/o to -> validation_failed
     - Invalid type code -> validation_failed
  B. Direct mock validator (POST /api/abc-mock/api/order/v2/orders):
     - legacy dates.deliveryAppointmentTime -> 400
     - deliveryAppointment TR w/ from+to -> 200
     - ST w/o fromTime -> 400
     - TR w/o toTime -> 400
     - invalid instructionsTypeCode -> 400
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
        "notes": "TEST_P0_APPT", "items": [_abc_line()],
    }
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=headers, json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text[:300]
    return r.json()


def _submit(headers, po_id, body):
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/abc-submit",
                      headers=headers, json=body, timeout=60)
    assert r.status_code == 200, r.text[:300]
    return r.json()


# -------------- End-to-end (RoofSpan payload builder) --------------
class TestEndToEndAppointmentBuilder:
    def _base(self):
        return {"submission_key": f"p0-appt-{uuid.uuid4().hex}"}

    def test_time_range_TR_confirms(self, owner_headers):
        po = _create_po(owner_headers)
        body = self._base()
        body["delivery"] = {"appointment_type": "TR",
                            "appointment_from": "09:00", "appointment_to": "12:00"}
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "confirmed", data
        assert data.get("confirmation_number", "").startswith("MOCK-CONF-"), data

    def test_specific_time_ST_confirms(self, owner_headers):
        po = _create_po(owner_headers)
        body = self._base()
        body["delivery"] = {"appointment_type": "ST", "appointment_from": "10:30"}
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "confirmed", data

    @pytest.mark.parametrize("code", ["AT", "AM", "PM", "FS"])
    def test_windowless_codes_confirm(self, owner_headers, code):
        po = _create_po(owner_headers)
        body = self._base()
        body["delivery"] = {"appointment_type": code}
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "confirmed", (code, data)

    def test_no_appointment_regression(self, owner_headers):
        po = _create_po(owner_headers)
        data = _submit(owner_headers, po["id"], self._base())
        assert data.get("status") == "confirmed", data

    def test_requested_date_only(self, owner_headers):
        po = _create_po(owner_headers)
        body = self._base()
        body["delivery"] = {"requested_date": "2030-01-15"}
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "confirmed", data

    def test_ST_missing_from_validation_fails(self, owner_headers):
        po = _create_po(owner_headers)
        body = self._base()
        body["delivery"] = {"appointment_type": "ST"}
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "validation_failed", data
        assert any("from time" in e.lower() for e in data.get("errors", [])), data

    def test_TR_missing_to_validation_fails(self, owner_headers):
        po = _create_po(owner_headers)
        body = self._base()
        body["delivery"] = {"appointment_type": "TR", "appointment_from": "09:00"}
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "validation_failed", data
        assert any("to time" in e.lower() for e in data.get("errors", [])), data

    def test_invalid_appointment_code(self, owner_headers):
        po = _create_po(owner_headers)
        body = self._base()
        body["delivery"] = {"appointment_type": "ZZ"}
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "validation_failed", data


# -------------- Direct mock contract --------------
class TestMockValidatorAppointment:
    @pytest.fixture(scope="class")
    def mock_bearer(self):
        r = requests.post(f"{BASE_URL}/api/abc-mock/oauth2/v1/token",
                          data={"grant_type": "client_credentials", "scope": "order.write"},
                          timeout=30)
        if r.status_code != 200:
            pytest.skip(f"ABC mock not reachable: {r.status_code} {r.text[:120]}")
        return r.json()["access_token"]

    def _base_order(self):
        return {
            "requestId": f"mock-req-{uuid.uuid4().hex}",
            "purchaseOrder": "P0-APPT", "branchNumber": "18",
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

    def test_reject_legacy_delivery_appointment_time(self, mock_bearer):
        order = self._base_order()
        order["dates"] = {"deliveryAppointmentTime": "09:00-12:00"}
        r = self._post(mock_bearer, order)
        assert r.status_code == 400, r.text[:300]
        assert "deliveryappointmenttime" in r.text.lower() or "deliveryappointment" in r.text.lower()

    def test_accept_valid_TR(self, mock_bearer):
        order = self._base_order()
        order["deliveryAppointment"] = {"instructionsTypeCode": "TR",
                                        "fromTime": "09:00", "toTime": "12:00"}
        r = self._post(mock_bearer, order)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["orders"][0]["confirmationNumber"].startswith("MOCK-CONF-")

    def test_accept_valid_ST(self, mock_bearer):
        order = self._base_order()
        order["deliveryAppointment"] = {"instructionsTypeCode": "ST", "fromTime": "10:30"}
        r = self._post(mock_bearer, order)
        assert r.status_code == 200, r.text[:300]

    @pytest.mark.parametrize("code", ["AT", "AM", "PM", "FS"])
    def test_accept_windowless_codes(self, mock_bearer, code):
        order = self._base_order()
        order["deliveryAppointment"] = {"instructionsTypeCode": code}
        r = self._post(mock_bearer, order)
        assert r.status_code == 200, (code, r.text[:200])

    def test_reject_ST_without_fromTime(self, mock_bearer):
        order = self._base_order()
        order["deliveryAppointment"] = {"instructionsTypeCode": "ST"}
        r = self._post(mock_bearer, order)
        assert r.status_code == 400, r.text[:300]
        assert "fromtime" in r.text.lower()

    def test_reject_TR_without_toTime(self, mock_bearer):
        order = self._base_order()
        order["deliveryAppointment"] = {"instructionsTypeCode": "TR", "fromTime": "09:00"}
        r = self._post(mock_bearer, order)
        assert r.status_code == 400, r.text[:300]
        assert "totime" in r.text.lower()

    def test_reject_invalid_code(self, mock_bearer):
        order = self._base_order()
        order["deliveryAppointment"] = {"instructionsTypeCode": "ZZ"}
        r = self._post(mock_bearer, order)
        assert r.status_code == 400, r.text[:300]
        assert "instructionstypecode" in r.text.lower()

    def test_accept_dates_deliveryRequestedFor(self, mock_bearer):
        order = self._base_order()
        order["dates"] = {"deliveryRequestedFor": "2030-01-15"}
        r = self._post(mock_bearer, order)
        assert r.status_code == 200, r.text[:300]

    def test_reject_instructions_too_long(self, mock_bearer):
        order = self._base_order()
        order["deliveryAppointment"] = {"instructionsTypeCode": "AT",
                                        "instructions": "x" * 300}
        r = self._post(mock_bearer, order)
        assert r.status_code == 400, r.text[:300]
