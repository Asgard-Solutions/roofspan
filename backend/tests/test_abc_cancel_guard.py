"""P1 regression: cancelling a confirmed ABC PO must be blocked (HTTP 409).

Covers backend/routers/purchasing.py::set_status guard:
- Confirmed ABC PO (external_confirmation_number set) + status=cancelled -> 409 and PO
  status is unchanged.
- Draft ABC PO (no external_confirmation_number) + status=cancelled -> allowed.
- Non-ABC PO + status=cancelled -> allowed (regression).
- Invalid status -> 422 (regression).
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
CLIENT_ID = "mock-client-id-123456"
CLIENT_SECRET = "mock-secret-abcdef"
MOCK_ITEM = "MOCK-SHINGLE-ARCH-WW"
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
    r = requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=H,
                     json={"default_ship_to_number": DEFAULT_SHIP_TO,
                           "default_branch_number": DEFAULT_BRANCH}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    yield


@pytest.fixture(scope="module")
def mapped_material_id(H):
    r = requests.post(
        f"{BASE_URL}/api/integrations/abc/catalog/{MOCK_ITEM}/add-to-inventory",
        headers=H, json={}, timeout=60,
    )
    assert r.status_code == 200, f"add-to-inventory failed: {r.status_code} {r.text[:300]}"
    return r.json()["material_id"]


@pytest.fixture(scope="module")
def plain_material_id(H):
    name = f"TEST_plain_cancel_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{BASE_URL}/api/materials", headers=H,
                      json={"name": name, "unit": "each", "standard_cost": 12.5}, timeout=30)
    assert r.status_code == 201, r.text[:300]
    return r.json()["id"]


def _create_abc_po(H, mapped_material_id):
    payload = {
        "supplier_name": "ABC Supply",
        "integration_provider": "abc_supply",
        "items": [
            {"material_id": mapped_material_id, "description": "Shingle",
             "quantity": 5, "unit": "SQ", "unit_cost": 135.36},
        ],
    }
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=H, json=payload, timeout=30)
    assert r.status_code == 201, r.text[:400]
    return r.json()


def _submit_abc(H, po_id):
    rv = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/abc-submit-review",
                       headers=H, json={"apply_price_changes": False}, timeout=60)
    assert rv.status_code == 200, f"abc-submit-review failed: {rv.status_code} {rv.text[:400]}"
    sk = rv.json().get("submission_key") or f"sk-{uuid.uuid4().hex}"
    rs = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/abc-submit",
                       headers=H, json={"apply_price_changes": False, "submission_key": sk}, timeout=60)
    assert rs.status_code == 200, f"abc-submit failed: {rs.status_code} {rs.text[:400]}"
    return rs.json()


# ---------- Test 1: confirmed ABC PO cancel blocked ----------------------
def test_confirmed_abc_po_cancel_returns_409_and_status_unchanged(H, mapped_material_id):
    po = _create_abc_po(H, mapped_material_id)
    po_id = po["id"]
    submitted = _submit_abc(H, po_id)
    conf = submitted.get("external_confirmation_number") or submitted.get("confirmation_number")
    # Fetch canonical PO to confirm confirmation number was persisted.
    got = requests.get(f"{BASE_URL}/api/purchase-orders/{po_id}", headers=H, timeout=30).json()
    assert got.get("external_confirmation_number"), f"expected confirmation number, got: {got}"
    assert got.get("external_confirmation_number", "").startswith("MOCK-CONF") or conf, got
    prior_status = got["status"]

    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/status", headers=H,
                      json={"status": "cancelled"}, timeout=30)
    assert r.status_code == 409, f"expected 409, got {r.status_code} {r.text[:400]}"
    body = r.json()
    msg = (body.get("detail") or "").lower()
    assert "abc" in msg and ("branch" in msg or "cancel" in msg), body

    # PO status must be unchanged.
    got2 = requests.get(f"{BASE_URL}/api/purchase-orders/{po_id}", headers=H, timeout=30).json()
    assert got2["status"] == prior_status, f"status changed unexpectedly: {got2['status']}"
    assert got2["status"] != "cancelled"


# ---------- Test 2: draft ABC PO (no confirmation) cancel allowed --------
def test_draft_abc_po_without_confirmation_can_be_cancelled(H, mapped_material_id):
    po = _create_abc_po(H, mapped_material_id)
    po_id = po["id"]
    assert not po.get("external_confirmation_number"), po

    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/status", headers=H,
                      json={"status": "cancelled"}, timeout=30)
    assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text[:400]}"
    got = requests.get(f"{BASE_URL}/api/purchase-orders/{po_id}", headers=H, timeout=30).json()
    assert got["status"] == "cancelled", got


# ---------- Test 3: non-ABC PO cancel allowed (regression) --------------
def test_non_abc_po_cancel_still_works(H, plain_material_id):
    payload = {
        "supplier_name": "Local Distributor",
        "items": [
            {"material_id": plain_material_id, "description": "Nails",
             "quantity": 4, "unit": "box", "unit_cost": 8.25},
        ],
    }
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=H, json=payload, timeout=30)
    assert r.status_code == 201, r.text[:400]
    po_id = r.json()["id"]

    r2 = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/status", headers=H,
                       json={"status": "cancelled"}, timeout=30)
    assert r2.status_code == 200, r2.text[:400]
    got = requests.get(f"{BASE_URL}/api/purchase-orders/{po_id}", headers=H, timeout=30).json()
    assert got["status"] == "cancelled", got


# ---------- Test 4: invalid status still 422 on confirmed ABC PO --------
def test_invalid_status_on_confirmed_abc_po_still_422(H, mapped_material_id):
    po = _create_abc_po(H, mapped_material_id)
    po_id = po["id"]
    _submit_abc(H, po_id)
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/status", headers=H,
                      json={"status": "not_a_real_status"}, timeout=30)
    assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text[:200]}"


# ---------- Test 5: non-cancel status transition on confirmed ABC PO allowed
def test_valid_non_cancel_status_on_confirmed_abc_po_is_allowed(H, mapped_material_id):
    po = _create_abc_po(H, mapped_material_id)
    po_id = po["id"]
    _submit_abc(H, po_id)
    got = requests.get(f"{BASE_URL}/api/purchase-orders/{po_id}", headers=H, timeout=30).json()
    current = got["status"]
    # Try setting to same status (no-op) — should be 200, not blocked.
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/status", headers=H,
                      json={"status": current}, timeout=30)
    assert r.status_code == 200, f"expected 200 for non-cancel transition, got {r.status_code} {r.text[:300]}"
