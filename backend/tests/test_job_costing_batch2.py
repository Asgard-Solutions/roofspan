"""Actual Job Costing — Batch 2 regression (manual actual costs, estimated-vs-actual summary,
variance, gross profit/margin, costing status, immutable completion snapshot)."""
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


def _new_material(h):
    r = requests.post(f"{API}/materials", headers=h, timeout=20, json={
        "name": f"QA Cost2 {uuid.uuid4().hex[:8]}", "unit": "EA", "category": "test", "quantity_on_hand": 0})
    return r.json()["id"]


def _po_receive(h, mid, qty, unit_cost):
    po = requests.post(f"{API}/purchase-orders", headers=h, timeout=20, json={
        "supplier_name": "QA Costing Supplier",
        "items": [{"material_id": mid, "description": "qa", "quantity": qty, "unit": "EA", "unit_cost": unit_cost}]}).json()
    requests.post(f"{API}/purchase-orders/{po['id']}/receive", headers=h, timeout=20,
                  json={"items": [{"po_item_id": po["items"][0]["id"], "quantity": qty}]})


def _accepted_job(h, mid, material_cost=5.0, measured=10, markup=20):
    cid = _customer_id(h)
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": measured,
                   "waste_percent": 0, "unit": "EA", "material_cost": material_cost, "markup_percent": markup}]}).json()
    q = requests.post(f"{API}/quotes", headers=h, timeout=20, json={"estimate_id": est["id"]}).json()
    return requests.post(f"{API}/quotes/{q['id']}/accept", headers=h, timeout=20, json={"acceptance_name": "T"}).json()["job_id"]


def _costing(h, job):
    return requests.get(f"{API}/jobs/{job}/costing", headers=h, timeout=20).json()


# ---------------------------------------------------------------------------

def test_manual_actual_costs_grouped_by_category():
    h = _h()
    mid = _new_material(h)
    job = _accepted_job(h, mid)
    requests.post(f"{API}/jobs/{job}/actual-costs", headers=h, timeout=20,
                  json={"category": "labor", "description": "Crew day 1", "amount": 800})
    requests.post(f"{API}/jobs/{job}/actual-costs", headers=h, timeout=20,
                  json={"category": "labor", "quantity": 10, "unit_rate": 45})   # amount derived = 450
    requests.post(f"{API}/jobs/{job}/actual-costs", headers=h, timeout=20,
                  json={"category": "permits", "amount": 150})
    m = requests.get(f"{API}/jobs/{job}/actual-costs", headers=h, timeout=20).json()
    assert abs(m["category_totals"]["labor"] - 1250.0) < 1e-6
    assert abs(m["category_totals"]["permits"] - 150.0) < 1e-6
    assert abs(m["total_manual_cost"] - 1400.0) < 1e-6
    assert len(m["entries"]) == 3


def test_invalid_category_rejected():
    h = _h()
    mid = _new_material(h)
    job = _accepted_job(h, mid)
    r = requests.post(f"{API}/jobs/{job}/actual-costs", headers=h, timeout=20,
                      json={"category": "payroll", "amount": 100})
    assert r.status_code == 422


def test_summary_estimated_vs_actual_variance_and_margin():
    h = _h()
    mid = _new_material(h)
    _po_receive(h, mid, 20, 5.00)                  # MWAC 5.00
    job = _accepted_job(h, mid, material_cost=5.0, measured=10, markup=20)  # est material 50, revenue 60
    loc = _default_loc(h)
    requests.post(f"{API}/inventory/issue", headers=h, timeout=20,
                  json={"material_id": mid, "location_id": loc, "quantity": 12, "job_id": job})  # actual material 60
    requests.post(f"{API}/jobs/{job}/actual-costs", headers=h, timeout=20,
                  json={"category": "labor", "amount": 5})
    s = _costing(h, job)["summary"]
    assert abs(s["revenue"] - 60.0) < 1e-6
    assert abs(s["estimated"]["material"] - 50.0) < 1e-6
    assert abs(s["actual"]["material"] - 60.0) < 1e-6
    assert abs(s["actual"]["labor"] - 5.0) < 1e-6
    assert abs(s["actual"]["total"] - 65.0) < 1e-6
    assert abs(s["variance"]["material"] - 10.0) < 1e-6        # over by 10
    assert abs(s["estimated"]["gross_profit"] - 10.0) < 1e-6   # 60 - 50
    assert abs(s["actual"]["gross_profit"] - (-5.0)) < 1e-6    # 60 - 65 (lost money)
    assert s["costing_status"] in ("partial", "complete")


def test_missing_cost_basis_status_propagates_to_summary():
    h = _h()
    mid = _new_material(h)
    r = requests.post(f"{API}/materials", headers=h, timeout=20, json={
        "name": f"QA NoBasis {uuid.uuid4().hex[:8]}", "unit": "EA", "quantity_on_hand": 40})
    mid = r.json()["id"]
    job = _accepted_job(h, mid)
    loc = _default_loc(h)
    requests.post(f"{API}/inventory/issue", headers=h, timeout=20,
                  json={"material_id": mid, "location_id": loc, "quantity": 5, "job_id": job})
    s = _costing(h, job)["summary"]
    assert s["costing_status"] == "missing_cost_basis"


def test_completion_creates_immutable_snapshot():
    h = _h()
    mid = _new_material(h)
    _po_receive(h, mid, 20, 5.00)
    job = _accepted_job(h, mid, material_cost=5.0, measured=10, markup=20)
    loc = _default_loc(h)
    requests.post(f"{API}/inventory/issue", headers=h, timeout=20,
                  json={"material_id": mid, "location_id": loc, "quantity": 10, "job_id": job})
    requests.post(f"{API}/jobs/{job}/actual-costs", headers=h, timeout=20,
                  json={"category": "labor", "amount": 3})
    # complete the job -> snapshot captured
    r = requests.patch(f"{API}/jobs/{job}", headers=h, timeout=20, json={"status": "completed"})
    assert r.status_code == 200, r.text
    snaps = requests.get(f"{API}/jobs/{job}/cost-snapshots", headers=h, timeout=20).json()["snapshots"]
    assert len(snaps) >= 1
    snap = snaps[0]
    assert snap["trigger"] == "completion"
    assert snap["costing_status"] == "complete"
    assert abs(snap["actual_total_cost"] - 53.0) < 1e-6       # 50 material + 3 labor
    assert abs(snap["revenue"] - 60.0) < 1e-6
    # immutability: adding a cost AFTER completion does not alter the captured snapshot
    requests.post(f"{API}/jobs/{job}/actual-costs", headers=h, timeout=20,
                  json={"category": "equipment", "amount": 999})
    snaps2 = requests.get(f"{API}/jobs/{job}/cost-snapshots", headers=h, timeout=20).json()["snapshots"]
    frozen = next(s for s in snaps2 if s["id"] == snap["id"])
    assert abs(frozen["actual_total_cost"] - 53.0) < 1e-6     # unchanged
