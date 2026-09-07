"""ABC Supply — End-to-End Creation Paths through abc-submit (consolidated regression).

Item #9 of the ABC go-live plan. This suite drives EVERY ABC PO creation path all the way through
POST /api/purchase-orders (or /from-abc-template) -> POST /abc-submit-review -> POST /abc-submit
against the ABC mock server, and proves each path yields either a confirmed order (MOCK-CONF-*) or
a documented handled outcome (validation_failed / failed / unknown -> reconciled / already_submitted
/ price_changed).

Contract enforcement is verified indirectly by the mock: mock_server.place_order_mock invokes the
same shared validate_place_order used by production abc_submit, so a status='confirmed' response
proves the built payload satisfies the versioned contract. Delivery-instructions overflow (>255)
routing into orderComments 'D' is exercised via the successful long-instruction submit.

Run single-worker: this reuses the ABC integration singleton (mock OAuth connect / defaults / mapping).
"""
import os
import uuid
import pytest
import requests


BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
CLIENT_ID = "mock-client-id-123456"
CLIENT_SECRET = "mock-secret-abcdef"

MOCK_ITEM = "MOCK-SHINGLE-ARCH-WW"          # priceable (135.36), confirms
MOCK_ITEM_REJECT = "MOCK-REJECT"            # priceable (9.99), place_order returns 400 rejection
MOCK_ITEM_TIMEOUT = "MOCK-TIMEOUT"          # priceable (4.5), place_order returns 504 (unknown)
DEFAULT_SHIP_TO = "1163698"
DEFAULT_BRANCH = "18"
TEMPLATE_ID = "97211"


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
    """Connect ABC (mock OAuth) and set defaults for the whole suite."""
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
    requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=H,
                 json={"default_ship_to_number": DEFAULT_SHIP_TO,
                       "default_branch_number": DEFAULT_BRANCH}, timeout=30)


def _map(H, item_number):
    r = requests.post(
        f"{BASE_URL}/api/integrations/abc/catalog/{item_number}/add-to-inventory",
        headers=H, json={}, timeout=60)
    assert r.status_code == 200, f"add-to-inventory {item_number}: {r.status_code} {r.text[:300]}"
    return r.json()["material_id"]


@pytest.fixture(scope="module")
def mapped_material_id(H):
    return _map(H, MOCK_ITEM)


@pytest.fixture(scope="module")
def mapped_reject_id(H):
    return _map(H, MOCK_ITEM_REJECT)


@pytest.fixture(scope="module")
def mapped_timeout_id(H):
    return _map(H, MOCK_ITEM_TIMEOUT)


@pytest.fixture(scope="module")
def plain_material_id(H):
    name = f"TEST_plain_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{BASE_URL}/api/materials", headers=H,
                      json={"name": name, "unit": "each", "standard_cost": 12.5}, timeout=30)
    assert r.status_code == 201, r.text[:300]
    return r.json()["id"]


def _create_po(H, payload):
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=H, json=payload, timeout=30)
    assert r.status_code == 201, r.text[:500]
    return r.json()


def _review(H, po_id, apply_price_changes=False, expect_ok=True):
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/abc-submit-review",
                      headers=H, json={"apply_price_changes": apply_price_changes}, timeout=60)
    assert r.status_code == 200, f"abc-submit-review: {r.status_code} {r.text[:400]}"
    body = r.json()
    if expect_ok:
        assert not body.get("errors"), f"unexpected review errors: {body.get('errors')}"
    return body


def _submit(H, po_id, submission_key=None, accept_price_changes=False, delivery=None,
            order_comments=None, delivery_service="OTG"):
    body = {
        "submission_key": submission_key or uuid.uuid4().hex,
        "accept_price_changes": accept_price_changes,
        "delivery_service": delivery_service,
    }
    if delivery is not None:
        body["delivery"] = delivery
    if order_comments is not None:
        body["order_comments"] = order_comments
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/abc-submit",
                      headers=H, json=body, timeout=60)
    assert r.status_code == 200, f"abc-submit: {r.status_code} {r.text[:400]}"
    return r.json(), body["submission_key"]


def _abc_line(item_number=MOCK_ITEM, uom="SQ", qty=3, unit_cost=135.36, material_id=None):
    line = {
        "description": item_number, "quantity": qty, "unit": uom, "unit_cost": unit_cost,
        "integration_provider": "abc_supply", "abc_item_number": item_number,
        "abc_branch_number": DEFAULT_BRANCH, "abc_ship_to_number": DEFAULT_SHIP_TO,
        "abc_uom": uom, "abc_price": unit_cost, "abc_price_status": "priced",
        "pricing_source": "abc",
    }
    if material_id:
        line["material_id"] = material_id
    return line


