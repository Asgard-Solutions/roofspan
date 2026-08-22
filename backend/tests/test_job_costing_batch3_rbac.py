"""Actual Job Costing — Batch 3 RBAC (Sales role must never receive cost / margin / profitability data)."""
import os
import uuid
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}


def _owner():
    r = requests.post(f"{API}/auth/login", json=OWNER, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _sales_headers(h):
    """Create (idempotently) a sales user and return its auth headers."""
    email = f"qa_sales_{uuid.uuid4().hex[:8]}@example.com"
    pw = "SalesQA#2026"
    r = requests.post(f"{API}/users", headers=h, timeout=20,
                      json={"email": email, "full_name": "QA Sales", "password": pw, "role": "sales"})
    assert r.status_code in (201, 409), r.text
    lr = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert lr.status_code == 200, lr.text
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}, email


def _a_job(h):
    cid = requests.get(f"{API}/customers", headers=h, timeout=20).json()[0]["id"]
    mid = requests.post(f"{API}/materials", headers=h, timeout=20, json={
        "name": f"QA Cost3 {uuid.uuid4().hex[:8]}", "unit": "EA", "quantity_on_hand": 0}).json()["id"]
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": 10, "waste_percent": 0,
                   "unit": "EA", "material_cost": 5, "markup_percent": 20}]}).json()
    q = requests.post(f"{API}/quotes", headers=h, timeout=20, json={"estimate_id": est["id"]}).json()
    return requests.post(f"{API}/quotes/{q['id']}/accept", headers=h, timeout=20, json={"acceptance_name": "T"}).json()["job_id"], mid


def test_sales_blocked_from_costing_endpoints():
    h = _owner()
    job, mid = _a_job(h)
    sh, _ = _sales_headers(h)
    for path, method, body in [
        (f"/jobs/{job}/costing", "get", None),
        (f"/jobs/{job}/actual-costs", "get", None),
        (f"/jobs/{job}/actual-costs", "post", {"category": "labor", "amount": 100}),
        (f"/jobs/{job}/cost-snapshots", "get", None),
        (f"/jobs/{job}/cost-snapshots", "post", {"trigger": "manual"}),
    ]:
        fn = getattr(requests, method)
        r = fn(f"{API}{path}", headers=sh, timeout=20, **({"json": body} if body else {}))
        assert r.status_code == 403, f"{method.upper()} {path} -> {r.status_code} (expected 403)"


def test_owner_allowed_costing():
    h = _owner()
    job, mid = _a_job(h)
    r = requests.get(f"{API}/jobs/{job}/costing", headers=h, timeout=20)
    assert r.status_code == 200
    assert "summary" in r.json()


def test_sales_transactions_hide_cost_basis():
    h = _owner()
    job, mid = _a_job(h)
    # give the material cost basis + issue to create a costed ledger txn
    po = requests.post(f"{API}/purchase-orders", headers=h, timeout=20, json={
        "supplier_name": "QA Costing Supplier",
        "items": [{"material_id": mid, "description": "x", "quantity": 10, "unit": "EA", "unit_cost": 5}]}).json()
    requests.post(f"{API}/purchase-orders/{po['id']}/receive", headers=h, timeout=20,
                  json={"items": [{"po_item_id": po["items"][0]["id"], "quantity": 10}]})
    loc = next(l["id"] for l in requests.get(f"{API}/inventory/locations", headers=h, timeout=20).json() if l["is_default"])
    requests.post(f"{API}/inventory/issue", headers=h, timeout=20,
                  json={"material_id": mid, "location_id": loc, "quantity": 4, "job_id": job})
    # owner sees cost on transactions
    ot = requests.get(f"{API}/inventory/transactions", headers=h, params={"material_id": mid, "reason": "job_issue"}, timeout=20).json()["transactions"]
    assert ot and ot[0]["unit_cost"] is not None
    # sales sees the transaction row but NOT the cost fields
    sh, _ = _sales_headers(h)
    stx = requests.get(f"{API}/inventory/transactions", headers=sh, params={"material_id": mid, "reason": "job_issue"}, timeout=20).json()["transactions"]
    assert stx and stx[0]["unit_cost"] is None and stx[0]["extended_cost"] is None
