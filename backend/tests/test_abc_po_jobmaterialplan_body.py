"""P0 regression: JobMaterialPlan-style create_po body.

JobMaterialPlan.jsx posts to /api/purchase-orders where each line ALREADY carries
abc_item_number + abc_uom (resolved from the supplier/material relationship on the
client), but the PO-level body OMITS abc_ship_to_number / abc_branch_number.

Verifies backend/routers/purchasing.py::create_po:
  1. Defaults configured -> PO + every ABC line get abc_ship_to_number / abc_branch_number
     from AbcIntegration defaults; caller-supplied abc_item_number/abc_uom preserved;
     abc-submit-review returns no 'missing ship_to/branch'.
  2. Defaults missing -> downgrades to standard draft; abc_setup_warning mentions the
     default Ship-To / branch are not set; NO partial ABC identity persisted.
  3. Explicit body abc_ship_to_number/abc_branch_number are respected (not overwritten
     by defaults) and persisted on PO + lines.
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
OVERRIDE_SHIP_TO = "9999001"
OVERRIDE_BRANCH = "42"


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
    """Connect ABC integration (mock OAuth) and set defaults."""
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
    # Restore defaults at teardown just in case.
    requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=H,
                 json={"default_ship_to_number": DEFAULT_SHIP_TO,
                       "default_branch_number": DEFAULT_BRANCH}, timeout=30)


@pytest.fixture(scope="module")
def mapped_material_id(H):
    """Real Material linked to MOCK_ITEM (via add-to-inventory)."""
    r = requests.post(
        f"{BASE_URL}/api/integrations/abc/catalog/{MOCK_ITEM}/add-to-inventory",
        headers=H, json={}, timeout=60,
    )
    assert r.status_code == 200, f"add-to-inventory failed: {r.status_code} {r.text[:300]}"
    return r.json()["material_id"]


def _create_po(H, payload):
    return requests.post(f"{BASE_URL}/api/purchase-orders", headers=H, json=payload, timeout=30)


# -------- Test 1: JobMaterialPlan-style body auto-populates defaults --------
def test_jmp_body_no_ship_to_uses_defaults_and_is_submittable(H, mapped_material_id):
    payload = {
        "supplier_name": "ABC Supply",
        "integration_provider": "abc_supply",
        # NOTE: PO-level abc_ship_to_number / abc_branch_number intentionally omitted.
        "items": [
            {
                "material_id": mapped_material_id,
                "description": "Shingle (JMP)",
                "quantity": 7,
                "unit": "SQ",
                "unit_cost": 135.36,
                # These come from the supplier/material relationship on the client:
                "abc_item_number": MOCK_ITEM,
                "abc_uom": "SQ",
            },
        ],
    }
    r = _create_po(H, payload)
    assert r.status_code == 201, r.text[:500]
    po = r.json()
    assert po["integration_provider"] == "abc_supply", po
    assert po["abc_ship_to_number"] == DEFAULT_SHIP_TO, po
    assert po["abc_branch_number"] == DEFAULT_BRANCH, po
    assert po.get("abc_setup_warning") in (None, ""), po.get("abc_setup_warning")
    assert po["items"], po
    for ln in po["items"]:
        assert ln.get("integration_provider") == "abc_supply", ln
        assert ln.get("abc_item_number") == MOCK_ITEM, ln
        assert ln.get("abc_uom") == "SQ", ln
        assert ln.get("abc_ship_to_number") == DEFAULT_SHIP_TO, ln
        assert ln.get("abc_branch_number") == DEFAULT_BRANCH, ln

    rv = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit-review",
                       headers=H, json={"apply_price_changes": False}, timeout=60)
    assert rv.status_code == 200, f"abc-submit-review failed: {rv.status_code} {rv.text[:400]}"
    txt = str(rv.json()).lower()
    assert not ("missing" in txt and ("ship_to" in txt or "ship-to" in txt or "branch" in txt)), rv.json()
    assert "no orderable" not in txt, rv.json()


# -------- Test 2: JMP-style body with defaults missing -> downgrade ---------
def test_jmp_body_missing_defaults_downgrades(H, mapped_material_id):
    # Clear defaults temporarily.
    r = requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=H,
                     json={"default_ship_to_number": "", "default_branch_number": ""}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    try:
        payload = {
            "supplier_name": "ABC Supply",
            "integration_provider": "abc_supply",
            "items": [
                {
                    "material_id": mapped_material_id,
                    "description": "Shingle (JMP no defaults)",
                    "quantity": 3,
                    "unit": "SQ",
                    "unit_cost": 135.36,
                    "abc_item_number": MOCK_ITEM,
                    "abc_uom": "SQ",
                },
            ],
        }
        r = _create_po(H, payload)
        assert r.status_code == 201, r.text[:500]
        po = r.json()
        # Must downgrade — never create an unsubmittable ABC PO.
        assert po["integration_provider"] in (None, ""), po
        assert po["abc_ship_to_number"] in (None, ""), po
        assert po["abc_branch_number"] in (None, ""), po
        warn = (po.get("abc_setup_warning") or "").lower()
        assert warn, "abc_setup_warning must be present when defaults missing"
        assert "ship-to" in warn or "ship_to" in warn or "default" in warn, warn
        for ln in po["items"]:
            # Downgraded ABC PO must not carry partial ABC identity.
            assert ln.get("integration_provider") in (None, ""), ln
            assert ln.get("abc_item_number") in (None, ""), ln
            assert ln.get("abc_ship_to_number") in (None, ""), ln
            assert ln.get("abc_branch_number") in (None, ""), ln
    finally:
        requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=H,
                     json={"default_ship_to_number": DEFAULT_SHIP_TO,
                           "default_branch_number": DEFAULT_BRANCH}, timeout=30)


# -------- Test 3: explicit body PO-level ship_to/branch respected -----------
def test_explicit_po_ship_to_branch_not_overwritten_by_defaults(H, mapped_material_id):
    payload = {
        "supplier_name": "ABC Supply",
        "integration_provider": "abc_supply",
        "abc_ship_to_number": OVERRIDE_SHIP_TO,
        "abc_branch_number": OVERRIDE_BRANCH,
        "items": [
            {
                "material_id": mapped_material_id,
                "description": "Shingle (override)",
                "quantity": 2,
                "unit": "SQ",
                "unit_cost": 135.36,
                "abc_item_number": MOCK_ITEM,
                "abc_uom": "SQ",
            },
        ],
    }
    r = _create_po(H, payload)
    assert r.status_code == 201, r.text[:500]
    po = r.json()
    assert po["integration_provider"] == "abc_supply", po
    assert po["abc_ship_to_number"] == OVERRIDE_SHIP_TO, po
    assert po["abc_branch_number"] == OVERRIDE_BRANCH, po
    assert po.get("abc_setup_warning") in (None, ""), po.get("abc_setup_warning")
    for ln in po["items"]:
        assert ln.get("abc_ship_to_number") == OVERRIDE_SHIP_TO, ln
        assert ln.get("abc_branch_number") == OVERRIDE_BRANCH, ln
        assert ln.get("abc_item_number") == MOCK_ITEM, ln
        assert ln.get("abc_uom") == "SQ", ln
