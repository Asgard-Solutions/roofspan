"""Backend regression: measurement lifecycle (create/put with If-Match) — iter 91."""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://proposal-accept-1.preview.emergentagent.com").rstrip("/")
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def property_id(headers):
    r = requests.post(
        f"{BASE_URL}/api/properties",
        headers=headers,
        json={"address": f"TEST_iter91 {uuid.uuid4().hex[:8]}", "city": "Denver", "state": "CO", "zip_code": "80202"},
        timeout=30,
    )
    assert r.status_code in (200, 201), f"Property create failed: {r.status_code} {r.text}"
    data = r.json()
    return data.get("id") or data.get("_id") or data.get("property_id")


def _create_measurement(headers, property_id):
    idem = uuid.uuid4().hex
    body = {
        "property_id": property_id,
        "structures": [{"name": "A", "structure_type": "main_house"}],
    }
    r = requests.post(
        f"{BASE_URL}/api/mobile/measurements",
        headers={**headers, "Idempotency-Key": idem},
        json=body,
        timeout=30,
    )
    return r


def test_create_measurement_201(headers, property_id):
    r = _create_measurement(headers, property_id)
    assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert "id" in data or "revision_id" in data
    assert "updated_at" in data


def test_put_with_if_match_200_rotates_updated_at(headers, property_id):
    r = _create_measurement(headers, property_id)
    assert r.status_code == 201
    m = r.json()
    rev_id = m.get("id") or m.get("revision_id")
    updated_at = m["updated_at"]

    put_body = {
        "structures": [{"name": "A", "structure_type": "main_house"}, {"name": "B", "structure_type": "detached_garage"}],
    }
    r2 = requests.put(
        f"{BASE_URL}/api/mobile/measurements/{rev_id}",
        headers={**headers, "If-Match": updated_at},
        json=put_body,
        timeout=30,
    )
    assert r2.status_code == 200, f"expected 200, got {r2.status_code}: {r2.text}"
    data2 = r2.json()
    assert data2.get("updated_at") and data2["updated_at"] != updated_at, "updated_at should rotate"


def test_put_with_stale_if_match_409(headers, property_id):
    r = _create_measurement(headers, property_id)
    m = r.json()
    rev_id = m.get("id") or m.get("revision_id")

    r_stale = requests.put(
        f"{BASE_URL}/api/mobile/measurements/{rev_id}",
        headers={**headers, "If-Match": "1970-01-01T00:00:00Z"},
        json={"structures": [{"name": "X", "structure_type": "main_house"}]},
        timeout=30,
    )
    assert r_stale.status_code == 409, f"expected 409, got {r_stale.status_code}: {r_stale.text}"
    body = r_stale.json()
    assert "detail" in body
    # server should provide server detail
    detail = body["detail"]
    if isinstance(detail, dict):
        assert "server" in detail or "updated_at" in detail or "current" in detail


def test_put_invalid_body_422(headers, property_id):
    r = _create_measurement(headers, property_id)
    m = r.json()
    rev_id = m.get("id") or m.get("revision_id")
    updated_at = m["updated_at"]

    # Invalid: structures must be a list; send wrong type
    r_bad = requests.put(
        f"{BASE_URL}/api/mobile/measurements/{rev_id}",
        headers={**headers, "If-Match": updated_at},
        json={"structures": "not-a-list"},
        timeout=30,
    )
    assert r_bad.status_code == 422, f"expected 422, got {r_bad.status_code}: {r_bad.text}"
