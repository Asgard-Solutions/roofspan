"""Backend regression: measurement lifecycle (create → update If-Match → stale If-Match conflict)."""
import os
import uuid
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://proposal-accept-1.preview.emergentagent.com").rstrip("/")
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


def _login():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    return r.json()["access_token"]


def _headers(token, extra=None):
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _create_property(token):
    payload = {
        "address": f"TEST_{uuid.uuid4().hex[:8]} 123 Regression Ln",
        "city": "Testville",
        "state": "CA",
        "zip_code": "90210",
    }
    r = requests.post(f"{BASE_URL}/api/properties", json=payload, headers=_headers(token), timeout=30)
    assert r.status_code in (200, 201), f"create property {r.status_code} {r.text}"
    data = r.json()
    return data.get("id") or data.get("property_id") or data.get("_id")


def test_measurement_lifecycle():
    token = _login()
    prop_id = _create_property(token)
    assert prop_id, "property id missing"

    idem = str(uuid.uuid4())
    body = {
        "property_id": prop_id,
        "client_id": str(uuid.uuid4()),
        "structures": [],
        "facets": [],
        "edges": [],
        "penetrations": [],
        "notes": "TEST_regression",
    }

    # POST create with Idempotency-Key
    r = requests.post(
        f"{BASE_URL}/api/mobile/measurements",
        json=body,
        headers=_headers(token, {"Idempotency-Key": idem}),
        timeout=30,
    )
    assert r.status_code == 201, f"create expected 201, got {r.status_code} {r.text}"
    created = r.json()
    rev_id = created.get("id") or created.get("revision_id") or created.get("_id")
    updated_at = created.get("updated_at")
    assert rev_id and updated_at, f"missing id/updated_at in {created}"

    # PUT with correct If-Match
    upd_body = {**body, "notes": "TEST_regression_updated"}
    r2 = requests.put(
        f"{BASE_URL}/api/mobile/measurements/{rev_id}",
        json=upd_body,
        headers=_headers(token, {"If-Match": updated_at, "Idempotency-Key": str(uuid.uuid4())}),
        timeout=30,
    )
    assert r2.status_code == 200, f"update expected 200, got {r2.status_code} {r2.text}"
    updated = r2.json()
    new_updated_at = updated.get("updated_at")
    assert new_updated_at and new_updated_at != updated_at, "updated_at should rotate"

    # PUT with stale If-Match → 409
    r3 = requests.put(
        f"{BASE_URL}/api/mobile/measurements/{rev_id}",
        json=upd_body,
        headers=_headers(token, {"If-Match": updated_at, "Idempotency-Key": str(uuid.uuid4())}),
        timeout=30,
    )
    assert r3.status_code == 409, f"stale If-Match expected 409, got {r3.status_code} {r3.text}"
    detail = r3.json().get("detail")
    assert detail and (isinstance(detail, dict) and "server" in detail), f"expected detail.server, got {r3.json()}"


if __name__ == "__main__":
    test_measurement_lifecycle()
    print("BACKEND REGRESSION: passed")