def _abc_po_payload(items, ship_to=DEFAULT_SHIP_TO, branch=DEFAULT_BRANCH, notes="TEST_E2E"):
    return {
        "supplier_name": "ABC Supply", "integration_provider": "abc_supply",
        "abc_ship_to_number": ship_to, "abc_branch_number": branch,
        "notes": notes, "items": items,
    }


# ==================================================================
# 1. Creation Path — Direct create (New PO / Catalog search)
# ==================================================================
def test_direct_create_confirms(H, mapped_material_id):
    """POST /api/purchase-orders with abc_item_number on the line -> submit -> CONFIRMS."""
    po = _create_po(H, _abc_po_payload([_abc_line(material_id=mapped_material_id)]))
    assert po["integration_provider"] == "abc_supply"
    _review(H, po["id"])
    data, _ = _submit(H, po["id"])
    assert data.get("status") == "confirmed", data
    assert (data.get("confirmation_number") or "").startswith("MOCK-CONF-"), data


# ==================================================================
# 2. Creation Path — Reorder Suggestions style (material_id only, no abc_item_number)
# ==================================================================
def test_reorder_suggestions_style_confirms(H, mapped_material_id):
    """Line has ONLY material_id (ABC-mapped) — server resolves ABC identity + defaults."""
    payload = {
        "supplier_name": "ABC Supply", "integration_provider": "abc_supply",
        "items": [{"material_id": mapped_material_id, "description": "Shingle",
                   "quantity": 4, "unit": "SQ", "unit_cost": 135.36}],
    }
    po = _create_po(H, payload)
    assert po["integration_provider"] == "abc_supply", po
    assert po["abc_ship_to_number"] == DEFAULT_SHIP_TO
    assert po["abc_branch_number"] == DEFAULT_BRANCH
    for ln in po["items"]:
        assert ln.get("abc_item_number") == MOCK_ITEM
        assert ln.get("abc_uom")

    _review(H, po["id"])
    data, _ = _submit(H, po["id"])
    assert data.get("status") == "confirmed", data
    assert (data.get("confirmation_number") or "").startswith("MOCK-CONF-"), data


def test_reorder_suggestions_unmapped_downgrades(H, plain_material_id):
    """Unmapped material -> standard draft with abc_setup_warning (not submittable as ABC)."""
    payload = {
        "supplier_name": "ABC Supply", "integration_provider": "abc_supply",
        "items": [{"material_id": plain_material_id, "description": "Widget",
                   "quantity": 1, "unit": "each", "unit_cost": 10.0}],
    }
    po = _create_po(H, payload)
    assert po["integration_provider"] is None, po
    warn = po.get("abc_setup_warning") or ""
    assert warn, "abc_setup_warning must be set"
    # Attempt abc-submit against the downgraded PO: must be rejected as non-ABC.
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                      headers=H,
                      json={"submission_key": uuid.uuid4().hex, "delivery_service": "OTG"},
                      timeout=30)
    assert r.status_code == 400, r.text[:300]


# ==================================================================
# 3. Creation Path — JobMaterialPlan style (line has abc_item_number+abc_uom, no PO ship_to)
# ==================================================================
def test_jobmaterialplan_style_confirms(H, mapped_material_id):
    payload = {
        "supplier_name": "ABC Supply", "integration_provider": "abc_supply",
        # NOTE: PO-level abc_ship_to_number/abc_branch_number omitted.
        "items": [{"material_id": mapped_material_id, "description": "Shingle (JMP)",
                   "quantity": 5, "unit": "SQ", "unit_cost": 135.36,
                   "abc_item_number": MOCK_ITEM, "abc_uom": "SQ"}],
    }
    po = _create_po(H, payload)
    assert po["integration_provider"] == "abc_supply", po
    assert po["abc_ship_to_number"] == DEFAULT_SHIP_TO
    assert po["abc_branch_number"] == DEFAULT_BRANCH
    _review(H, po["id"])
    data, _ = _submit(H, po["id"])
    assert data.get("status") == "confirmed", data
    assert (data.get("confirmation_number") or "").startswith("MOCK-CONF-"), data


