"""Actual Job Costing — Batch 4 reporting (profitability, material variance, waste, supplier impact)
plus Sales-role protection on every report endpoint."""
import os
import uuid
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
REPORTS = ["profitability", "material-variance", "waste", "supplier-impact"]


def _owner():
    r = requests.post(f"{API}/auth/login", json=OWNER, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _sales(h):
    email = f"qa_sales_{uuid.uuid4().hex[:8]}@example.com"
    requests.post(f"{API}/users", headers=h, timeout=20,
                  json={"email": email, "full_name": "QA Sales", "password": "SalesQA#2026", "role": "sales"})
    lr = requests.post(f"{API}/auth/login", json={"email": email, "password": "SalesQA#2026"}, timeout=20)
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}


def _seed_costed_job(h):
    cid = requests.get(f"{API}/customers", headers=h, timeout=20).json()[0]["id"]
    mid = requests.post(f"{API}/materials", headers=h, timeout=20, json={
        "name": f"QA Rpt {uuid.uuid4().hex[:8]}", "unit": "EA", "quantity_on_hand": 0}).json()["id"]
    po = requests.post(f"{API}/purchase-orders", headers=h, timeout=20, json={
        "supplier_name": "QA Report Supplier",
        "items": [{"material_id": mid, "description": "x", "quantity": 20, "unit": "EA", "unit_cost": 5}]}).json()
    requests.post(f"{API}/purchase-orders/{po['id']}/receive", headers=h, timeout=20,
                  json={"items": [{"po_item_id": po["items"][0]["id"], "quantity": 20}]})
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": 10, "waste_percent": 0,
                   "unit": "EA", "material_cost": 5, "markup_percent": 20}]}).json()
    q = requests.post(f"{API}/quotes", headers=h, timeout=20, json={"estimate_id": est["id"]}).json()
    job = requests.post(f"{API}/quotes/{q['id']}/accept", headers=h, timeout=20, json={"acceptance_name": "T"}).json()["job_id"]
    requests.post(f"{API}/jobs/{job}/materials/generate", headers=h, timeout=20)
    loc = next(l["id"] for l in requests.get(f"{API}/inventory/locations", headers=h, timeout=20).json() if l["is_default"])
    requests.post(f"{API}/inventory/issue", headers=h, timeout=20,
                  json={"material_id": mid, "location_id": loc, "quantity": 10, "job_id": job})
    requests.post(f"{API}/inventory/disposition", headers=h, timeout=20,
                  json={"material_id": mid, "location_id": loc, "quantity": 2, "kind": "waste", "job_id": job, "reason": "qa"})
    return job, mid


def test_profitability_report_includes_costed_job():
    h = _owner()
    job, mid = _seed_costed_job(h)
    d = requests.get(f"{API}/reports/costing/profitability", headers=h, timeout=20).json()
    row = next((r for r in d["rows"] if r["job_id"] == job), None)
    assert row is not None
    assert abs(row["revenue"] - 60.0) < 1e-6
    assert abs(row["actual_cost"] - 60.0) < 1e-6      # 10 issued*5 + 2 waste*5
    assert "actual_gross_margin_percent" in row
    assert "actual_gross_profit" in d["totals"]


def test_material_variance_report():
    h = _owner()
    job, mid = _seed_costed_job(h)
    d = requests.get(f"{API}/reports/costing/material-variance", headers=h, timeout=20).json()
    row = next((r for r in d["rows"] if r["material_id"] == mid), None)
    assert row is not None
    assert abs(row["estimated_cost"] - 50.0) < 1e-6
    assert abs(row["actual_cost"] - 60.0) < 1e-6
    assert abs(row["variance"] - 10.0) < 1e-6


def test_waste_report():
    h = _owner()
    job, mid = _seed_costed_job(h)
    d = requests.get(f"{API}/reports/costing/waste", headers=h, timeout=20).json()
    row = next((r for r in d["rows"] if r["material_id"] == mid), None)
    assert row is not None and abs(row["waste_cost"] - 10.0) < 1e-6
    assert d["total_waste_cost"] >= 10.0


def test_supplier_impact_report():
    h = _owner()
    _seed_costed_job(h)
    d = requests.get(f"{API}/reports/costing/supplier-impact", headers=h, timeout=20).json()
    assert any(r["supplier_name"] == "QA Report Supplier" and r["received_cost"] > 0 for r in d["rows"])
    assert d["total_received_cost"] > 0


def test_sales_blocked_from_all_reports():
    h = _owner()
    sh = _sales(h)
    for r in REPORTS:
        resp = requests.get(f"{API}/reports/costing/{r}", headers=sh, timeout=20)
        assert resp.status_code == 403, f"{r} -> {resp.status_code}"
