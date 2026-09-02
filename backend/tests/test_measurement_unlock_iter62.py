"""
Iteration 62 - POST /api/measurements/{revision_id}/unlock

Coverage:
  * Happy path: draft -> field_complete -> office_verified -> locked, then unlock returns
    status='office_verified', is_immutable=false, locked_by/locked_at cleared.
  * After unlock, the revision is usable again (return to draft via /status to=draft).
  * Guard: unlock on a non-locked status (draft / field_complete / office_verified) -> 409.
  * Role guard: sales user attempting unlock -> 403.
  * Estimate-referenced: noted as not-exercised (requires template + estimate wiring).
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://labeled-field-inputs.preview.emergentagent.com").rstrip("/")
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"
SALES_CREDENTIALS = [
    ("sales@example.com", "SalesRS#2026"),
    ("sales1_38f545f9@example.com", "Sales1#2026"),
    ("sales2_7ad4f5cd@example.com", "Sales2#2026"),
    ("sales_bk@example.com", "SalesBk#2026"),
]
TIMEOUT = 30


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=TIMEOUT)
    if r.status_code != 200:
        return None
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def token():
    tok = _login(OWNER_EMAIL, OWNER_PASSWORD)
    assert tok, "owner login failed"
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def sales_h():
    for email, pw in SALES_CREDENTIALS:
        tok = _login(email, pw)
        if tok:
            return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    pytest.skip("no sales user available")


@pytest.fixture(scope="module")
def lead_and_property(h):
    r = requests.get(f"{BASE_URL}/api/leads", headers=h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    leads = body if isinstance(body, list) else body.get("items") or body.get("leads") or []
    for lead in leads:
        pid = lead.get("property_id") or (lead.get("property") or {}).get("id")
        if pid:
            return lead["id"], pid
    payload = {
        "first_name": "TEST", "last_name": f"Iter62_{uuid.uuid4().hex[:6]}",
        "address_line1": "789 Unlock Ave", "city": "Austin", "state": "TX", "postal_code": "78703",
    }
    r = requests.post(f"{BASE_URL}/api/leads", headers=h, json=payload, timeout=TIMEOUT)
    assert r.status_code in (200, 201), r.text
    lead = r.json()
    pid = lead.get("property_id") or (lead.get("property") or {}).get("id")
    return lead["id"], pid


def _minimal_body(lead_id, property_id):
    ref_s = f"s-{uuid.uuid4().hex[:6]}"
    ref_f = f"f-{uuid.uuid4().hex[:6]}"
    return {
        "lead_id": lead_id,
        "property_id": property_id,
        "source": "office",
        "structures": [{"ref": ref_s, "name": "Main", "structure_type": "main_house"}],
        "facets": [{"ref": ref_f, "structure_ref": ref_s, "facet_label": "F1", "area_sqft": 100.0, "pitch_rise": 6}],
        "edges": [],
        "penetrations": [],
        "summary": {"deck_type": "osb"},
    }


def _create_draft(h, lead_id, property_id):
    r = requests.post(f"{BASE_URL}/api/measurements", headers=h,
                      json=_minimal_body(lead_id, property_id), timeout=TIMEOUT)
    assert r.status_code == 201, f"create draft failed: {r.status_code} {r.text}"
    return r.json()


def _status(h, rid, to):
    return requests.post(f"{BASE_URL}/api/measurements/{rid}/status",
                         headers=h, json={"to": to}, timeout=TIMEOUT)


def _drive_to_locked(h, lead_id, property_id):
    rev = _create_draft(h, lead_id, property_id)
    rid = rev["id"]
    for to in ("field_complete", "office_verified", "locked"):
        r = _status(h, rid, to)
        assert r.status_code == 200, f"transition to {to} failed: {r.status_code} {r.text}"
        assert r.json()["status"] == to
    # verify locked state
    g = requests.get(f"{BASE_URL}/api/measurements/{rid}", headers=h, timeout=TIMEOUT)
    assert g.status_code == 200
    body = g.json()
    assert body["status"] == "locked"
    assert body["is_immutable"] is True
    assert body.get("locked_by")
    assert body.get("locked_at")
    return rid


class TestUnlockMeasurementRevision:

    def test_login(self, token):
        assert isinstance(token, str) and len(token) > 10

    def test_unlock_happy_path(self, h, lead_and_property):
        lead_id, property_id = lead_and_property
        rid = _drive_to_locked(h, lead_id, property_id)

        r = requests.post(f"{BASE_URL}/api/measurements/{rid}/unlock", headers=h, timeout=TIMEOUT)
        assert r.status_code == 200, f"unlock failed: {r.status_code} {r.text}"
        body = r.json()
        assert body["status"] == "office_verified"
        assert body["is_immutable"] is False
        assert body.get("locked_by") in (None, "")
        assert body.get("locked_at") in (None, "")

        # Verify via GET
        g = requests.get(f"{BASE_URL}/api/measurements/{rid}", headers=h, timeout=TIMEOUT)
        assert g.status_code == 200
        gb = g.json()
        assert gb["status"] == "office_verified"
        assert gb["is_immutable"] is False
        assert gb.get("locked_by") in (None, "")
        assert gb.get("locked_at") in (None, "")

    def test_unlocked_revision_is_usable_again(self, h, lead_and_property):
        lead_id, property_id = lead_and_property
        rid = _drive_to_locked(h, lead_id, property_id)
        r = requests.post(f"{BASE_URL}/api/measurements/{rid}/unlock", headers=h, timeout=TIMEOUT)
        assert r.status_code == 200, r.text

        # Return to draft — should now succeed since is_immutable=False and status=office_verified
        r = _status(h, rid, "draft")
        assert r.status_code == 200, f"cannot return to draft after unlock: {r.status_code} {r.text}"
        assert r.json()["status"] == "draft"

    def test_unlock_on_draft_returns_409(self, h, lead_and_property):
        lead_id, property_id = lead_and_property
        rev = _create_draft(h, lead_id, property_id)
        rid = rev["id"]
        r = requests.post(f"{BASE_URL}/api/measurements/{rid}/unlock", headers=h, timeout=TIMEOUT)
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
        assert "Only a locked revision" in str(r.json().get("detail", ""))
        # state unchanged
        g = requests.get(f"{BASE_URL}/api/measurements/{rid}", headers=h, timeout=TIMEOUT)
        assert g.json()["status"] == "draft"

    def test_unlock_on_field_complete_returns_409(self, h, lead_and_property):
        lead_id, property_id = lead_and_property
        rev = _create_draft(h, lead_id, property_id)
        rid = rev["id"]
        assert _status(h, rid, "field_complete").status_code == 200
        r = requests.post(f"{BASE_URL}/api/measurements/{rid}/unlock", headers=h, timeout=TIMEOUT)
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
        g = requests.get(f"{BASE_URL}/api/measurements/{rid}", headers=h, timeout=TIMEOUT)
        assert g.json()["status"] == "field_complete"

    def test_unlock_on_office_verified_returns_409(self, h, lead_and_property):
        lead_id, property_id = lead_and_property
        rev = _create_draft(h, lead_id, property_id)
        rid = rev["id"]
        assert _status(h, rid, "field_complete").status_code == 200
        assert _status(h, rid, "office_verified").status_code == 200
        r = requests.post(f"{BASE_URL}/api/measurements/{rid}/unlock", headers=h, timeout=TIMEOUT)
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
        g = requests.get(f"{BASE_URL}/api/measurements/{rid}", headers=h, timeout=TIMEOUT)
        assert g.json()["status"] == "office_verified"
        assert g.json()["is_immutable"] is False

    def test_unlock_bogus_id_returns_404(self, h):
        r = requests.post(f"{BASE_URL}/api/measurements/{uuid.uuid4()}/unlock", headers=h, timeout=TIMEOUT)
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"

    def test_role_guard_sales_forbidden(self, h, sales_h, lead_and_property):
        lead_id, property_id = lead_and_property
        rid = _drive_to_locked(h, lead_id, property_id)
        # sales attempts unlock
        r = requests.post(f"{BASE_URL}/api/measurements/{rid}/unlock", headers=sales_h, timeout=TIMEOUT)
        assert r.status_code == 403, f"expected 403 for sales user, got {r.status_code}: {r.text}"
        # still locked
        g = requests.get(f"{BASE_URL}/api/measurements/{rid}", headers=h, timeout=TIMEOUT)
        assert g.status_code == 200
        assert g.json()["status"] == "locked"
        assert g.json()["is_immutable"] is True
        # owner can unlock now (cleanup + confirms guard did not break it)
        r = requests.post(f"{BASE_URL}/api/measurements/{rid}/unlock", headers=h, timeout=TIMEOUT)
        assert r.status_code == 200

    def test_estimate_referenced_path_not_exercised(self):
        # Estimate/takeoff generation path requires template + estimate wiring; per iter62 request,
        # note as not-exercised. Service code path is exercised in unit terms by the same helper —
        # the SQL SELECT on EstimateTakeoff.measurement_revision_id in services/measurements.py:611.
        pytest.skip("Estimate-referenced unlock refusal path not exercised via API (requires takeoff/estimate generation wiring).")
