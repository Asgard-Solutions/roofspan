"""Actual Job Costing — Batch 1 regression (MWAC cost basis, issue/return/waste cost snapshots,
estimated baseline). HTTP integration against the running backend."""
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


def _customer_id(h):
    c = requests.get(f"{API}/customers", headers=h, timeout=20).json()
    return (c[0]["id"] if isinstance(c, list) else c["items"][0]["id"])


def _new_material(h, on_hand=0):
    r = requests.post(f"{API}/materials", headers=h, timeout=20, json={
        "name": f"QA Cost {uuid.uuid4().hex[:8]}", "unit": "EA", "category": "test",
        "quantity_on_hand": on_hand})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _po_receive(h, mid, qty, unit_cost):
    """Create a 1-line manual PO for material and receive it fully at unit_cost."""
    po = requests.post(f"{API}/purchase-orders", headers=h, timeout=20, json={
        "supplier_name": "QA Costing Supplier",
        "items": [{"material_id": mid, "description": "qa", "quantity": qty, "unit": "EA", "unit_cost": unit_cost}]}).json()
    item_id = po["items"][0]["id"]
    r = requests.post(f"{API}/purchase-orders/{po['id']}/receive", headers=h, timeout=20,
                      json={"items": [{"po_item_id": item_id, "quantity": qty}]})
    assert r.status_code == 200, r.text
    return po["id"]


def _accepted_job_for(h, mid, material_cost, measured=10):
    cid = _customer_id(h)
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": measured,
                   "waste_percent": 0, "unit": "EA", "material_cost": material_cost, "markup_percent": 20}]}).json()
    q = requests.post(f"{API}/quotes", headers=h, timeout=20, json={"estimate_id": est["id"]}).json()
    job = requests.post(f"{API}/quotes/{q['id']}/accept", headers=h, timeout=20, json={"acceptance_name": "T"}).json()["job_id"]
    requests.post(f"{API}/jobs/{job}/materials/generate", headers=h, timeout=20)
    return job


def _issue_txn(h, mid, job):
    txns = requests.get(f"{API}/inventory/transactions", headers=h,
                        params={"material_id": mid, "job_id": job, "reason": "job_issue"}, timeout=20).json()["transactions"]
    return txns[0] if txns else None


def _costing_line(h, job, mid):
    c = requests.get(f"{API}/jobs/{job}/costing", headers=h, timeout=20).json()
    return c, next((l for l in c["material_actual"]["lines"] if l["material_id"] == mid), None)


# ---------------------------------------------------------------------------

def test_mwac_recomputes_on_receipts_and_snapshots_on_issue():
    h = _h()
    mid = _new_material(h)
    _po_receive(h, mid, 10, 4.00)     # avg -> 4.00
    _po_receive(h, mid, 10, 6.00)     # avg -> (40+60)/20 = 5.00
    job = _accepted_job_for(h, mid, material_cost=5.0)
    loc = _default_loc(h)
    r = requests.post(f"{API}/inventory/issue", headers=h, timeout=20,
                      json={"material_id": mid, "location_id": loc, "quantity": 10, "job_id": job})
    assert r.status_code == 200, r.text
    t = _issue_txn(h, mid, job)
    assert t and abs(t["unit_cost"] - 5.00) < 1e-6            # snapshot = MWAC at issue
    assert abs(t["extended_cost"] - (-50.00)) < 1e-6
    _, line = _costing_line(h, job, mid)
    assert abs(line["issued_cost"] - 50.00) < 1e-6
    assert abs(line["actual_material_cost"] - 50.00) < 1e-6
    assert line["cost_basis_status"] == "complete"


def test_issue_cost_snapshot_is_immutable_when_mwac_changes_later():
    h = _h()
    mid = _new_material(h)
    _po_receive(h, mid, 10, 4.00)
    _po_receive(h, mid, 10, 6.00)     # avg 5.00, on hand 20
    job = _accepted_job_for(h, mid, material_cost=5.0)
    loc = _default_loc(h)
    requests.post(f"{API}/inventory/issue", headers=h, timeout=20,
                  json={"material_id": mid, "location_id": loc, "quantity": 10, "job_id": job})
    # change MWAC materially with an expensive receipt AFTER the issue
    _po_receive(h, mid, 10, 20.00)
    t = _issue_txn(h, mid, job)
    assert abs(t["unit_cost"] - 5.00) < 1e-6                 # unchanged (final at issue time)
    _, line = _costing_line(h, job, mid)
    assert abs(line["actual_material_cost"] - 50.00) < 1e-6  # not revalued


