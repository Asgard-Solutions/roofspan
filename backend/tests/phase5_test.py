"""RoofSpan Phase 5 - Production Readiness backend tests.

Covers the approved Operations safety hardening and security guarantees:
- PO line quantity must be > 0 (422)
- Material starting quantity / reorder threshold must be >= 0 (422)
- Material name normalization + case/space-insensitive uniqueness (409)
- Atomic idempotent receiving (same Idempotency-Key never double-posts inventory)
- Partial -> full receiving + over-receive protection (400)
- Security: RentCast/MapTiler secret is never returned in plaintext (masked only)
- Security: a disabled user's existing token can no longer access the API (401)
"""
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


@pytest.fixture(scope="module")
def owner_headers():
    r = requests.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _mk_material(headers, name=None, qty=0, reorder=0):
    name = name or f"TEST_P5_Mat_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/materials", json={"name": name, "unit": "each", "quantity_on_hand": qty, "reorder_threshold": reorder}, headers=headers, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- Hardening: input constraints ----------
def test_po_line_quantity_must_be_positive(owner_headers):
    for bad in (0, -3):
        r = requests.post(f"{API}/purchase-orders", json={"supplier_name": "TEST_P5_Sup", "items": [{"description": "x", "quantity": bad, "unit_cost": 5}]}, headers=owner_headers, timeout=15)
        assert r.status_code == 422, f"quantity={bad} -> {r.status_code}: {r.text}"


def test_material_quantities_must_be_non_negative(owner_headers):
    r = requests.post(f"{API}/materials", json={"name": f"TEST_P5_Neg_{uuid.uuid4().hex[:6]}", "quantity_on_hand": -5}, headers=owner_headers, timeout=15)
    assert r.status_code == 422, r.text
    r2 = requests.post(f"{API}/materials", json={"name": f"TEST_P5_Neg2_{uuid.uuid4().hex[:6]}", "reorder_threshold": -1}, headers=owner_headers, timeout=15)
    assert r2.status_code == 422, r2.text


def test_material_name_normalized_and_unique(owner_headers):
    base = f"TEST_P5_Uniq_{uuid.uuid4().hex[:6]}"
    m = _mk_material(owner_headers, name=f"  {base}   Shingle  ")
    # stored name is trimmed + whitespace-collapsed
    assert m["name"] == f"{base} Shingle", m["name"]
    # case/spacing variant is rejected as a duplicate
    dup = requests.post(f"{API}/materials", json={"name": f"{base.lower()} shingle", "unit": "each"}, headers=owner_headers, timeout=15)
    assert dup.status_code == 409, dup.text


# ---------- Hardening: atomic idempotent receiving ----------
def test_receiving_idempotent_and_bounded(owner_headers):
    m = _mk_material(owner_headers, qty=0)
    po = requests.post(f"{API}/purchase-orders", json={"supplier_name": "TEST_P5_Sup", "items": [{"material_id": m["id"], "quantity": 10, "unit_cost": 5}]}, headers=owner_headers, timeout=15).json()
    line_id = po["items"][0]["id"]

    key1 = f"p5recv-{uuid.uuid4().hex}"
    h = {**owner_headers, "Idempotency-Key": key1}
    r1 = requests.post(f"{API}/purchase-orders/{po['id']}/receive", json={"items": [{"po_item_id": line_id, "quantity": 4}]}, headers=h, timeout=15)
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "partially_received"
    on_hand = requests.get(f"{API}/materials", headers=owner_headers, timeout=15).json()
    assert next(x for x in on_hand if x["id"] == m["id"])["quantity_on_hand"] == 4

    # replay with the SAME key -> no double post
    r2 = requests.post(f"{API}/purchase-orders/{po['id']}/receive", json={"items": [{"po_item_id": line_id, "quantity": 4}]}, headers=h, timeout=15)
    assert r2.status_code == 200, r2.text
    on_hand = requests.get(f"{API}/materials", headers=owner_headers, timeout=15).json()
    assert next(x for x in on_hand if x["id"] == m["id"])["quantity_on_hand"] == 4, "idempotent replay must not increment inventory"

    # receive the rest with a new key -> fully received
    key2 = f"p5recv-{uuid.uuid4().hex}"
    r3 = requests.post(f"{API}/purchase-orders/{po['id']}/receive", json={"items": [{"po_item_id": line_id, "quantity": 6}]}, headers={**owner_headers, "Idempotency-Key": key2}, timeout=15)
    assert r3.status_code == 200 and r3.json()["status"] == "received", r3.text
    on_hand = requests.get(f"{API}/materials", headers=owner_headers, timeout=15).json()
    assert next(x for x in on_hand if x["id"] == m["id"])["quantity_on_hand"] == 10

    # over-receive is rejected
    r4 = requests.post(f"{API}/purchase-orders/{po['id']}/receive", json={"items": [{"po_item_id": line_id, "quantity": 1}]}, headers={**owner_headers, "Idempotency-Key": f"p5recv-{uuid.uuid4().hex}"}, timeout=15)
    assert r4.status_code == 400, r4.text


