"""P1 contract: server-side ABC orderability preflight in POST /purchase-orders/{id}/abc-submit.

The preflight fetches the Ship-To from ABC immediately before placing an order and blocks the
submit (status='validation_failed', no confirmation, no durable pending submission) when:
  * the Ship-To no longer exists at ABC (mock: number startswith 'MISSING' -> {}),
  * its status is not active/open (mock: '9999999' -> inactive, empty branches),
  * it is on credit hold (isSellable=false) (mock: number startswith 'CREDITHOLD'),
  * the selected branch is no longer associated with the Ship-To (mock: number startswith
    'NOBRANCH' returns branches without 18).

Also asserts the happy path 1163698/branch 18 still confirms (regression) and that after a
blocked submit the PO can be retried (no stuck 'pending' AbcOrderSubmission).
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
    requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=H,
                 json={"default_ship_to_number": DEFAULT_SHIP_TO,
                       "default_branch_number": DEFAULT_BRANCH}, timeout=30)
    yield


def _abc_line():
    return {
        "description": "Shingle", "quantity": 3, "unit": "SQ", "unit_cost": 135.36,
        "integration_provider": "abc_supply", "abc_item_number": "MOCK-SHINGLE-ARCH-WW",
        "abc_branch_number": DEFAULT_BRANCH, "abc_ship_to_number": DEFAULT_SHIP_TO, "abc_uom": "SQ",
        "abc_price": 135.36, "abc_price_status": "priced", "pricing_source": "abc",
    }


def _create_po(H, ship_to=DEFAULT_SHIP_TO, branch=DEFAULT_BRANCH, notes="TEST_P1_PREFLIGHT"):
    line = _abc_line()
    line["abc_ship_to_number"] = ship_to
    line["abc_branch_number"] = branch
    payload = {
        "supplier_name": "ABC Supply", "integration_provider": "abc_supply",
        "abc_ship_to_number": ship_to, "abc_branch_number": branch,
        "notes": notes, "items": [line],
    }
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=H, json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text[:400]
    po = r.json()
    # create_po should preserve the explicit ship_to/branch even for CREDITHOLD*/NOBRANCH*/etc.
    assert po.get("abc_ship_to_number") == ship_to, po
    assert po.get("abc_branch_number") == branch, po
    return po


def _submit(H, po_id, body=None):
    body = body or {"submission_key": uuid.uuid4().hex}
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/abc-submit",
                      headers=H, json=body, timeout=60)
    assert r.status_code == 200, r.text[:400]
    return r.json()


# -------- Happy path regression --------
def test_happy_path_default_ship_to_confirms(H):
    po = _create_po(H)
    data = _submit(H, po["id"])
    assert data.get("status") == "confirmed", data
    assert (data.get("confirmation_number") or "").startswith("MOCK-CONF-"), data


# -------- Preflight failures --------
def _assert_blocked(data, needle_options):
    assert data.get("status") == "validation_failed", data
    assert not data.get("confirmation_number"), data
    errs = " | ".join(data.get("errors") or []).lower()
    assert any(n.lower() in errs for n in needle_options), (data, needle_options)


def test_credit_hold_blocks_submit(H):
    po = _create_po(H, ship_to=f"CREDITHOLD{DEFAULT_SHIP_TO}")
    data = _submit(H, po["id"])
    _assert_blocked(data, ["credit hold", "not sellable"])


def test_inactive_ship_to_blocks_submit(H):
    po = _create_po(H, ship_to="9999999")
    data = _submit(H, po["id"])
    _assert_blocked(data, ["inactive", "cannot place orders"])


def test_branch_not_associated_blocks_submit(H):
    po = _create_po(H, ship_to=f"NOBRANCH{DEFAULT_SHIP_TO}", branch=DEFAULT_BRANCH)
    data = _submit(H, po["id"])
    _assert_blocked(data, ["no longer associated"])


def test_missing_ship_to_blocks_submit(H):
    po = _create_po(H, ship_to=f"MISSING{DEFAULT_SHIP_TO}")
    data = _submit(H, po["id"])
    _assert_blocked(data, ["no longer exists"])


# -------- No stuck pending: retry after fixing the account succeeds --------
def test_blocked_submit_leaves_no_stuck_pending_and_retry_works(H):
    """A blocked preflight must NOT create a durable pending AbcOrderSubmission.
    Reusing the SAME submission_key after fixing the Ship-To must submit fresh
    and confirm — proving the failed preflight didn't leave a stuck record."""
    po = _create_po(H, ship_to=f"CREDITHOLD{DEFAULT_SHIP_TO}")
    key = uuid.uuid4().hex
    data1 = _submit(H, po["id"], {"submission_key": key})
    _assert_blocked(data1, ["credit hold", "not sellable"])

    # "Fix" the account by pointing the PO at the healthy default Ship-To.
    # Try common in-place update; if unsupported, recreate the PO.
    r = requests.patch(f"{BASE_URL}/api/purchase-orders/{po['id']}",
                       headers=H, json={"abc_ship_to_number": DEFAULT_SHIP_TO}, timeout=30)
    if r.status_code >= 400:
        # Fallback: create a fresh healthy PO. Still validates the "no stuck pending"
        # invariant because the previous PO's key was never persisted.
        po = _create_po(H)
    else:
        po = r.json()
        assert po.get("abc_ship_to_number") == DEFAULT_SHIP_TO, po

    data2 = _submit(H, po["id"], {"submission_key": key})
    # If a stuck 'pending' had been created, we'd get {'status':'pending', ...} back.
    assert data2.get("status") == "confirmed", data2
    assert (data2.get("confirmation_number") or "").startswith("MOCK-CONF-"), data2
