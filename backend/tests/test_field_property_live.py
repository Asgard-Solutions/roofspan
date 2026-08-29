"""Live HTTP tests for Field Property parity + DNK PATCH + outcome validation + IDOR.

Runs against REACT_APP_BACKEND_URL. Only touches endpoints (no direct DB access).
"""
import os
import uuid
import requests
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://field-office-sync-2.preview.emergentagent.com").rstrip("/")

OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
SALES1 = {"email": "sales1_38f545f9@example.com", "password": "Sales1#2026"}
SALES2 = {"email": "sales2_7ad4f5cd@example.com", "password": "Sales2#2026"}

CANONICAL_KEYS = [
    "id", "formatted_address", "property_type", "bedrooms", "bathrooms",
    "square_footage", "year_built", "latitude", "longitude", "owner_occupied",
    "do_not_knock", "do_not_knock_reason", "contacts", "visits", "lead_id",
    "location_diagnostics", "created_at", "updated_at",
]
COMPAT_KEYS = ["owner_name", "owner_phone", "existing_lead_id"]


def _login(creds):
    r = requests.post(f"{BASE}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login {creds['email']} failed: {r.status_code} {r.text[:300]}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in response: {r.json()}"
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def owner_h():
    return _login(OWNER)


@pytest.fixture(scope="module")
def sales1_h():
    return _login(SALES1)


@pytest.fixture(scope="module")
def sales2_h():
    return _login(SALES2)


@pytest.fixture(scope="module")
def owner_property_id(owner_h):
    """Find any existing property accessible to owner."""
    # Try /api/properties list
    r = requests.get(f"{BASE}/api/properties", headers=owner_h, timeout=30, params={"limit": 5})
    if r.status_code == 200:
        data = r.json()
        items = data.get("items") if isinstance(data, dict) else data
        if items:
            return items[0]["id"]
    # Create a property via owner
    payload = {
        "formatted_address": f"TEST_ {uuid.uuid4().hex[:6]} 1 Test Ave",
        "source": "test",
    }
    r = requests.post(f"{BASE}/api/properties", headers=owner_h, json=payload, timeout=30)
    assert r.status_code in (200, 201), f"create property failed: {r.status_code} {r.text[:400]}"
    return r.json()["id"]


# ---------------- Auth sanity ----------------
def test_owner_login(owner_h):
    assert "Authorization" in owner_h


def test_sales_login(sales1_h, sales2_h):
    assert sales1_h and sales2_h


# ---------------- Canonical parity: Office vs Field ----------------
def test_office_and_field_return_canonical_keys(owner_h, owner_property_id):
    r_off = requests.get(f"{BASE}/api/properties/{owner_property_id}", headers=owner_h, timeout=30)
    assert r_off.status_code == 200, f"office GET failed: {r_off.status_code} {r_off.text[:300]}"
    r_mob = requests.get(f"{BASE}/api/mobile/properties/{owner_property_id}", headers=owner_h, timeout=30)
    assert r_mob.status_code == 200, f"mobile GET failed: {r_mob.status_code} {r_mob.text[:300]}"

    off, mob = r_off.json(), r_mob.json()
    missing_off = [k for k in CANONICAL_KEYS if k not in off]
    missing_mob = [k for k in CANONICAL_KEYS if k not in mob]
    assert not missing_off, f"office missing canonical keys: {missing_off}"
    assert not missing_mob, f"mobile missing canonical keys: {missing_mob}"

    # Field must include compat aliases
    missing_compat = [k for k in COMPAT_KEYS if k not in mob]
    assert not missing_compat, f"mobile missing compat aliases: {missing_compat}"

    # values equal for canonical keys shared
    for k in CANONICAL_KEYS:
        assert off[k] == mob[k], f"canonical parity mismatch on '{k}': office={off[k]!r} mobile={mob[k]!r}"

    # compat aliases align with canonical values
    owner_contact = next((c for c in mob["contacts"] if c.get("kind") == "owner"), None)
    if owner_contact:
        assert mob["owner_name"] == owner_contact.get("name")
        assert mob["owner_phone"] == owner_contact.get("phone")
    assert mob["existing_lead_id"] == mob["lead_id"]


# ---------------- DNK ON/OFF via mobile PATCH (owner authorized) ----------------
def test_mobile_patch_dnk_toggle_and_notes(owner_h, owner_property_id):
    # ON
    r = requests.patch(f"{BASE}/api/mobile/properties/{owner_property_id}",
                       headers=owner_h, json={"do_not_knock": True, "do_not_knock_reason": "TEST ON"}, timeout=30)
    assert r.status_code == 200, f"PATCH ON failed: {r.status_code} {r.text[:300]}"
    assert r.json().get("do_not_knock") is True

    # OFF
    r = requests.patch(f"{BASE}/api/mobile/properties/{owner_property_id}",
                       headers=owner_h, json={"do_not_knock": False}, timeout=30)
    assert r.status_code == 200
    assert r.json().get("do_not_knock") is False

    # notes
    r = requests.patch(f"{BASE}/api/mobile/properties/{owner_property_id}",
                       headers=owner_h, json={"notes": "TEST note via field"}, timeout=30)
    assert r.status_code == 200
    assert r.json().get("notes") == "TEST note via field"


# ---------------- Sales IDOR: unauthorized sales -> 403 on GET & PATCH ----------------
def test_sales_idor_get_and_patch_forbidden(sales1_h, sales2_h, owner_h, owner_property_id):
    # Pick whichever sales user is NOT authorized. Try both, at least one should be 403.
    forbidden_seen = {"get": False, "patch": False}
    for h, label in ((sales1_h, "sales1"), (sales2_h, "sales2")):
        rg = requests.get(f"{BASE}/api/mobile/properties/{owner_property_id}", headers=h, timeout=30)
        rp = requests.patch(f"{BASE}/api/mobile/properties/{owner_property_id}", headers=h,
                            json={"do_not_knock": True}, timeout=30)
        print(f"{label} GET={rg.status_code} PATCH={rp.status_code}")
        if rg.status_code == 403:
            forbidden_seen["get"] = True
        if rp.status_code == 403:
            forbidden_seen["patch"] = True
        # Sanity: never 200 unless truly authorized (accept 200 as authorized-sales case).
        assert rg.status_code in (200, 403, 404), f"unexpected GET code {rg.status_code}: {rg.text[:200]}"
        assert rp.status_code in (200, 403, 404), f"unexpected PATCH code {rp.status_code}: {rp.text[:200]}"
    assert forbidden_seen["get"], "no sales user got 403 on GET — IDOR check inconclusive"
    assert forbidden_seen["patch"], "no sales user got 403 on PATCH — IDOR check inconclusive"


# ---------------- Canonical visit outcomes: mobile ----------------
VALID_OUTCOMES = ["no_answer", "not_interested", "interested", "callback", "appointment", "do_not_knock"]
INVALID_OUTCOMES = ["sold", "maybe"]


@pytest.mark.parametrize("outcome", VALID_OUTCOMES)
def test_mobile_visit_accepts_valid_outcome(owner_h, owner_property_id, outcome):
    r = requests.post(f"{BASE}/api/mobile/visits", headers=owner_h,
                      json={"property_id": owner_property_id, "outcome": outcome,
                            "notes": f"TEST visit outcome={outcome}"}, timeout=30)
    assert 200 <= r.status_code < 300, f"outcome {outcome} rejected: {r.status_code} {r.text[:300]}"


@pytest.mark.parametrize("outcome", INVALID_OUTCOMES)
def test_mobile_visit_rejects_invalid_outcome(owner_h, owner_property_id, outcome):
    r = requests.post(f"{BASE}/api/mobile/visits", headers=owner_h,
                      json={"property_id": owner_property_id, "outcome": outcome,
                            "notes": "TEST invalid"}, timeout=30)
    assert r.status_code == 422, f"expected 422 for outcome={outcome}, got {r.status_code} {r.text[:300]}"


# ---------------- Canonical visit outcomes: office ----------------
def test_office_visit_rejects_invalid(owner_h, owner_property_id):
    r = requests.post(f"{BASE}/api/properties/{owner_property_id}/visits", headers=owner_h,
                      json={"outcome": "maybe", "notes": "TEST bad"}, timeout=30)
    assert r.status_code == 422, f"expected 422 got {r.status_code}: {r.text[:300]}"


def test_office_visit_accepts_callback_and_appointment(owner_h, owner_property_id):
    for oc in ("callback", "appointment"):
        r = requests.post(f"{BASE}/api/properties/{owner_property_id}/visits", headers=owner_h,
                          json={"outcome": oc, "notes": f"TEST office {oc}"}, timeout=30)
        assert 200 <= r.status_code < 300, f"office {oc} failed: {r.status_code} {r.text[:300]}"


# ---------------- Visit notes persist and appear in visits[] ----------------
def test_visit_notes_persist_in_visits_list(owner_h, owner_property_id):
    tag = f"TEST_NOTE_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{BASE}/api/mobile/visits", headers=owner_h,
                      json={"property_id": owner_property_id, "outcome": "interested", "notes": tag}, timeout=30)
    assert 200 <= r.status_code < 300, r.text[:300]
    g = requests.get(f"{BASE}/api/mobile/properties/{owner_property_id}", headers=owner_h, timeout=30)
    assert g.status_code == 200
    visits = g.json().get("visits", [])
    assert any(v.get("notes") == tag for v in visits), f"visit note {tag!r} not found in visits[]"



