"""Purchasing / Pricing / Customer-Output completion phase — backend regression."""
import os
import uuid
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}


def _owner():
    return {"Authorization": f"Bearer {requests.post(f'{API}/auth/login', json=OWNER, timeout=20).json()['access_token']}"}


def _sales(h):
    email = f"qa_sales_{uuid.uuid4().hex[:8]}@example.com"
    requests.post(f"{API}/users", headers=h, timeout=20, json={"email": email, "full_name": "S", "password": "SalesQA#2026", "role": "sales"})
    return {"Authorization": f"Bearer {requests.post(f'{API}/auth/login', json={'email': email, 'password': 'SalesQA#2026'}, timeout=20).json()['access_token']}"}


def _material(h):
    return requests.post(f"{API}/materials", headers=h, timeout=20, json={"name": f"QA PPO {uuid.uuid4().hex[:8]}", "unit": "EA", "quantity_on_hand": 0}).json()["id"]


def _customer(h):
    return requests.get(f"{API}/customers", headers=h, timeout=20).json()[0]["id"]


# ---------------- PO status history ----------------

def test_po_status_history_records_real_events_no_dupes():
    h = _owner()
    mid = _material(h)
    po = requests.post(f"{API}/purchase-orders", headers=h, timeout=20, json={
        "supplier_name": "QA PPO Supplier", "items": [{"material_id": mid, "description": "x", "quantity": 5, "unit": "EA", "unit_cost": 4}]}).json()
    ev = requests.get(f"{API}/purchase-orders/{po['id']}/status-history", headers=h, timeout=20).json()["events"]
    assert ev[0]["normalized_status"] == "draft"
    # meaningful change -> new event
    requests.post(f"{API}/purchase-orders/{po['id']}/status", headers=h, timeout=20, json={"status": "ordered"})
    # repeated same status -> NO duplicate
    requests.post(f"{API}/purchase-orders/{po['id']}/status", headers=h, timeout=20, json={"status": "ordered"})
    ev2 = requests.get(f"{API}/purchase-orders/{po['id']}/status-history", headers=h, timeout=20).json()["events"]
    statuses = [e["normalized_status"] for e in ev2]
    assert statuses.count("ordered") == 1 and statuses[-1] == "ordered"
    # receive -> partially/received event
    it = po["items"][0]["id"]
    requests.post(f"{API}/purchase-orders/{po['id']}/receive", headers=h, timeout=20, json={"items": [{"po_item_id": it, "quantity": 5}]})
    ev3 = requests.get(f"{API}/purchase-orders/{po['id']}/status-history", headers=h, timeout=20).json()["events"]
    assert ev3[-1]["normalized_status"] == "received"


# ---------------- Price Book auto-application ----------------

def _price_book(h, markup=25.0):
    pb = requests.post(f"{API}/estimating/price-books", headers=h, timeout=20, json={
        "name": f"QA PB {uuid.uuid4().hex[:6]}", "active": True, "is_default": False}).json()
    return pb["id"]


def test_price_book_auto_applies_general_markup_rule():
    h = _owner()
    pb = _price_book(h)
    requests.put(f"{API}/estimating/price-books/{pb}/entries", headers=h, timeout=20,
                 json=[{"target_type": "material", "rule_type": "markup", "markup_percent": 25}])  # general (no material_id)
    mid = _material(h)
    cid = _customer(h)
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0, "price_book_id": pb,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": 10, "waste_percent": 0, "unit": "EA", "material_cost": 4}]}).json()
    line = est["items"][0]
    assert abs(line["selling_unit_price"] - 5.0) < 1e-6      # 4 * 1.25
    assert est["price_book_id"] == pb


def test_price_book_exact_material_rule_wins_over_general():
    h = _owner()
    pb = _price_book(h)
    mid = _material(h)
    requests.put(f"{API}/estimating/price-books/{pb}/entries", headers=h, timeout=20, json=[
        {"target_type": "material", "rule_type": "markup", "markup_percent": 10},                # general
        {"target_type": "material", "material_id": mid, "rule_type": "fixed", "fixed_price": 99}, # exact
    ])
    cid = _customer(h)
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0, "price_book_id": pb,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": 1, "waste_percent": 0, "unit": "EA", "material_cost": 4}]}).json()
    assert abs(est["items"][0]["selling_unit_price"] - 99.0) < 1e-6


def test_user_price_override_respected_over_price_book():
    h = _owner()
    pb = _price_book(h)
    requests.put(f"{API}/estimating/price-books/{pb}/entries", headers=h, timeout=20,
                 json=[{"target_type": "material", "rule_type": "markup", "markup_percent": 25}])
    mid = _material(h); cid = _customer(h)
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0, "price_book_id": pb,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": 1, "waste_percent": 0, "unit": "EA", "material_cost": 4, "selling_unit_price": 12}]}).json()
    assert abs(est["items"][0]["selling_unit_price"] - 12.0) < 1e-6   # explicit price wins