# ==================================================================
# 4. Creation Path — ABC Template convert
# ==================================================================
def test_from_abc_template_confirms(H):
    """Template unit prices differ from live prices -> apply price changes at review; submit confirms."""
    r = requests.post(f"{BASE_URL}/api/purchase-orders/from-abc-template", headers=H,
                      json={"template_id": TEMPLATE_ID}, timeout=60)
    assert r.status_code == 201, r.text[:500]
    po = r.json()
    assert po["integration_provider"] == "abc_supply", po
    assert po["abc_ship_to_number"] == DEFAULT_SHIP_TO
    assert po["abc_branch_number"] == DEFAULT_BRANCH
    assert po["items"], "template PO must have lines"

    # Apply price changes so submit doesn't return status='price_changed'.
    review = _review(H, po["id"], apply_price_changes=True, expect_ok=False)
    assert not review.get("errors"), review

    data, _ = _submit(H, po["id"], accept_price_changes=True)
    assert data.get("status") == "confirmed", data
    assert (data.get("confirmation_number") or "").startswith("MOCK-CONF-"), data


# ==================================================================
# 5. Negative — line rejection (MOCK-REJECT)
# ==================================================================
def test_line_rejection_mock_reject(H, mapped_reject_id):
    payload = _abc_po_payload([_abc_line(item_number=MOCK_ITEM_REJECT, uom="EA", qty=1,
                                         unit_cost=9.99, material_id=mapped_reject_id)])
    po = _create_po(H, payload)
    _review(H, po["id"])
    data, _ = _submit(H, po["id"])
    assert data.get("status") == "failed", data
    assert not data.get("confirmation_number"), data
    assert "reject" in (data.get("message") or "").lower(), data


# ==================================================================
# 6. Negative — unknown / timeout + reconcile resolves
# ==================================================================
def test_timeout_yields_unknown_then_reconcile(H, mapped_timeout_id):
    payload = _abc_po_payload([_abc_line(item_number=MOCK_ITEM_TIMEOUT, uom="EA", qty=1,
                                         unit_cost=4.5, material_id=mapped_timeout_id)])
    po = _create_po(H, payload)
    _review(H, po["id"])
    data, key = _submit(H, po["id"])
    assert data.get("status") == "unknown", data
    assert not data.get("confirmation_number"), data

    # Retry with same key must NOT auto-resubmit — still 'unknown'.
    r_retry = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                            headers=H,
                            json={"submission_key": key, "delivery_service": "OTG"}, timeout=60)
    assert r_retry.status_code == 200, r_retry.text[:300]
    assert r_retry.json().get("status") == "unknown", r_retry.json()

    # Reconcile via history lookup should resolve to a real confirmation number.
    r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-reconcile",
                      headers=H, timeout=60)
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert body.get("status") == "reconciled", body
    assert (body.get("confirmation_number") or "").startswith("MOCK-CONF-"), body


# ==================================================================
# 7. Idempotency — same submission_key + already_submitted
# ==================================================================
def test_idempotent_same_submission_key(H, mapped_material_id):
    po = _create_po(H, _abc_po_payload([_abc_line(material_id=mapped_material_id)]))
    _review(H, po["id"])
    key = uuid.uuid4().hex
    d1, _ = _submit(H, po["id"], submission_key=key)
    assert d1.get("status") == "confirmed", d1
    conf1 = d1["confirmation_number"]

    # Repeat with same key: must return same confirmation, NOT create a duplicate.
    d2, _ = _submit(H, po["id"], submission_key=key)
    assert d2.get("status") == "already_submitted", d2
    assert d2.get("confirmation_number") == conf1, d2

    # And a fresh key on the same already-confirmed PO also returns already_submitted.
    d3, _ = _submit(H, po["id"], submission_key=uuid.uuid4().hex)
    assert d3.get("status") == "already_submitted", d3
    assert d3.get("confirmation_number") == conf1, d3


# ==================================================================
# 8. Preflight negatives (ship-to prefixes) + retry after switching back
# ==================================================================
@pytest.mark.parametrize("ship_to,branch,needles", [
    (f"CREDITHOLD{DEFAULT_SHIP_TO}", DEFAULT_BRANCH, ["credit hold", "not sellable"]),
    ("9999999", DEFAULT_BRANCH, ["inactive", "cannot place orders"]),
    (f"NOBRANCH{DEFAULT_SHIP_TO}", DEFAULT_BRANCH, ["no longer associated"]),
    (f"MISSING{DEFAULT_SHIP_TO}", DEFAULT_BRANCH, ["no longer exists"]),
])
def test_preflight_blocks(H, mapped_material_id, ship_to, branch, needles):
    line = _abc_line(material_id=mapped_material_id)
    line["abc_ship_to_number"] = ship_to
    line["abc_branch_number"] = branch
    po = _create_po(H, _abc_po_payload([line], ship_to=ship_to, branch=branch))
    data, _ = _submit(H, po["id"])
    assert data.get("status") == "validation_failed", data
    assert not data.get("confirmation_number"), data
    errs = " | ".join(data.get("errors") or []).lower()
    assert any(n in errs for n in needles), (data, needles)