def test_return_reverses_cost_at_outstanding_issued_basis():
    h = _h()
    mid = _new_material(h)
    _po_receive(h, mid, 20, 5.00)     # avg 5.00
    job = _accepted_job_for(h, mid, material_cost=5.0)
    loc = _default_loc(h)
    requests.post(f"{API}/inventory/issue", headers=h, timeout=20,
                  json={"material_id": mid, "location_id": loc, "quantity": 10, "job_id": job})
    r = requests.post(f"{API}/inventory/return", headers=h, timeout=20,
                      json={"material_id": mid, "location_id": loc, "quantity": 4, "job_id": job})
    assert r.status_code == 200, r.text
    _, line = _costing_line(h, job, mid)
    assert abs(line["returned_cost"] - 20.00) < 1e-6          # 4 * 5.00 issued basis
    assert abs(line["actual_material_cost"] - 30.00) < 1e-6   # 50 - 20
    assert abs(line["net_used_quantity"] - 6.0) < 1e-6


def test_waste_costed_separately_from_productive_use():
    h = _h()
    mid = _new_material(h)
    _po_receive(h, mid, 20, 5.00)
    job = _accepted_job_for(h, mid, material_cost=5.0)
    loc = _default_loc(h)
    requests.post(f"{API}/inventory/issue", headers=h, timeout=20,
                  json={"material_id": mid, "location_id": loc, "quantity": 8, "job_id": job})
    r = requests.post(f"{API}/inventory/disposition", headers=h, timeout=20,
                      json={"material_id": mid, "location_id": loc, "quantity": 2, "kind": "waste", "job_id": job, "reason": "qa"})
    assert r.status_code == 200, r.text
    _, line = _costing_line(h, job, mid)
    assert abs(line["issued_cost"] - 40.00) < 1e-6
    assert abs(line["waste_cost"] - 10.00) < 1e-6             # 2 * 5.00 tracked separately
    assert abs(line["actual_material_cost"] - 50.00) < 1e-6   # issued + waste


def test_missing_cost_basis_flagged_when_no_receipt_cost():
    h = _h()
    mid = _new_material(h, on_hand=50)                        # stock exists but no priced receipt -> avg NULL
    job = _accepted_job_for(h, mid, material_cost=5.0)
    loc = _default_loc(h)
    requests.post(f"{API}/inventory/issue", headers=h, timeout=20,
                  json={"material_id": mid, "location_id": loc, "quantity": 5, "job_id": job})
    t = _issue_txn(h, mid, job)
    assert t["unit_cost"] is None and t["extended_cost"] is None
    c, line = _costing_line(h, job, mid)
    assert line["cost_basis_status"] == "missing_cost_basis"
    assert c["material_actual"]["has_missing_cost_basis"] is True


def test_estimated_baseline_from_accepted_quote():
    h = _h()
    mid = _new_material(h)
    job = _accepted_job_for(h, mid, material_cost=5.0, measured=10)
    c = requests.get(f"{API}/jobs/{job}/costing", headers=h, timeout=20).json()
    b = c["baseline"]
    assert b["baseline_status"] == "quote"
    assert abs(b["estimated_material_cost"] - 50.00) < 1e-6   # 10 units * 5.00 snapshot cost
    assert abs(b["estimated_selling"] - 60.00) < 1e-6         # 20% markup on 50 cost
    assert abs(b["estimated_gross_profit"] - 10.00) < 1e-6
    # per-material estimated cost also flows to the material line
    _, line = _costing_line(h, job, mid)
    assert abs(line["estimated_material_cost"] - 50.00) < 1e-6


def test_no_baseline_marked_when_job_has_no_quote():
    h = _h()
    # a job created directly on a customer (no quote) has no historical baseline
    from datetime import datetime
    cid = _customer_id(h)
    # jobs are normally quote-derived; if a direct-create path isn't exposed, skip gracefully
    r = requests.post(f"{API}/jobs", headers=h, timeout=20, json={"customer_id": cid})
    if r.status_code not in (200, 201):
        import pytest
        pytest.skip("no direct job-create endpoint")
    job = r.json()["id"]
    b = requests.get(f"{API}/jobs/{job}/costing", headers=h, timeout=20).json()["baseline"]
    assert b["baseline_status"] == "none"
