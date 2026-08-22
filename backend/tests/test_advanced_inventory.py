"""Advanced Inventory Operations regression — locations, balances, transfer, issue, return,
waste, cycle count, auto-release; integrity invariants."""
import os
import uuid
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}


def _h():
    r = requests.post(f"{API}/auth/login", json=OWNER, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _default_loc(h):
    d = requests.get(f"{API}/inventory/locations", headers=h, timeout=20).json()
    return next(l["id"] for l in d if l["is_default"])


def _new_loc(h, typ="yard"):
    return requests.post(f"{API}/inventory/locations", headers=h, timeout=20, json={"name": f"QA {typ} {uuid.uuid4().hex[:5]}", "type": typ}).json()["id"]


def _material_onhand(h, mid):
    d = requests.get(f"{API}/materials", headers=h, timeout=20).json()
    return next(m for m in d if m["id"] == mid)["on_hand"]


def _stocked_material(h, qty=40):
    """Deterministic: create a brand-new material this test OWNS and receive `qty` to the DEFAULT
    location via a manual PO. Never depends on arbitrary preview-DB materials or execution order."""
    mid = requests.post(f"{API}/materials", headers=h, timeout=20, json={
        "name": f"QA AdvInv {uuid.uuid4().hex[:10]}", "unit": "EA", "category": "test", "quantity_on_hand": 0}).json()["id"]
    po = requests.post(f"{API}/purchase-orders", headers=h, timeout=20, json={
        "supplier_name": "QA AdvInv Supplier",
        "items": [{"material_id": mid, "description": "seed", "quantity": qty, "unit": "EA", "unit_cost": 5}]}).json()
    loc = _default_loc(h)
    r = requests.post(f"{API}/purchase-orders/{po['id']}/receive", headers=h, timeout=20,
                      json={"items": [{"po_item_id": po["items"][0]["id"], "quantity": qty}], "location_id": loc})
    assert r.status_code == 200, r.text  # stock now lives entirely at the default location
    return mid


def _balance_sum(h, mid):
    d = requests.get(f"{API}/inventory/balances", headers=h, params={"material_id": mid}, timeout=20).json()
    return round(sum(b["quantity_on_hand"] for b in d["balances"]), 3)


def _accepted_job(h):
    mid = _stocked_material(h)  # owns its own default-location stock
    cust = requests.get(f"{API}/customers", headers=h, timeout=20).json()
    cid = cust[0]["id"] if isinstance(cust, list) else cust["items"][0]["id"]
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": 10, "waste_percent": 0, "unit": "EA", "material_cost": 5}]}).json()
    q = requests.post(f"{API}/quotes", headers=h, timeout=20, json={"estimate_id": est["id"]}).json()
    job = requests.post(f"{API}/quotes/{q['id']}/accept", headers=h, timeout=20, json={"acceptance_name": "T"}).json()["job_id"]
    requests.post(f"{API}/jobs/{job}/materials/generate", headers=h, timeout=20)
    return job, mid


def test_backfill_balance_equals_company_onhand():
    h = _h()
    mid = _stocked_material(h)
    assert _balance_sum(h, mid) == round(_material_onhand(h, mid), 3)


def test_transfer_nets_to_zero():
    h = _h()
    mid = _stocked_material(h)
    before = _material_onhand(h, mid)
    src, dst = _default_loc(h), _new_loc(h)
    r = requests.post(f"{API}/inventory/transfer", headers=h, timeout=20, json={
        "material_id": mid, "source_location_id": src, "destination_location_id": dst, "quantity": 3})
    assert r.status_code == 200
    assert _material_onhand(h, mid) == before          # company total unchanged
    assert _balance_sum(h, mid) == round(before, 3)


def test_transfer_same_location_rejected():
    h = _h()
    mid = _stocked_material(h)
    src = _default_loc(h)
    r = requests.post(f"{API}/inventory/transfer", headers=h, timeout=20, json={
        "material_id": mid, "source_location_id": src, "destination_location_id": src, "quantity": 1})
    assert r.status_code == 400


def test_transfer_insufficient_rejected():
    h = _h()
    mid = _stocked_material(h)
    src, dst = _default_loc(h), _new_loc(h)
    r = requests.post(f"{API}/inventory/transfer", headers=h, timeout=20, json={
        "material_id": mid, "source_location_id": src, "destination_location_id": dst, "quantity": 999999})
    assert r.status_code == 400


def test_issue_consumes_reservation_and_reduces_onhand():
    h = _h()
    job, mid = _accepted_job(h)
    plan = requests.get(f"{API}/jobs/{job}/material-plan", headers=h, timeout=20).json()["materials"][0]
    # reserve some
    requests.post(f"{API}/jobs/{job}/materials/{plan['id']}/reserve", headers=h, timeout=20, json={"quantity": 4})
    onhand_before = _material_onhand(h, mid)
    loc = _default_loc(h)
    r = requests.post(f"{API}/inventory/issue", headers=h, timeout=20, json={
        "material_id": mid, "location_id": loc, "quantity": 4, "job_id": job})
    assert r.status_code == 200, r.text
    assert _material_onhand(h, mid) == round(onhand_before - 4, 3)   # On Hand reduced once
    p2 = requests.get(f"{API}/jobs/{job}/material-plan", headers=h, timeout=20).json()["materials"][0]
    assert p2["issued"] >= 4
    assert p2["reserved"] == 0                                       # reservation consumed


def test_return_restores_stock():
    h = _h()
    job, mid = _accepted_job(h)
    loc = _default_loc(h)
    requests.post(f"{API}/inventory/issue", headers=h, timeout=20, json={"material_id": mid, "location_id": loc, "quantity": 3, "job_id": job})
    before = _material_onhand(h, mid)
    r = requests.post(f"{API}/inventory/return", headers=h, timeout=20, json={"material_id": mid, "location_id": loc, "quantity": 2, "job_id": job})
    assert r.status_code == 200
    assert _material_onhand(h, mid) == round(before + 2, 3)
    p = requests.get(f"{API}/jobs/{job}/material-plan", headers=h, timeout=20).json()["materials"][0]
    assert p["returned"] >= 2 and p["net_used"] == round(p["issued"] - p["returned"], 3)


def test_waste_reduces_onhand():
    h = _h()
    mid = _stocked_material(h)
    loc = _default_loc(h)
    before = _material_onhand(h, mid)
    r = requests.post(f"{API}/inventory/disposition", headers=h, timeout=20, json={
        "material_id": mid, "location_id": loc, "quantity": 1, "kind": "waste", "reason": "test"})
    assert r.status_code == 200
    assert _material_onhand(h, mid) == round(before - 1, 3)


def test_cycle_count_creates_adjustment():
    h = _h()
    mid = _stocked_material(h)
    loc = _default_loc(h)
    cur = requests.get(f"{API}/inventory/balances", headers=h, params={"material_id": mid}, timeout=20).json()
    at = next((b["quantity_on_hand"] for b in cur["balances"] if b["location_id"] == loc), 0)
    r = requests.post(f"{API}/inventory/cycle-count", headers=h, timeout=20, json={
        "location_id": loc, "lines": [{"material_id": mid, "counted_quantity": at + 2}]})
    assert r.status_code == 200
    assert r.json()["results"][0]["variance"] == 2.0
    txns = requests.get(f"{API}/inventory/transactions", headers=h, params={"material_id": mid, "reason": "cycle_count"}, timeout=20).json()
    assert len(txns["transactions"]) >= 1


def test_auto_release_on_cancel_idempotent():
    h = _h()
    job, mid = _accepted_job(h)
    plan = requests.get(f"{API}/jobs/{job}/material-plan", headers=h, timeout=20).json()["materials"][0]
    requests.post(f"{API}/jobs/{job}/materials/{plan['id']}/reserve", headers=h, timeout=20, json={"quantity": 3})
    onhand = _material_onhand(h, mid)
    requests.patch(f"{API}/jobs/{job}", headers=h, timeout=20, json={"status": "cancelled"})
    p = requests.get(f"{API}/jobs/{job}/material-plan", headers=h, timeout=20).json()["materials"][0]
    assert p["reserved"] == 0                        # released
    assert _material_onhand(h, mid) == onhand        # On Hand unchanged by release
    # idempotent: cancelling again does not over-release (reserved already 0)
    requests.patch(f"{API}/jobs/{job}", headers=h, timeout=20, json={"status": "cancelled"})
    p2 = requests.get(f"{API}/jobs/{job}/material-plan", headers=h, timeout=20).json()["materials"][0]
    assert p2["reserved"] == 0


def test_abc_provider_po_recognized_and_draft():
    """A PO created with integration_provider=abc_supply is recognized as ABC and stays draft (not submitted)."""
    h = _h()
    sup = requests.get(f"{API}/suppliers", headers=h, timeout=20).json()
    abc = next(s for s in sup if s["integration_provider"] == "abc_supply")
    d = requests.get(f"{API}/materials", headers=h, timeout=20).json()
    mid = d[0]["id"]
    r = requests.post(f"{API}/purchase-orders", headers=h, timeout=20, json={
        "supplier_id": abc["id"], "integration_provider": "abc_supply",
        "items": [{"material_id": mid, "description": "x", "quantity": 2, "unit": "ea", "unit_cost": 10,
                   "integration_provider": "abc_supply", "abc_item_number": "ABC-1"}]})
    assert r.status_code == 201, r.text
    po = r.json()
    assert po["integration_provider"] == "abc_supply"
    assert po["status"] == "draft"          # never auto-submitted


def test_transaction_history_captures_movements():
    h = _h()
    mid = _stocked_material(h)
    loc = _default_loc(h)
    requests.post(f"{API}/inventory/disposition", headers=h, timeout=20, json={
        "material_id": mid, "location_id": loc, "quantity": 1, "kind": "waste", "reason": "hist test"})
    txns = requests.get(f"{API}/inventory/transactions", headers=h, params={"material_id": mid, "reason": "waste"}, timeout=20).json()
    assert len(txns["transactions"]) >= 1
    t = txns["transactions"][0]
    assert t["reason"] == "waste" and t["material_name"] and t["source_location"]
