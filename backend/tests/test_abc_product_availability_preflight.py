"""ABC Product Availability preflight (SEPARATE from pricing).

Regression tests for the ABC ordering-gap fix: prior to abc-submit the server must call the
Product Availability API for every ABC line and:

  * A. Confirm submits when the item IS available at the selected branch.
  * B. BLOCK (status='validation_failed', no confirmation, no durable pending submission,
       no Place Order sent) when the item is PRICED but Product Availability reports it not
       orderable at the selected branch (MOCK-UNAVAIL-AT-18 at branch 18).
  * C. Dimensional item + a valid available length (MOCK-DRIP-EDGE-DIM length '10' at 18) confirms.
  * D. Dimensional item + an UNAVAILABLE length (length '99' at 18) is BLOCKED with an explicit
       'variation is not currently available' message and no order is sent.
  * E. Availability API failure (MOCK-AVAIL-ERR -> 503) fails closed with a retryable error.
       NO Place Order is sent and NO durable pending AbcOrderSubmission is created.
  * F. Recovery — a PO that failed availability can be replaced with a healthy PO and submitted
       to a confirmation using the SAME submission_key (proving no stuck pending was created).

Run single-worker: shares the ABC integration singleton with the other ABC contract suites.
"""
import os
import uuid

import pytest
import requests


BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
CLIENT_ID = "mock-client-id-123456"
CLIENT_SECRET = "mock-secret-abcdef"
DEFAULT_SHIP_TO = "1163698"
DEFAULT_BRANCH = "18"

ITEM_HAPPY = "MOCK-SHINGLE-ARCH-WW"          # priced + available at branch 18
ITEM_UNAVAIL = "MOCK-UNAVAIL-AT-18"          # priced but Product Availability says only 409
ITEM_DIM = "MOCK-DRIP-EDGE-DIM"              # dimensional; branch 18 lengths [10, 12]
ITEM_AVAIL_ERR = "MOCK-AVAIL-ERR"            # Product Availability endpoint returns 503


# --------------------------- helpers ---------------------------
def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def H():
    return {"Authorization": f"Bearer {_login(*OWNER)}"}


@pytest.fixture(scope="module", autouse=True)
def _connect_abc(H):
    """Connect ABC (mock OAuth) + set defaults; reused across the suite."""
    requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=H,
                 json={"environment": "sandbox", "client_id": CLIENT_ID}, timeout=30)
    requests.put(f"{BASE_URL}/api/integrations/abc/config/secret", headers=H,
                 json={"client_secret": CLIENT_SECRET}, timeout=30)
    requests.post(f"{BASE_URL}/api/integrations/abc/disconnect", headers=H, timeout=30)
    r = requests.post(f"{BASE_URL}/api/integrations/abc/connect", headers=H, timeout=30)
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
    st = requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=H, timeout=30).json()
    assert st.get("status") == "connected", st
    r = requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=H,
                     json={"default_ship_to_number": DEFAULT_SHIP_TO,
                           "default_branch_number": DEFAULT_BRANCH}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    yield


def _map(H, item_number):
    r = requests.post(
        f"{BASE_URL}/api/integrations/abc/catalog/{item_number}/add-to-inventory",
        headers=H, json={}, timeout=60)
    assert r.status_code == 200, f"add-to-inventory {item_number}: {r.status_code} {r.text[:300]}"
    return r.json()["material_id"]


@pytest.fixture(scope="module")
def mat_happy(H):
    return _map(H, ITEM_HAPPY)


@pytest.fixture(scope="module")
def mat_unavail(H):
    return _map(H, ITEM_UNAVAIL)


@pytest.fixture(scope="module")
def mat_dim(H):
    return _map(H, ITEM_DIM)


@pytest.fixture(scope="module")
def mat_availerr(H):
    return _map(H, ITEM_AVAIL_ERR)