# ---------------- Datetime wire-format parity (regression fix) ----------------
def test_datetime_parity_office_vs_mobile(owner_h, owner_property_id):
    """Office and Mobile Property detail must emit BYTE-IDENTICAL timestamp strings."""
    r_off = requests.get(f"{BASE}/api/properties/{owner_property_id}", headers=owner_h, timeout=30)
    r_mob = requests.get(f"{BASE}/api/mobile/properties/{owner_property_id}", headers=owner_h, timeout=30)
    assert r_off.status_code == 200 and r_mob.status_code == 200
    off, mob = r_off.json(), r_mob.json()

    # Top-level timestamps
    assert off["created_at"] == mob["created_at"], (
        f"created_at wire mismatch: office={off['created_at']!r} mobile={mob['created_at']!r}"
    )
    assert off["updated_at"] == mob["updated_at"], (
        f"updated_at wire mismatch: office={off['updated_at']!r} mobile={mob['updated_at']!r}"
    )

    # Visit-level timestamps (same ordering guaranteed by service)
    off_visits = off.get("visits", [])
    mob_visits = mob.get("visits", [])
    assert len(off_visits) == len(mob_visits), "visits count differs"
    for i, (ov, mv) in enumerate(zip(off_visits, mob_visits)):
        for k in ("visited_at", "created_at"):
            if k in ov or k in mv:
                assert ov.get(k) == mv.get(k), (
                    f"visits[{i}].{k} wire mismatch: office={ov.get(k)!r} mobile={mv.get(k)!r}"
                )
