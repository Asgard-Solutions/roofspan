"""Spec-closure: Purchasing/Inventory dashboard + Inventory On-Hand report + RBAC."""
import os, uuid, requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}


def _owner():
    return {"Authorization": f"Bearer {requests.post(f'{API}/auth/login', json=OWNER, timeout=20).json()['access_token']}"}


def _sales(h):
    e = f"qa_sales_{uuid.uuid4().hex[:8]}@example.com"
    requests.post(f"{API}/users", headers=h, timeout=20, json={"email": e, "full_name": "S", "password": "SalesQA#2026", "role": "sales"})
    return {"Authorization": f"Bearer {requests.post(f'{API}/auth/login', json={'email': e, 'password': 'SalesQA#2026'}, timeout=20).json()['access_token']}"}


def test_purchasing_dashboard_real_data_and_actions():
    h = _owner()
    d = requests.get(f"{API}/dashboard/purchasing", headers=h, timeout=30).json()
    c = d["cards"]
    for k in ("low_stock_items", "reserved_quantity", "open_purchase_orders", "incoming_this_week", "jobs_needing_materials", "backordered_items"):
        assert k in c
    assert d["cost_visible"] is True and "inventory_value" in c and c["inventory_value"] >= 0
    assert isinstance(d["action_required"], list)
    for a in d["action_required"]:
        assert a["link"] and a["message"] and a["type"]


def test_dashboard_hides_cost_from_sales():
    h = _owner()
    sd = requests.get(f"{API}/dashboard/purchasing", headers=_sales(h), timeout=30).json()
    assert sd["cost_visible"] is False
    assert "inventory_value" not in sd["cards"] and "open_po_committed_value" not in sd["cards"]
    # operational counts still present
    assert "open_purchase_orders" in sd["cards"]


def test_inventory_on_hand_report_and_csv():
    h = _owner()
    d = requests.get(f"{API}/reports/inventory/on-hand", headers=h, timeout=30).json()
    assert d["cost_visible"] is True and isinstance(d["rows"], list)
    if d["rows"]:
        r = d["rows"][0]
        for k in ("material", "on_hand", "reserved", "available", "on_order", "required", "projected", "avg_cost", "inventory_value"):
            assert k in r
    csv = requests.get(f"{API}/reports/inventory/on-hand.csv", headers=h, timeout=30)
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert "Inventory Value" in csv.text.splitlines()[0]


def test_inventory_report_rbac():
    h = _owner()
    sh = _sales(h)
    # sales may see operational on-hand but WITHOUT cost columns
    d = requests.get(f"{API}/reports/inventory/on-hand", headers=sh, timeout=30).json()
    assert d["cost_visible"] is False
    if d["rows"]:
        assert "avg_cost" not in d["rows"][0] and "inventory_value" not in d["rows"][0]
    # cost CSV export denied to sales
    assert requests.get(f"{API}/reports/inventory/on-hand.csv", headers=sh, timeout=20).status_code == 403