def _abc_line(item_number, *, material_id=None, uom="EA", qty=1, unit_cost=1.0,
              length_value=None, branch=DEFAULT_BRANCH, ship_to=DEFAULT_SHIP_TO):
    line = {
        "description": item_number, "quantity": qty, "unit": uom, "unit_cost": unit_cost,
        "integration_provider": "abc_supply", "abc_item_number": item_number,
        "abc_branch_number": branch, "abc_ship_to_number": ship_to,
        "abc_uom": uom, "abc_price": unit_cost, "abc_price_status": "priced",
        "pricing_source": "abc",
    }
    if material_id:
        line["material_id"] = material_id
    if length_value is not None:
        line["abc_variation"] = {"value": str(length_value), "uom": "ft"}
    return line


def _abc_po(H, items, ship_to=DEFAULT_SHIP_TO, branch=DEFAULT_BRANCH, notes="TEST_AVAIL_PREFLIGHT"):
    payload = {
        "supplier_name": "ABC Supply", "integration_provider": "abc_supply",
        "abc_ship_to_number": ship_to, "abc_branch_number": branch,
        "notes": notes, "items": items,
    }
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=H, json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text[:400]
    return r.json()


def _review(H, po_id, apply_price_changes=False):
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/abc-submit-review",
                      headers=H, json={"apply_price_changes": apply_price_changes}, timeout=60)
    assert r.status_code == 200, r.text[:400]
    return r.json()


def _submit(H, po_id, submission_key=None, accept_price_changes=True):
    body = {
        "submission_key": submission_key or uuid.uuid4().hex,
        "accept_price_changes": accept_price_changes,
        "delivery_service": "OTG",
    }
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/abc-submit",
                      headers=H, json=body, timeout=60)
    assert r.status_code == 200, f"abc-submit: {r.status_code} {r.text[:400]}"
    return r.json(), body["submission_key"]


def _has_err(data, needles):
    errs = " | ".join((data.get("errors") or []) + [data.get("message") or ""]).lower()
    return any(n.lower() in errs for n in needles), errs


# ============================================================
# A. Available item at selected branch -> confirms
# ============================================================
def test_A_available_item_confirms(H, mat_happy):
    po = _abc_po(H, [_abc_line(ITEM_HAPPY, material_id=mat_happy, uom="SQ",
                               qty=3, unit_cost=135.36)])
    review = _review(H, po["id"])
    assert not review.get("errors"), review
    data, _ = _submit(H, po["id"])
    assert data.get("status") == "confirmed", data
    assert (data.get("confirmation_number") or "").startswith("MOCK-CONF-"), data


# ============================================================
# B. Priced but UNAVAILABLE at selected branch -> blocked, no order
# ============================================================
def test_B_priced_but_unavailable_at_branch_blocks(H, mat_unavail):
    po = _abc_po(H, [_abc_line(ITEM_UNAVAIL, material_id=mat_unavail, uom="EA",
                               qty=2, unit_cost=75.0)])
    # abc-submit-review must surface an availability error (does not raise HTTP error).
    review = _review(H, po["id"])
    ok_review, review_errs = _has_err({"errors": review.get("errors") or []},
                                      ["not currently available for ordering from branch"])
    assert ok_review, f"review did not report availability error: {review_errs} :: {review}"

    # abc-submit must return validation_failed with no confirmation and no order sent.
    data, _ = _submit(H, po["id"])
    assert data.get("status") == "validation_failed", data
    assert not data.get("confirmation_number"), data
    ok, errs = _has_err(data, [
        f"{ITEM_UNAVAIL} is not currently available for ordering from branch {DEFAULT_BRANCH}"])
    assert ok, f"unexpected/missing availability error: {errs} :: {data}"


# ============================================================
# C. Dimensional item with a valid available length -> confirms
# ============================================================
def test_C_dimensional_valid_length_confirms(H, mat_dim):
    line = _abc_line(ITEM_DIM, material_id=mat_dim, uom="PC", qty=4, unit_cost=65.0,
                     length_value="10")
    po = _abc_po(H, [line])
    # Price for length 10 is 6.5 * 10 = 65.0 -> matches unit_cost so no price_changed.
    review = _review(H, po["id"], apply_price_changes=True)
    assert not review.get("errors"), review
    data, _ = _submit(H, po["id"])
    assert data.get("status") == "confirmed", data
    assert (data.get("confirmation_number") or "").startswith("MOCK-CONF-"), data


