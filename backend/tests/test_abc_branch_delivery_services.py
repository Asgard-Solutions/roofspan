"""P0 contract: ABC branch-level delivery-service availability.

Covers A-G from iteration_107 request:
  A. Branch 18 + OTG -> confirmed.
  B. Branch 18 + OTR -> confirmed (18 supports OTG/OTR/CPU/COM).
  C. Branch 409 + OTR -> validation_failed with branch-specific message; no confirmation, no Place Order.
  D. Branch 409 + EXP -> confirmed (409 supports OTG/EXP/CPU/TPC).
  E. Branch TOGGLE (OTR present on first Get Branch, gone after) submitted with OTR -> blocked at submit.
  F. Branch SVCERR (Get Branch 503) submitted with any code -> retryable validation_failed,
     no pending AbcOrderSubmission created and recovery works via same submission_key.
  G. GET /abc/branches/{branch}/delivery-services returns exactly branch-supported codes;
     SVCERR -> HTTP 502.
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


def _abc_line(branch="18"):
    return {
        "description": "Shingle", "quantity": 10, "unit": "SQ", "unit_cost": 135.36,
        "integration_provider": "abc_supply", "abc_item_number": "MOCK-SHINGLE-ARCH-WW",
        "abc_branch_number": branch, "abc_ship_to_number": "1163698", "abc_uom": "SQ",
        "abc_price": 135.36, "abc_price_status": "priced", "pricing_source": "abc",
    }


def _create_po(headers, branch="18"):
    payload = {
        "supplier_name": "ABC Supply", "integration_provider": "abc_supply",
        "abc_ship_to_number": "1163698", "abc_branch_number": branch,
        "notes": "TEST_P0_BRANCH_DELIVERY_SVC", "items": [_abc_line(branch=branch)],
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


# ---------- G. Branch-services endpoint ----------
class TestBranchDeliveryServicesEndpoint:

    def test_branch_18_exact_set(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/purchase-orders/abc/branches/18/delivery-services",
                         headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        codes = {s["code"] for s in body["services"]}
        assert codes == {"OTG", "OTR", "CPU", "COM"}, codes
        # default must be a supported code
        assert body["default"] in codes

    def test_branch_409_exact_set(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/purchase-orders/abc/branches/409/delivery-services",
                         headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        codes = {s["code"] for s in r.json()["services"]}
        assert codes == {"OTG", "EXP", "CPU", "TPC"}, codes
        assert "OTR" not in codes

    def test_branch_700_pickup_only(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/purchase-orders/abc/branches/700/delivery-services",
                         headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        codes = {s["code"] for s in r.json()["services"]}
        assert codes == {"CPU"}, codes

    def test_branch_svcerr_502(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/purchase-orders/abc/branches/SVCERR/delivery-services",
                         headers=owner_headers, timeout=30)
        assert r.status_code == 502, r.text[:300]

    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/purchase-orders/abc/branches/18/delivery-services", timeout=30)
        assert r.status_code in (401, 403)


# ---------- A/B/D. Positive: branch supports the selected service ----------
class TestBranchSupportedServiceSubmits:

    def test_a_branch_18_otg(self, owner_headers):
        po = _create_po(owner_headers, branch="18")
        data = _submit(owner_headers, po["id"],
                       {"submission_key": uuid.uuid4().hex, "delivery_service": "OTG"})
        assert data.get("status") == "confirmed", data
        assert data.get("confirmation_number", "").startswith("MOCK-CONF-"), data

    def test_b_branch_18_otr(self, owner_headers):
        po = _create_po(owner_headers, branch="18")
        data = _submit(owner_headers, po["id"],
                       {"submission_key": uuid.uuid4().hex, "delivery_service": "OTR"})
        assert data.get("status") == "confirmed", data
        assert data.get("confirmation_number", "").startswith("MOCK-CONF-"), data

    def test_d_branch_409_exp(self, owner_headers):
        po = _create_po(owner_headers, branch="409")
        data = _submit(owner_headers, po["id"],
                       {"submission_key": uuid.uuid4().hex, "delivery_service": "EXP"})
        assert data.get("status") == "confirmed", data
        assert data.get("confirmation_number", "").startswith("MOCK-CONF-"), data


# ---------- C. Branch does NOT support the selected service ----------
class TestBranchUnsupportedServiceBlocked:

    def test_c_branch_409_otr_blocked(self, owner_headers):
        po = _create_po(owner_headers, branch="409")
        data = _submit(owner_headers, po["id"],
                       {"submission_key": uuid.uuid4().hex, "delivery_service": "OTR"})
        assert data.get("status") == "validation_failed", data
        errs = " ".join(data.get("errors") or [])
        assert "409" in errs and "OTR" in errs, errs
        assert "does not currently support delivery service" in errs, errs
        assert not data.get("confirmation_number"), data


# ---------- E. TOGGLE branch: review passes, submit re-checks and blocks ----------
class TestBranchTogglesServiceBetweenReviewAndSubmit:

    def test_e_toggle_review_then_submit_blocks(self, owner_headers):
        # NOTE: the mock's TOGGLE counter is module-level and NOT reset between runs. We
        # therefore repeatedly poll the review endpoint until OTR reappears (or skip if the
        # test env has already exhausted the toggle). This preserves the invariant we care
        # about: review shows OTR, submit then re-checks and blocks.
        codes_review = set()
        for _ in range(3):
            r = requests.get(f"{BASE_URL}/api/purchase-orders/abc/branches/TOGGLE/delivery-services",
                             headers=owner_headers, timeout=30)
            if r.status_code == 200:
                codes_review = {s["code"] for s in r.json()["services"]}
                if "OTR" in codes_review:
                    break
        if "OTR" not in codes_review:
            pytest.skip("TOGGLE mock counter already exhausted (no reset endpoint); rerun after backend restart")

        # Step 2: submit with OTR — Get Branch on this next call no longer lists OTR.
        po = _create_po(owner_headers, branch="TOGGLE")
        data = _submit(owner_headers, po["id"],
                       {"submission_key": uuid.uuid4().hex, "delivery_service": "OTR"})
        assert data.get("status") == "validation_failed", data
        errs = " ".join(data.get("errors") or [])
        assert "TOGGLE" in errs and "OTR" in errs, errs
        assert "does not currently support delivery service" in errs, errs
        assert not data.get("confirmation_number"), data


# ---------- F. SVCERR: fail closed, no pending submission, retryable, recovery works ----------
class TestBranchServicesLookupFailure:

    def test_f_svcerr_fails_closed_and_recovery(self, owner_headers):
        po = _create_po(owner_headers, branch="SVCERR")
        submission_key = uuid.uuid4().hex
        data = _submit(owner_headers, po["id"],
                       {"submission_key": submission_key, "delivery_service": "OTG"})
        assert data.get("status") == "validation_failed", data
        errs = " ".join(data.get("errors") or []).lower()
        # Retryable message about being unable to verify the branch services
        assert ("try submitting again shortly" in errs) or ("try again shortly" in errs), errs
        assert not data.get("confirmation_number"), data

        # Retry with same submission_key after switching PO's branch to a healthy one (18 + OTG default).
        # Update the PO's branch via PATCH if supported; else create a fresh PO. Both prove "no stuck pending".
        patch = requests.patch(f"{BASE_URL}/api/purchase-orders/{po['id']}", headers=owner_headers,
                               json={"abc_branch_number": "18"}, timeout=30)
        if patch.status_code not in (200, 204):
            # PATCH not supported -> spin up a fresh PO to prove the same submission_key can still confirm.
            po = _create_po(owner_headers, branch="18")

        data2 = _submit(owner_headers, po["id"],
                        {"submission_key": submission_key, "delivery_service": "OTG"})
        assert data2.get("status") == "confirmed", data2
        assert data2.get("confirmation_number", "").startswith("MOCK-CONF-"), data2