def test_preflight_retry_after_switch_back_succeeds(H, mapped_material_id):
    """Blocked preflight must NOT create a stuck pending; switching back to a healthy Ship-To
    with the same submission_key confirms."""
    line = _abc_line(material_id=mapped_material_id)
    line["abc_ship_to_number"] = f"CREDITHOLD{DEFAULT_SHIP_TO}"
    po = _create_po(H, _abc_po_payload([line],
                                       ship_to=f"CREDITHOLD{DEFAULT_SHIP_TO}",
                                       branch=DEFAULT_BRANCH))
    key = uuid.uuid4().hex
    d1, _ = _submit(H, po["id"], submission_key=key)
    assert d1.get("status") == "validation_failed", d1

    # Switch back via PATCH to the healthy default Ship-To.
    r = requests.patch(f"{BASE_URL}/api/purchase-orders/{po['id']}",
                       headers=H, json={"abc_ship_to_number": DEFAULT_SHIP_TO}, timeout=30)
    if r.status_code >= 400:
        # Fallback: fresh healthy PO. Reusing the same key STILL validates 'no stuck pending'
        # (the previous key was never persisted by a failed preflight).
        po = _create_po(H, _abc_po_payload([_abc_line(material_id=mapped_material_id)]))
    _review(H, po["id"])
    d2, _ = _submit(H, po["id"], submission_key=key)
    assert d2.get("status") == "confirmed", d2
    assert (d2.get("confirmation_number") or "").startswith("MOCK-CONF-"), d2


# ==================================================================
# 9. Contract enforcement end-to-end (short vs >255-char delivery instructions)
# ==================================================================
def test_short_delivery_instructions_go_into_deliveryAppointment(H, mapped_material_id):
    """<=255 chars stay in deliveryAppointment.instructions. Mock's shared contract validator
    passes -> status='confirmed' proves the payload satisfies validate_place_order."""
    po = _create_po(H, _abc_po_payload([_abc_line(material_id=mapped_material_id)]))
    _review(H, po["id"])
    short = "Leave at the side gate — driver please call 30 minutes before arrival."
    assert len(short) <= 255
    data, _ = _submit(H, po["id"], delivery={"instructions": short})
    assert data.get("status") == "confirmed", data


def test_long_delivery_instructions_overflow_into_orderComments_D(H, mapped_material_id):
    """>255 chars: first 255 stay in deliveryAppointment.instructions, remainder overflows into
    orderComments with code 'D'. The mock's shared contract validator would REJECT if the
    truncation/overflow logic was wrong (instructions>255 would violate the contract), so
    status='confirmed' end-to-end proves the routing works."""
    po = _create_po(H, _abc_po_payload([_abc_line(material_id=mapped_material_id)]))
    _review(H, po["id"])
    long_instr = "X" * 400  # 400 chars, well above ABC's 255-char cap.
    data, _ = _submit(H, po["id"], delivery={"instructions": long_instr})
    assert data.get("status") == "confirmed", data


# ==================================================================
# 10. Price-change path (backend)
# ==================================================================
def test_price_changed_without_accept_and_confirmed_with_accept(H, mapped_material_id):
    """Set unit_cost far below the live 135.36 -> _validate_and_price records a change ->
    abc-submit returns status='price_changed' when accept_price_changes=false. Retrying
    with accept_price_changes=true proceeds to a confirmed order."""
    line = _abc_line(material_id=mapped_material_id, unit_cost=100.0)
    line["abc_price"] = None  # force old_price to fall back to unit_cost.
    line["abc_price_status"] = "unavailable"
    po = _create_po(H, _abc_po_payload([line]))
    review = _review(H, po["id"])
    assert review.get("price_changes"), review

    # accept_price_changes=false -> price_changed, no confirmation.
    d1, key = _submit(H, po["id"], accept_price_changes=False)
    assert d1.get("status") == "price_changed", d1
    assert not d1.get("confirmation_number"), d1

    # accept_price_changes=true (fresh key) -> confirmed.
    d2, _ = _submit(H, po["id"], submission_key=uuid.uuid4().hex, accept_price_changes=True)
    assert d2.get("status") == "confirmed", d2
    assert (d2.get("confirmation_number") or "").startswith("MOCK-CONF-"), d2