# ============================================================
# D. Dimensional item with UNAVAILABLE length -> blocked, no order
# ============================================================
def test_D_dimensional_unavailable_length_blocks(H, mat_dim):
    line = _abc_line(ITEM_DIM, material_id=mat_dim, uom="PC", qty=1, unit_cost=6.5 * 99,
                     length_value="99")
    po = _abc_po(H, [line])
    data, _ = _submit(H, po["id"])
    assert data.get("status") == "validation_failed", data
    assert not data.get("confirmation_number"), data
    ok, errs = _has_err(data, [
        f"{ITEM_DIM} is available at branch {DEFAULT_BRANCH}, but the selected 99",
        "variation is not currently available",
    ])
    assert ok, f"expected dimensional length block, got: {errs} :: {data}"


# ============================================================
# E. Availability API failure (503) -> validation_failed, no pending, no order
# ============================================================
def test_E_availability_transport_error_fails_closed(H, mat_availerr):
    po = _abc_po(H, [_abc_line(ITEM_AVAIL_ERR, material_id=mat_availerr, uom="EA",
                               qty=1, unit_cost=50.0)])
    key = uuid.uuid4().hex
    data, _ = _submit(H, po["id"], submission_key=key)
    assert data.get("status") == "validation_failed", data
    assert not data.get("confirmation_number"), data
    ok, errs = _has_err(data, [
        "could not verify abc product availability",
        "try submitting again",
    ])
    assert ok, f"expected retryable availability error, got: {errs} :: {data}"

    # Retry with the SAME submission_key must NOT be short-circuited by a stuck pending row —
    # since the service is still failing, we get validation_failed again (never 'already_submitted').
    data2, _ = _submit(H, po["id"], submission_key=key)
    assert data2.get("status") == "validation_failed", data2
    assert not data2.get("confirmation_number"), data2


# ============================================================
# F. Recovery — corrected/replacement PO submits normally using the same submission_key
# ============================================================
def test_F_recovery_after_availability_failure(H, mat_availerr, mat_happy):
    # Start with a PO that fails availability (503 path).
    bad_po = _abc_po(H, [_abc_line(ITEM_AVAIL_ERR, material_id=mat_availerr, uom="EA",
                                   qty=1, unit_cost=50.0)])
    key = uuid.uuid4().hex
    d1, _ = _submit(H, bad_po["id"], submission_key=key)
    assert d1.get("status") == "validation_failed", d1

    # "Fix" by submitting a fresh healthy PO with the SAME submission_key. If the failed
    # preflight had created a stuck pending submission tied to this key, this would collide
    # or return a stale status; instead it must confirm cleanly.
    good_po = _abc_po(H, [_abc_line(ITEM_HAPPY, material_id=mat_happy, uom="SQ",
                                    qty=1, unit_cost=135.36)])
    _review(H, good_po["id"])
    d2, _ = _submit(H, good_po["id"], submission_key=key)
    assert d2.get("status") == "confirmed", d2
    assert (d2.get("confirmation_number") or "").startswith("MOCK-CONF-"), d2


# ============================================================
# Regression — pricing-based unavailability ($0 price) still blocks
# ============================================================
def test_regression_zero_price_still_blocks(H):
    """MOCK-RIDGE-CAP-NOPRICE prices at $0.00 -> pricing marks unavailable BEFORE the
    availability preflight even runs. Verifies the pricing gate is intact."""
    mat = _map(H, "MOCK-RIDGE-CAP-NOPRICE")
    po = _abc_po(H, [_abc_line("MOCK-RIDGE-CAP-NOPRICE", material_id=mat, uom="BD",
                               qty=1, unit_cost=10.0)])
    data, _ = _submit(H, po["id"])
    assert data.get("status") == "validation_failed", data
    assert not data.get("confirmation_number"), data
