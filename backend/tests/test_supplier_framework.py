"""Supplier Framework tests (Slices 2,3,6): supplier CRUD, connector capabilities, manual supplier
materials, immutable price history, Best Known Cost vs Preferred."""
import os
import uuid
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")


def _h():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": OWNER[0], "password": OWNER[1]}, timeout=30)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_abc_supplier_advertises_capabilities_manual_does_not():
    h = _h()
    sups = requests.get(f"{BASE_URL}/api/suppliers", headers=h, timeout=30).json()
    abc = next(s for s in sups if s["name"] == "ABC Supply")
    assert abc["integration_provider"] == "abc_supply"
    assert "catalog_search" in abc["capabilities"] and "online_order_submission" in abc["capabilities"]
    manual = [s for s in sups if not s["integration_provider"]]
    assert all(s["capabilities"] == [] for s in manual)


def test_supplier_crud_and_deactivate():
    h = _h(); tag = uuid.uuid4().hex[:6]
    s = requests.post(f"{BASE_URL}/api/suppliers", headers=h, json={"name": f"Sup {tag}", "supplier_type": "distributor", "payment_terms": "Net 30"}, timeout=30).json()
    assert s["integration_status"] == "manual" and s["payment_terms"] == "Net 30"
    upd = requests.patch(f"{BASE_URL}/api/suppliers/{s['id']}", headers=h, json={"sales_rep": "Jane"}, timeout=30).json()
    assert upd["sales_rep"] == "Jane"
    off = requests.post(f"{BASE_URL}/api/suppliers/{s['id']}/active?active=false", headers=h, timeout=30).json()
    assert off["active"] is False
    detail = requests.get(f"{BASE_URL}/api/suppliers/{s['id']}", headers=h, timeout=30).json()
    assert "products" in detail and "supplier" in detail


def test_manual_supplier_material_price_history_and_best_known_cost():
    h = _h(); tag = uuid.uuid4().hex[:6]
    sid = requests.post(f"{BASE_URL}/api/suppliers", headers=h, json={"name": f"PriceSup {tag}"}, timeout=30).json()["id"]
    # fresh custom material for isolation
    mid = requests.post(f"{BASE_URL}/api/materials", headers=h, json={"name": f"PriceMat {tag}", "unit": "each"}, timeout=30).json()["id"]
    sm = requests.post(f"{BASE_URL}/api/supplier-materials", headers=h, json={"material_id": mid, "supplier_id": sid, "supplier_item_number": f"X-{tag}", "current_cost": 50.0}, timeout=30).json()
    assert sm["price_status"] == "manual" and sm["current_cost"] == 50.0
    requests.patch(f"{BASE_URL}/api/supplier-materials/{sm['id']}", headers=h, json={"current_cost": 45.0}, timeout=30)
    hist = requests.get(f"{BASE_URL}/api/supplier-materials/{sm['id']}/price-history", headers=h, timeout=30).json()
    assert len(hist) == 2 and sorted(e["cost"] for e in hist) == [45.0, 50.0]  # immutable snapshots
    assert all(e["source"] == "manual" for e in hist)
    detail = requests.get(f"{BASE_URL}/api/materials/{mid}/detail", headers=h, timeout=30).json()
    # Best Known Cost = lowest active supplier cost (45.0). This material's only mapping is this manual one.
    assert detail["material"]["best_known_cost"] == 45.0
    # the sole mapping is preferred (first mapping)
    assert any(s["is_preferred"] for s in detail["suppliers"])
