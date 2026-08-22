"""Estimating Modernization regression — calc engine (unit) + API (integration via requests).
Covers cost/waste/markup/margin/UOM, assemblies+expand+versioning, price books default,
quote snapshot (cost hidden), multi-package accept, cost-refresh (no auto-apply)."""
import os
import uuid
import requests

from services import estimating as calc

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}


def _h():
    r = requests.post(f"{API}/auth/login", json=OWNER, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------- calc engine unit tests ----------------
def test_waste_calculated_quantity():
    assert calc.calculated_quantity(31.5, 12) == 35.28


def test_markup_vs_margin_distinct():
    assert calc.price_from_markup(100, 25) == 125.0
    assert calc.margin_from_prices(100, 125) == 20.0
    assert calc.markup_from_prices(100, 125) == 25.0
    assert calc.price_from_margin(100, 20) == 125.0


def test_order_quantity_ceil():
    assert calc.order_quantity(35.28, 1) == 36.0
    assert calc.order_quantity(10, 3) == 30.0
    assert calc.order_quantity(10, None) is None


def test_compute_line_markup_mode():
    line = {"material_cost": 100, "measured_quantity": 10, "waste_percent": 10,
            "markup_percent": 20, "pricing_mode": "markup", "unit": "SQ"}
    calc.compute_line(line)
    assert line["quantity"] == 11.0
    assert line["selling_unit_price"] == 120.0
    assert line["line_total"] == 1320.0


def test_summarize_margin():
    lines = [{"quantity": 10, "material_cost": 100, "labor_cost": 0, "equipment_cost": 0,
              "subcontract_cost": 0, "line_total": 1200, "_unit_cost": 100}]
    s = calc.summarize(lines, tax_rate=5)
    assert s["estimated_total_cost"] == 1000.0
    assert s["gross_profit"] == 200.0
    assert s["gross_margin_pct"] == 16.67
    assert s["tax"] == 60.0


# ---------------- API integration ----------------
def test_default_price_book_exists():
    r = requests.get(f"{API}/estimating/price-books", headers=_h(), timeout=20)
    assert r.status_code == 200
    assert len([b for b in r.json() if b["is_default"]]) == 1


def test_estimate_waste_and_summary():
    h = _h()
    r = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "tax_rate": 0,
        "items": [{"description": "Shingles", "line_kind": "material", "measured_quantity": 20,
                   "waste_percent": 10, "material_cost": 100, "markup_percent": 25,
                   "pricing_mode": "markup", "unit": "SQ"}]})
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["can_see_cost"] is True
    line = e["items"][0]
    assert line["quantity"] == 22.0
    assert line["selling_unit_price"] == 125.0
    assert e["cost_summary"]["estimated_total_cost"] == 2200.0
    assert e["cost_summary"]["gross_margin_pct"] == 20.0


def test_assembly_create_expand_versioning():
    h = _h()
    name = f"TEST Assembly {uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/estimating/assemblies", headers=h, timeout=20, json={
        "name": name, "unit_basis": "SQ",
        "items": [{"description": "Underlayment", "quantity_factor": 1, "unit": "RL", "waste_override": 5},
                  {"description": "Nails", "quantity_factor": 2, "unit": "BX"}]})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    d = requests.post(f"{API}/estimating/assemblies/{aid}/expand?quantity=20", headers=h, timeout=20).json()
    assert d["assembly_version"] == 1
    lines = {l["description"]: l for l in d["lines"]}
    assert lines["Underlayment"]["quantity"] == 21.0
    assert lines["Nails"]["measured_quantity"] == 40.0
    r2 = requests.put(f"{API}/estimating/assemblies/{aid}", headers=h, timeout=20, json={
        "name": name, "unit_basis": "SQ", "items": [{"description": "Underlayment", "quantity_factor": 2, "unit": "RL"}]})
    assert r2.json()["version"] == 2


def test_quote_hides_cost_and_snapshots():
    h = _h()
    e = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "tax_rate": 0, "items": [{"description": "Item", "measured_quantity": 5, "material_cost": 80,
                                  "markup_percent": 25, "pricing_mode": "markup", "unit": "EA"}]}).json()
    q = requests.post(f"{API}/quotes", headers=h, timeout=20, json={"estimate_id": e["id"]}).json()
    assert q["items"][0]["unit_price"] == 100.0
    assert q["items"][0]["material_cost"] is None


def test_multi_package_quote_accept():
    h = _h()
    q = requests.post(f"{API}/quotes", headers=h, timeout=20, json={
        "tax_rate": 0, "multi_package": True, "packages": [
            {"name": "Good", "tier": 1, "items": [{"description": "A", "quantity": 10, "unit": "SQ", "selling_unit_price": 100}]},
            {"name": "Best", "tier": 3, "items": [{"description": "B", "quantity": 10, "unit": "SQ", "selling_unit_price": 200}]}]}).json()
    pkgs = {p["name"]: p for p in q["packages"]}
    assert pkgs["Good"]["total"] == 1000.0 and pkgs["Best"]["total"] == 2000.0
    rf = requests.post(f"{API}/quotes/{q['id']}/accept", headers=h, timeout=20, json={"acceptance_name": "X"})
    assert rf.status_code == 400
    r = requests.post(f"{API}/quotes/{q['id']}/accept", headers=h, timeout=20,
                      json={"acceptance_name": "X", "package_id": pkgs["Best"]["id"]})
    assert r.status_code == 200
    assert r.json()["quote"]["accepted_package_id"] == pkgs["Best"]["id"]
    assert r.json()["quote"]["total"] == 2000.0


def test_cost_refresh_preview_no_autoapply():
    h = _h()
    e = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "tax_rate": 0, "items": [{"description": "Custom", "quantity": 1, "unit_price": 50}]}).json()
    r = requests.get(f"{API}/estimates/{e['id']}/cost-refresh/preview", headers=h, timeout=20)
    assert r.status_code == 200
    assert r.json()["changed_count"] == 0


def test_legacy_custom_estimate_still_works():
    h = _h()
    r = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "tax_rate": 8.5, "items": [{"description": "Legacy line", "quantity": 2, "unit": "ea", "unit_price": 150}]})
    assert r.status_code == 201
    e = r.json()
    assert e["items"][0]["line_total"] == 300.0
    assert e["subtotal"] == 300.0
