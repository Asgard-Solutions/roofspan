"""P0 regression: create_po ABC identity resolution + abc_setup_warning fallback.

Verifies the fix in POST /api/purchase-orders (backend/routers/purchasing.py::create_po):
  1. When ABC integration has default Ship-To/branch AND the referenced Material has an
     ABC mapping (linked via /catalog/{item_number}/add-to-inventory), a PO created with
     integration_provider='abc_supply' and lines that only pass material_id is enriched
     server-side with abc_item_number, abc_uom, abc_ship_to_number, abc_branch_number,
     and passes abc-submit-review (no missing ship_to/branch or 'no orderable line').
  2. Unmapped material -> downgraded to a standard draft (integration_provider=None,
     abc_setup_warning mentions the item(s) with no ABC catalog mapping, lines carry
     NO partial ABC identity).
  3. Mapped material but ABC default Ship-To/branch not configured -> downgraded to a
     standard draft with abc_setup_warning mentioning the missing default Ship-To/branch.
  4. Non-ABC PO (integration_provider=null) is unaffected: line passthrough values are
     preserved and abc_setup_warning is None.
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


# --- helpers ---
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
    """Connect ABC to sandbox mock server and set defaults."""
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
    # Set defaults for positive test.
    r = requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=H,
                     json={"default_ship_to_number": DEFAULT_SHIP_TO,
                           "default_branch_number": DEFAULT_BRANCH}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    yield


@pytest.fixture(scope="module")
def mapped_material_id(H):
    """Create/link a Material to the ABC catalog item using the real endpoint."""
    r = requests.post(
        f"{BASE_URL}/api/integrations/abc/catalog/{MOCK_ITEM}/add-to-inventory",
        headers=H, json={}, timeout=60,
    )
    assert r.status_code == 200, f"add-to-inventory failed: {r.status_code} {r.text[:300]}"
    return r.json()["material_id"]


@pytest.fixture(scope="module")
def plain_material_id(H):
    """Create a Material with no ABC mapping."""
    name = f"TEST_plain_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{BASE_URL}/api/materials", headers=H,
                      json={"name": name, "unit": "each", "standard_cost": 12.5}, timeout=30)
    assert r.status_code == 201, r.text[:300]
    return r.json()["id"]


def _create_po(H, payload):
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=H, json=payload, timeout=30)
    return r


# ---------- Test 1: positive path -----------------------------------------
def test_positive_abc_po_is_fully_populated_and_submittable(H, mapped_material_id):
    payload = {
        "supplier_name": "ABC Supply",
        "integration_provider": "abc_supply",
        "items": [
            {"material_id": mapped_material_id, "description": "Shingle",
             "quantity": 5, "unit": "SQ", "unit_cost": 135.36},
        ],
    }
    r = _create_po(H, payload)
    assert r.status_code == 201, r.text[:400]
    po = r.json()
    assert po["integration_provider"] == "abc_supply", po
    assert po["abc_ship_to_number"] == DEFAULT_SHIP_TO
    assert po["abc_branch_number"] == DEFAULT_BRANCH
    assert po.get("abc_setup_warning") in (None, ""), po.get("abc_setup_warning")
    assert po["items"], "PO must have lines"
    for ln in po["items"]:
        assert ln.get("integration_provider") == "abc_supply", ln
        assert ln.get("abc_item_number"), f"line missing abc_item_number: {ln}"
        assert ln.get("abc_uom"), f"line missing abc_uom: {ln}"
        assert ln.get("abc_ship_to_number") == DEFAULT_SHIP_TO
        assert ln.get("abc_branch_number") == DEFAULT_BRANCH

    # Should pass abc-submit-review (no ship_to/branch or 'no orderable' errors)
    rv = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit-review",
                       headers=H, json={"apply_price_changes": False}, timeout=60)
    # Endpoint should not error out with a validation problem; accept 200 OR non-4xx.
    assert rv.status_code == 200, f"abc-submit-review failed: {rv.status_code} {rv.text[:400]}"
    body = rv.json()
    # Common shape: contains no fatal missing config markers.
    txt = str(body).lower()
    assert "ship_to" not in txt or "missing" not in txt, body
    assert "no orderable" not in txt, body


# ---------- Test 2: unmapped material -> downgrade ------------------------
def test_unmapped_material_downgrades_to_standard_draft(H, plain_material_id):
    payload = {
        "supplier_name": "ABC Supply",
        "integration_provider": "abc_supply",
        "items": [
            {"material_id": plain_material_id, "description": "Random widget",
             "quantity": 2, "unit": "each", "unit_cost": 10.0},
        ],
    }
    r = _create_po(H, payload)
    assert r.status_code == 201, r.text[:400]
    po = r.json()
    assert po["integration_provider"] is None, po
    assert po["abc_ship_to_number"] in (None, ""), po
    assert po["abc_branch_number"] in (None, ""), po
    warn = po.get("abc_setup_warning") or ""
    assert warn, "abc_setup_warning must be present"
    assert "ABC Supply catalog mapping" in warn or "no ABC" in warn.lower(), warn
    for ln in po["items"]:
        assert ln.get("integration_provider") in (None, ""), ln
        assert ln.get("abc_item_number") in (None, ""), ln
        assert ln.get("abc_ship_to_number") in (None, ""), ln
        assert ln.get("abc_branch_number") in (None, ""), ln


# ---------- Test 3: mapped material but defaults missing ------------------
def test_missing_defaults_downgrades_even_if_mapped(H, mapped_material_id):
    # Temporarily clear defaults.
    r = requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=H,
                     json={"default_ship_to_number": "", "default_branch_number": ""}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    try:
        payload = {
            "supplier_name": "ABC Supply",
            "integration_provider": "abc_supply",
            "items": [
                {"material_id": mapped_material_id, "description": "Shingle",
                 "quantity": 3, "unit": "SQ", "unit_cost": 135.36},
            ],
        }
        r = _create_po(H, payload)
        assert r.status_code == 201, r.text[:400]
        po = r.json()
        assert po["integration_provider"] is None, po
        warn = po.get("abc_setup_warning") or ""
        assert warn, "abc_setup_warning must be present when defaults missing"
        assert "ship-to" in warn.lower() or "ship_to" in warn.lower() or "default" in warn.lower(), warn
        for ln in po["items"]:
            assert ln.get("abc_item_number") in (None, ""), ln
    finally:
        # Restore defaults so subsequent tests aren't affected.
        requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=H,
                     json={"default_ship_to_number": DEFAULT_SHIP_TO,
                           "default_branch_number": DEFAULT_BRANCH}, timeout=30)


# ---------- Test 4: normal (non-ABC) PO is unaffected ---------------------
def test_normal_po_regression_no_warning_and_passthrough(H, plain_material_id):
    payload = {
        "supplier_name": "Local Distributor",
        # integration_provider omitted -> normal PO
        "items": [
            {"material_id": plain_material_id, "description": "Nails",
             "quantity": 4, "unit": "box", "unit_cost": 8.25},
        ],
    }
    r = _create_po(H, payload)
    assert r.status_code == 201, r.text[:400]
    po = r.json()
    assert po["integration_provider"] in (None, ""), po
    assert po.get("abc_setup_warning") in (None, ""), po
    assert po["items"] and po["items"][0]["description"] == "Nails"
    assert po["items"][0]["unit_cost"] == 8.25
    assert po["items"][0].get("abc_item_number") in (None, ""), po["items"][0]
