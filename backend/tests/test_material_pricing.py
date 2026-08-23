"""Material effective Cost + Default-Price-Book Price — HTTP integration tests.

Covers rule priority (Item>Supplier>Manufacturer>Category>Default), supplier-rule aligned to the
cost-source supplier, cost-basis fallbacks, markup vs margin, default-book-only, inventory+detail
expose Cost+Price, Sales cost gating (price still visible), and missing-cost -> null (never $0).
Self-owned data; safe to run repeatedly.
"""
import os
import uuid
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _tag():
    return uuid.uuid4().hex[:8]


def _mk_supplier(h, name):
    return requests.post(f"{API}/suppliers", headers=h, json={"name": name}, timeout=30).json()["id"]


def _mk_material(h, **kw):
    body = {"name": f"MP {_tag()}", "unit": "SQ", "quantity_on_hand": 0, "reorder_threshold": 0}
    body.update(kw)
    r = requests.post(f"{API}/materials", headers=h, json=body, timeout=30)
    assert r.status_code == 201, r.text[:200]
    return r.json()["id"]


def _mk_sm(h, material_id, supplier_id, cost):
    r = requests.post(f"{API}/supplier-materials", headers=h, json={
        "material_id": material_id, "supplier_id": supplier_id,
        "supplier_item_number": f"SI-{_tag()}", "current_cost": cost}, timeout=30)
    assert r.status_code == 201, r.text[:200]
    return r.json()["id"]


def _default_pb(h, entries):
    pb = requests.post(f"{API}/estimating/price-books", headers=h,
                       json={"name": f"MP Default {_tag()}", "is_default": True}, timeout=30).json()
    requests.put(f"{API}/estimating/price-books/{pb['id']}/entries", headers=h, json=entries, timeout=30)
    return pb["id"]


def _detail(h, mid):
    return requests.get(f"{API}/materials/{mid}/detail", headers=h, timeout=30).json()["material"]


def test_priority_and_supplier_alignment_and_calc():
    h = _login(*OWNER)
    abc = _mk_supplier(h, f"ABC {_tag()}")
    man = _mk_supplier(h, f"Manual {_tag()}")
    mid = _mk_material(h, manufacturer="GAF", category="Roofing")
    sm_abc = _mk_sm(h, mid, abc, 40)
    _mk_sm(h, mid, man, 38)  # cheaper, but NOT preferred
    requests.post(f"{API}/materials/{mid}/suppliers/{sm_abc}/prefer", headers=h, timeout=30)

    full = [
        {"target_type": "default", "rule_type": "markup", "markup_percent": 30},
        {"target_type": "category", "category": "Roofing", "rule_type": "markup", "markup_percent": 35},
        {"target_type": "manufacturer", "manufacturer": "GAF", "rule_type": "markup", "markup_percent": 40},
        {"target_type": "supplier", "supplier_id": abc, "rule_type": "markup", "markup_percent": 42},
        {"target_type": "material", "material_id": mid, "rule_type": "markup", "markup_percent": 45},
    ]
    pb = _default_pb(h, full)

    m = _detail(h, mid)
    # cost source = preferred ABC ($40) NOT cheaper manual ($38)
    assert m["effective_cost"] == 40.0 and m["effective_cost_source"] == "preferred_supplier"
    assert m["effective_cost_supplier_name"].startswith("ABC")
    assert m["matched_rule_type"] == "markup" and m["effective_price"] == 58.0  # item 45%

    # peel: supplier wins (42% -> 56.8)
    requests.put(f"{API}/estimating/price-books/{pb}/entries", headers=h, json=full[:4], timeout=30)
    assert _detail(h, mid)["effective_price"] == 56.8
    # manufacturer (40% -> 56.0)
    requests.put(f"{API}/estimating/price-books/{pb}/entries", headers=h, json=full[:3], timeout=30)
    assert _detail(h, mid)["effective_price"] == 56.0
    # category (35% -> 54.0)
    requests.put(f"{API}/estimating/price-books/{pb}/entries", headers=h, json=full[:2], timeout=30)
    assert _detail(h, mid)["effective_price"] == 54.0
    # default (30% -> 52.0)
    requests.put(f"{API}/estimating/price-books/{pb}/entries", headers=h, json=full[:1], timeout=30)
    assert _detail(h, mid)["effective_price"] == 52.0
    # margin mode (20% -> 40/0.8 = 50.0)
    requests.put(f"{API}/estimating/price-books/{pb}/entries", headers=h,
                 json=[{"target_type": "default", "rule_type": "margin", "margin_percent": 20}], timeout=30)
    assert _detail(h, mid)["effective_price"] == 50.0


