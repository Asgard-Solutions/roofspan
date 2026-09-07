"""P0 contract: ABC deliveryService enum single-source-of-truth.

Covers:
  A. GET /api/purchase-orders/abc/delivery-services returns exactly the 7
     documented codes {OTG, OTR, OTW, CPU, EXP, COM, TPC} with labels
     and default 'OTG'; must NOT contain legacy OTB or WCL.
  B. POST /api/purchase-orders/{po_id}/abc-submit rejects invalid delivery_service
     ('OTB', 'WCL', 'ZZZ') with status='validation_failed' and an error mentioning
     the invalid code / delivery service.
  C. Valid codes ('OTG', 'OTR', 'CPU') result in status='confirmed' (MOCK-CONF-*).
  D. Regression: default OTG still works end-to-end.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
CLIENT_ID = "mock-client-id-123456"
CLIENT_SECRET = "mock-secret-abcdef"

EXPECTED_CODES = {"OTG", "OTR", "OTW", "CPU", "EXP", "COM", "TPC"}
LEGACY_CODES = {"OTB", "WCL"}


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
        "notes": "TEST_P0_DELIVERY_SVC", "items": [_abc_line()],
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


# ---------- A. Enum endpoint contract ----------
class TestDeliveryServicesEndpoint:

    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/purchase-orders/abc/delivery-services", timeout=30)
        assert r.status_code in (401, 403), r.text[:200]

    def test_returns_exact_seven_codes(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/purchase-orders/abc/delivery-services",
                         headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert "services" in body and "default" in body, body
        assert body["default"] == "OTG", body
        codes = {s["code"] for s in body["services"]}
        assert codes == EXPECTED_CODES, f"got {codes}"
        assert not (codes & LEGACY_CODES), f"legacy codes leaked: {codes & LEGACY_CODES}"

    def test_labels_present_and_nonempty(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/purchase-orders/abc/delivery-services",
                         headers=owner_headers, timeout=30)
        body = r.json()
        for s in body["services"]:
            assert isinstance(s.get("code"), str) and s["code"], s
            assert isinstance(s.get("label"), str) and s["label"], s

    def test_specific_labels(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/purchase-orders/abc/delivery-services",
                         headers=owner_headers, timeout=30)
        by = {s["code"]: s["label"] for s in r.json()["services"]}
        # Sanity check for a couple of key labels (case-insensitive)
        assert "ground" in by["OTG"].lower()
        assert "roof" in by["OTR"].lower()
        assert "window" in by["OTW"].lower()
        assert "customer" in by["CPU"].lower() or "pickup" in by["CPU"].lower()


# ---------- B & C. Backend validation in abc-submit ----------
class TestAbcSubmitDeliveryServiceValidation:

    def _base_body(self):
        return {"submission_key": f"p0-dsvc-{uuid.uuid4().hex}"}

    @pytest.mark.parametrize("bad", ["OTB", "WCL", "ZZZ", "xx", ""])
    def test_reject_invalid_codes(self, owner_headers, bad):
        po = _create_po(owner_headers)
        body = self._base_body()
        body["delivery_service"] = bad
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "validation_failed", (bad, data)
        errs = " ".join(data.get("errors") or []).lower()
        assert "delivery service" in errs or "delivery_service" in errs or "valid abc" in errs, data

    @pytest.mark.parametrize("code", ["OTG", "OTR", "OTW", "CPU", "EXP", "COM", "TPC"])
    def test_accept_valid_codes(self, owner_headers, code):
        po = _create_po(owner_headers)
        body = self._base_body()
        body["delivery_service"] = code
        data = _submit(owner_headers, po["id"], body)
        assert data.get("status") == "confirmed", (code, data)
        assert data.get("confirmation_number", "").startswith("MOCK-CONF-"), (code, data)

    def test_default_otg_regression_no_delivery_service_in_body(self, owner_headers):
        po = _create_po(owner_headers)
        # Do not include delivery_service -> defaults to OTG per AbcSubmitIn
        data = _submit(owner_headers, po["id"], self._base_body())
        assert data.get("status") == "confirmed", data
        assert data.get("confirmation_number", "").startswith("MOCK-CONF-"), data