def test_idempotency_key_reuse_for_different_po_conflicts(owner_headers):
    m = _mk_material(owner_headers, qty=0)
    po_a = requests.post(f"{API}/purchase-orders", json={"supplier_name": "TEST_P5_Sup", "items": [{"material_id": m["id"], "quantity": 5, "unit_cost": 1}]}, headers=owner_headers, timeout=15).json()
    po_b = requests.post(f"{API}/purchase-orders", json={"supplier_name": "TEST_P5_Sup", "items": [{"material_id": m["id"], "quantity": 5, "unit_cost": 1}]}, headers=owner_headers, timeout=15).json()
    key = f"p5reuse-{uuid.uuid4().hex}"
    r1 = requests.post(f"{API}/purchase-orders/{po_a['id']}/receive", json={"items": [{"po_item_id": po_a['items'][0]['id'], "quantity": 2}]}, headers={**owner_headers, "Idempotency-Key": key}, timeout=15)
    assert r1.status_code == 200, r1.text
    r2 = requests.post(f"{API}/purchase-orders/{po_b['id']}/receive", json={"items": [{"po_item_id": po_b['items'][0]['id'], "quantity": 2}]}, headers={**owner_headers, "Idempotency-Key": key}, timeout=15)
    assert r2.status_code == 409, r2.text


# ---------- Security ----------
def test_integration_secret_never_returned_plaintext(owner_headers):
    secret = f"sk_test_{uuid.uuid4().hex}"
    put = requests.put(f"{API}/integrations/rentcast/secret", json={"secret": secret}, headers=owner_headers, timeout=15)
    assert put.status_code == 200, put.text
    body = put.json()
    assert body.get("has_secret") is True
    assert secret not in str(body)
    assert body.get("secret_masked", "").endswith(secret[-4:])
    got = requests.get(f"{API}/integrations/rentcast", headers=owner_headers, timeout=15).json()
    assert secret not in str(got)
    # cleanup: clear the test key
    requests.delete(f"{API}/integrations/rentcast/secret", headers=owner_headers, timeout=15)


def test_disabled_user_token_is_rejected(owner_headers):
    email = f"TEST_P5_disable_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "DisableMe#2026"
    cr = requests.post(f"{API}/users", json={"email": email, "full_name": "TEST P5 Disable", "password": pwd, "role": "office"}, headers=owner_headers, timeout=15)
    assert cr.status_code == 201, cr.text
    uid = cr.json()["id"]
    tok = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=15).json()["access_token"]
    uh = {"Authorization": f"Bearer {tok}"}
    assert requests.get(f"{API}/auth/me", headers=uh, timeout=15).status_code == 200
    # disable the user
    requests.patch(f"{API}/users/{uid}", json={"is_active": False}, headers=owner_headers, timeout=15)
    # the previously-issued token must no longer work
    assert requests.get(f"{API}/auth/me", headers=uh, timeout=15).status_code == 401
