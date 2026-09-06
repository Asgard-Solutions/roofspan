"""Backend contract tests for mobile measurement ack lifecycle.

Verifies:
- POST /api/mobile/measurements returns authoritative revision (id, updated_at, ...).
- Idempotency-Key replay returns same id + replayed:true.
- GET list & detail return authoritative revision.
- PUT with correct If-Match succeeds; updated_at changes.
- PUT with stale If-Match returns 409 with detail.server = current authoritative revision.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def property_id(headers):
    # Create a property to attach measurement to
    payload = {
        "address_line1": f"TEST_{uuid.uuid4().hex[:8]} Test Ln",
        "city": "Testville",
        "state": "TX",
        "postal_code": "75001",
    }
    r = requests.post(f"{BASE_URL}/api/properties", headers=headers, json=payload, timeout=30)
    assert r.status_code in (200, 201), f"property create failed: {r.status_code} {r.text}"
    pid = r.json().get("id")
    assert pid
    return pid


def _minimal_body(property_id, note=None):
    body = {
        "property_id": property_id,
        "source": "field",
        "structures": [],
        "facets": [],
        "edges": [],
        "penetrations": [],
        "summary": {"note": note} if note else {},
    }
    return body


def test_create_measurement_returns_authoritative_revision(headers, property_id):
    body = _minimal_body(property_id)
    r = requests.post(f"{BASE_URL}/api/mobile/measurements",
                      headers=headers, json=body, timeout=30)
    assert r.status_code == 201, f"create failed: {r.status_code} {r.text}"
    data = r.json()
    for key in ("id", "updated_at", "revision_number", "editable",
                "structures", "facets", "edges", "penetrations", "summary"):
        assert key in data, f"missing key {key} in response: {list(data.keys())}"
    assert data["id"]
    assert data["updated_at"]
    assert isinstance(data["structures"], list)
    assert isinstance(data["facets"], list)
    assert isinstance(data["edges"], list)
    assert isinstance(data["penetrations"], list)


def test_idempotent_create_returns_same_revision(headers, property_id):
    idem = f"TEST-idem-{uuid.uuid4().hex}"
    body = _minimal_body(property_id, note="idem-first")
    h = dict(headers); h["Idempotency-Key"] = idem
    r1 = requests.post(f"{BASE_URL}/api/mobile/measurements", headers=h, json=body, timeout=30)
    assert r1.status_code == 201, f"first create failed: {r1.status_code} {r1.text}"
    id1 = r1.json()["id"]
    # Replay
    r2 = requests.post(f"{BASE_URL}/api/mobile/measurements", headers=h, json=body, timeout=30)
    assert r2.status_code in (200, 201), f"replay failed: {r2.status_code} {r2.text}"
    data2 = r2.json()
    assert data2["id"] == id1, f"idempotent replay returned different id: {id1} vs {data2['id']}"
    assert data2.get("replayed") is True, f"replay flag not set: {data2}"


def test_list_and_get_return_authoritative(headers, property_id):
    # Create fresh
    body = _minimal_body(property_id, note="list-get")
    r = requests.post(f"{BASE_URL}/api/mobile/measurements", headers=headers, json=body, timeout=30)
    assert r.status_code == 201
    created = r.json()
    rid = created["id"]

    # LIST
    rl = requests.get(f"{BASE_URL}/api/mobile/measurements",
                      headers=headers, params={"property_id": property_id}, timeout=30)
    assert rl.status_code == 200, rl.text
    lst = rl.json()
    assert isinstance(lst, list) and len(lst) >= 1
    ids = [x.get("id") for x in lst]
    assert rid in ids, f"created rev {rid} not in list {ids}"

    # GET
    rg = requests.get(f"{BASE_URL}/api/mobile/measurements/{rid}", headers=headers, timeout=30)
    assert rg.status_code == 200, rg.text
    got = rg.json()
    assert got["id"] == rid
    assert got["updated_at"] == created["updated_at"]


def test_update_success_changes_updated_at(headers, property_id):
    body = _minimal_body(property_id, note="upd-1")
    r = requests.post(f"{BASE_URL}/api/mobile/measurements", headers=headers, json=body, timeout=30)
    assert r.status_code == 201
    created = r.json()
    rid = created["id"]
    orig_updated = created["updated_at"]

    # Update with correct If-Match
    new_body = _minimal_body(property_id, note="upd-2")
    h = dict(headers); h["If-Match"] = orig_updated
    ru = requests.put(f"{BASE_URL}/api/mobile/measurements/{rid}", headers=h, json=new_body, timeout=30)
    assert ru.status_code == 200, f"update failed: {ru.status_code} {ru.text}"
    updated = ru.json()
    assert updated["id"] == rid
    assert updated["updated_at"], "updated_at missing"
    assert updated["updated_at"] != orig_updated, "updated_at didn't change after update"


def test_stale_if_match_conflict_returns_detail_server(headers, property_id):
    body = _minimal_body(property_id, note="conflict-init")
    r = requests.post(f"{BASE_URL}/api/mobile/measurements", headers=headers, json=body, timeout=30)
    assert r.status_code == 201
    created = r.json()
    rid = created["id"]
    stale_token = created["updated_at"]

    # First good update advances updated_at
    h_ok = dict(headers); h_ok["If-Match"] = stale_token
    ru = requests.put(f"{BASE_URL}/api/mobile/measurements/{rid}",
                      headers=h_ok, json=_minimal_body(property_id, note="conflict-advance"), timeout=30)
    assert ru.status_code == 200, ru.text
    new_updated = ru.json()["updated_at"]
    assert new_updated != stale_token

    # Second update using STALE token -> 409
    h_stale = dict(headers); h_stale["If-Match"] = stale_token
    rc = requests.put(f"{BASE_URL}/api/mobile/measurements/{rid}",
                      headers=h_stale, json=_minimal_body(property_id, note="conflict-stale"), timeout=30)
    assert rc.status_code == 409, f"expected 409, got {rc.status_code}: {rc.text}"
    body409 = rc.json()
    assert "detail" in body409, f"no detail key: {body409}"
    detail = body409["detail"]
    assert isinstance(detail, dict), f"detail must be object, got: {type(detail).__name__} {detail}"
    assert "server" in detail, f"detail.server missing: {detail}"
    server = detail["server"]
    assert isinstance(server, dict)
    assert server.get("id") == rid, f"detail.server.id mismatch: {server.get('id')} vs {rid}"
    assert server.get("updated_at") == new_updated, (
        f"detail.server.updated_at mismatch: {server.get('updated_at')} vs {new_updated}")
