"""RBAC: sales user must NOT be able to mutate locations/transfer/issue/return/disposition.
Read paths (locations list, balances) should remain accessible."""
import os
import uuid
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}


def _owner_h():
    r = requests.post(f"{API}/auth/login", json=OWNER, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _sales_h():
    oh = _owner_h()
    email = f"TEST_sales_{uuid.uuid4().hex[:6]}@example.com"
    pw = "Sales#Rbac2026"
    r = requests.post(f"{API}/users", headers=oh, timeout=20, json={
        "email": email, "password": pw, "full_name": "Sales RBAC", "role": "sales"})
    assert r.status_code in (200, 201), r.text
    lr = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert lr.status_code == 200, lr.text
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}, oh


def _pick(h):
    mats = requests.get(f"{API}/materials", headers=h, timeout=20).json()
    mid = next(m["id"] for m in mats if m.get("quantity_on_hand", 0) > 20)
    locs = requests.get(f"{API}/inventory/locations", headers=h, timeout=20).json()
    loc = next(l["id"] for l in locs if l["is_default"])
    return mid, loc


def test_sales_cannot_mutate_inventory_ops():
    sh, oh = _sales_h()
    mid, loc = _pick(oh)
    # Reads: allowed
    assert requests.get(f"{API}/inventory/locations", headers=sh, timeout=20).status_code == 200
    assert requests.get(f"{API}/inventory/balances", headers=sh, params={"material_id": mid}, timeout=20).status_code == 200

    forbidden = (401, 403)
    # Location create
    r = requests.post(f"{API}/inventory/locations", headers=sh, timeout=20,
                      json={"name": "TEST_sales_loc", "type": "yard"})
    assert r.status_code in forbidden, r.status_code
    # Transfer
    r = requests.post(f"{API}/inventory/transfer", headers=sh, timeout=20,
                      json={"material_id": mid, "source_location_id": loc, "destination_location_id": loc, "quantity": 1})
    assert r.status_code in forbidden, r.status_code
    # Issue
    r = requests.post(f"{API}/inventory/issue", headers=sh, timeout=20,
                      json={"material_id": mid, "location_id": loc, "quantity": 1})
    assert r.status_code in forbidden, r.status_code
    # Return
    r = requests.post(f"{API}/inventory/return", headers=sh, timeout=20,
                      json={"material_id": mid, "location_id": loc, "quantity": 1})
    assert r.status_code in forbidden, r.status_code
    # Disposition
    r = requests.post(f"{API}/inventory/disposition", headers=sh, timeout=20,
                      json={"material_id": mid, "location_id": loc, "quantity": 1, "kind": "waste"})
    assert r.status_code in forbidden, r.status_code
    # Cycle count
    r = requests.post(f"{API}/inventory/cycle-count", headers=sh, timeout=20,
                      json={"location_id": loc, "lines": [{"material_id": mid, "counted_quantity": 1}]})
    assert r.status_code in forbidden, r.status_code