def test_price_book_switch_preview_and_apply():
    h = _owner()
    mid = _material(h); cid = _customer(h)
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": 1, "waste_percent": 0, "unit": "EA", "material_cost": 4, "markup_percent": 0}]}).json()
    pb = _price_book(h)
    requests.put(f"{API}/estimating/price-books/{pb}/entries", headers=h, timeout=20,
                 json=[{"target_type": "material", "material_id": mid, "rule_type": "fixed", "fixed_price": 20}])
    pv = requests.post(f"{API}/estimates/{est['id']}/price-book/preview", headers=h, timeout=20, json={"price_book_id": pb}).json()
    assert pv["affected"] == 1 and abs(pv["lines"][0]["new_sell"] - 20.0) < 1e-6
    applied = requests.post(f"{API}/estimates/{est['id']}/price-book/apply", headers=h, timeout=20, json={"price_book_id": pb}).json()
    assert abs(applied["items"][0]["selling_unit_price"] - 20.0) < 1e-6


# ---------------- Margin guardrails ----------------

def test_margin_policy_warning_only():
    h = _owner()
    requests.put(f"{API}/margin-policy", headers=h, timeout=20, json={"enabled": True, "target_minimum_margin": 40})
    mid = _material(h); cid = _customer(h)
    # cost 8, sell 10 -> margin 20% (< 40 target)
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": 1, "waste_percent": 0, "unit": "EA", "material_cost": 8, "selling_unit_price": 10}]}).json()
    assert est["margin_warnings"]["enabled"] is True
    assert est["margin_warnings"]["overall_below"] is True
    assert len(est["margin_warnings"]["below_lines"]) == 1
    requests.put(f"{API}/margin-policy", headers=h, timeout=20, json={"enabled": False, "target_minimum_margin": 30})


# ---------------- Customer proposal ----------------

def _accepted_quote(h, mid, cost=5, markup=20):
    cid = _customer(h)
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": 10, "waste_percent": 0, "unit": "EA", "material_cost": cost, "markup_percent": markup}]}).json()
    q = requests.post(f"{API}/quotes", headers=h, timeout=20, json={"estimate_id": est["id"]}).json()
    return q["id"]


def test_proposal_json_is_customer_safe():
    h = _owner()
    qid = _accepted_quote(h, _material(h))
    data = requests.get(f"{API}/quotes/{qid}/proposal", headers=h, timeout=20).json()
    blob = str(data).lower()
    for forbidden in ["material_cost", "total_unit_cost", "markup", "margin", "base_cost", "supplier_cost", "best_known"]:
        assert forbidden not in blob, f"leaked {forbidden}"
    assert data["quote"]["number"] and data["lines"][0]["unit_price"] > 0


def test_proposal_pdf_generates():
    h = _owner()
    qid = _accepted_quote(h, _material(h))
    r = requests.get(f"{API}/quotes/{qid}/proposal.pdf", headers=h, timeout=30)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:4] == b"%PDF"


def test_sales_can_view_customer_proposal():
    h = _owner()
    qid = _accepted_quote(h, _material(h))
    sh = _sales(h)
    r = requests.get(f"{API}/quotes/{qid}/proposal", headers=sh, timeout=20)
    assert r.status_code == 200  # customer-safe -> sales (who sell) may view


# ---------------- Cost overrun alerts ----------------

def test_cost_overrun_alert_flag():
    h = _owner()
    mid = _material(h)
    po = requests.post(f"{API}/purchase-orders", headers=h, timeout=20, json={
        "supplier_name": "QA PPO Supplier", "items": [{"material_id": mid, "description": "x", "quantity": 20, "unit": "EA", "unit_cost": 5}]}).json()
    requests.post(f"{API}/purchase-orders/{po['id']}/receive", headers=h, timeout=20, json={"items": [{"po_item_id": po["items"][0]["id"], "quantity": 20}]})
    cid = _customer(h)
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": 10, "waste_percent": 0, "unit": "EA", "material_cost": 5, "markup_percent": 20}]}).json()
    q = requests.post(f"{API}/quotes", headers=h, timeout=20, json={"estimate_id": est["id"]}).json()
    job = requests.post(f"{API}/quotes/{q['id']}/accept", headers=h, timeout=20, json={"acceptance_name": "T"}).json()["job_id"]
    requests.post(f"{API}/jobs/{job}/materials/generate", headers=h, timeout=20)
    loc = next(l["id"] for l in requests.get(f"{API}/inventory/locations", headers=h, timeout=20).json() if l["is_default"])
    requests.post(f"{API}/inventory/issue", headers=h, timeout=20, json={"material_id": mid, "location_id": loc, "quantity": 15, "job_id": job})  # 75 > est 50
    alerts = requests.get(f"{API}/jobs/{job}/costing", headers=h, timeout=20).json()["summary"]["alerts"]
    assert alerts["over_budget"] is True and alerts["material_overrun"] is True
    assert abs(alerts["total_overrun_amount"] - 25.0) < 1e-6


# ---------------- CSV export RBAC ----------------

def test_csv_exports_owner_ok_sales_denied():
    h = _owner()
    for r in ["profitability.csv", "cost-variance.csv", "material-variance.csv", "waste.csv", "supplier-impact.csv"]:
        resp = requests.get(f"{API}/reports/costing/{r}", headers=h, timeout=30)
        assert resp.status_code == 200 and resp.headers.get("content-type", "").startswith("text/csv"), r
    sh = _sales(h)
    for r in ["profitability.csv", "cost-variance.csv", "material-variance.csv", "waste.csv", "supplier-impact.csv"]:
        assert requests.get(f"{API}/reports/costing/{r}", headers=sh, timeout=20).status_code == 403, r