def test_cost_basis_fallbacks_and_missing():
    h = _login(*OWNER)
    _default_pb(h, [{"target_type": "default", "rule_type": "markup", "markup_percent": 10}])
    # standard cost fallback
    mid = _mk_material(h, standard_cost=100)
    m = _detail(h, mid)
    assert m["effective_cost"] == 100.0 and m["effective_cost_source"] == "standard_cost" and m["effective_price"] == 110.0
    # no cost at all -> null cost & price (never $0)
    mid2 = _mk_material(h)
    m2 = _detail(h, mid2)
    assert m2["effective_cost"] is None and m2["effective_price"] is None


def test_best_known_when_no_preferred():
    h = _login(*OWNER)
    _default_pb(h, [{"target_type": "default", "rule_type": "markup", "markup_percent": 0}])
    s1 = _mk_supplier(h, f"S1 {_tag()}")
    s2 = _mk_supplier(h, f"S2 {_tag()}")
    mid = _mk_material(h)
    # First mapping auto-becomes preferred but has NO cost -> resolution must fall to best known.
    requests.post(f"{API}/supplier-materials", headers=h, json={
        "material_id": mid, "supplier_id": s1, "supplier_item_number": f"SI-{_tag()}"}, timeout=30)
    _mk_sm(h, mid, s2, 45)  # priced -> best known
    m = _detail(h, mid)
    assert m["effective_cost"] == 45.0 and m["effective_cost_source"] == "best_known_cost"


def test_only_default_book_used():
    h = _login(*OWNER)
    # A non-default active book with an aggressive material rule must be IGNORED.
    mid = _mk_material(h, standard_cost=100)
    other = requests.post(f"{API}/estimating/price-books", headers=h,
                          json={"name": f"NonDefault {_tag()}", "is_default": False}, timeout=30).json()
    requests.put(f"{API}/estimating/price-books/{other['id']}/entries", headers=h,
                 json=[{"target_type": "material", "material_id": mid, "rule_type": "markup", "markup_percent": 999}], timeout=30)
    _default_pb(h, [{"target_type": "default", "rule_type": "markup", "markup_percent": 10}])
    m = _detail(h, mid)
    assert m["effective_price"] == 110.0  # default book's 10%, not the 999% non-default


def test_inventory_list_exposes_cost_and_price():
    h = _login(*OWNER)
    _default_pb(h, [{"target_type": "default", "rule_type": "markup", "markup_percent": 25}])
    mid = _mk_material(h, standard_cost=80)
    rows = requests.get(f"{API}/materials", headers=h, timeout=30).json()
    row = next(r for r in rows if r["id"] == mid)
    assert row["effective_cost"] == 80.0 and row["effective_price"] == 100.0


def test_sales_cannot_see_cost_but_sees_price():
    h = _login(*OWNER)
    _default_pb(h, [{"target_type": "default", "rule_type": "markup", "markup_percent": 50}])
    mid = _mk_material(h, standard_cost=100)
    # create a sales user
    semail = f"salesmp_{_tag()}@example.com"
    requests.post(f"{API}/users", headers=h,
                  json={"email": semail, "password": "SalesMP#2026", "full_name": "Sales MP", "role": "sales"}, timeout=30)
    sh = _login(semail, "SalesMP#2026")
    # detail
    m = _detail(sh, mid)
    assert m["effective_cost"] is None and m["effective_cost_source"] is None
    assert m["best_known_cost"] is None and m["standard_cost"] is None
    assert m["effective_price"] == 150.0  # price still visible to sales
    # list
    rows = requests.get(f"{API}/materials", headers=sh, timeout=30).json()
    row = next(r for r in rows if r["id"] == mid)
    assert row["effective_cost"] is None and row["effective_price"] == 150.0


def test_labor_and_assembly_entries_still_persist():
    h = _login(*OWNER)
    pb = requests.post(f"{API}/estimating/price-books", headers=h,
                       json={"name": f"LA {_tag()}"}, timeout=30).json()
    out = requests.put(f"{API}/estimating/price-books/{pb['id']}/entries", headers=h, json=[
        {"target_type": "labor", "label": "Tear-off", "rule_type": "fixed", "fixed_price": 75},
        {"target_type": "supplier", "supplier_id": None, "rule_type": "markup", "markup_percent": 10},
    ], timeout=30).json()
    types = {e["target_type"] for e in out["entries"]}
    assert "labor" in types and "supplier" in types
