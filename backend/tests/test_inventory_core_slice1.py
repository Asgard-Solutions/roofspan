"""Inventory Core 2.0 — Slice 1 tests: master fields + generic SupplierMaterial mapping + ABC backfill."""
import os
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")


def _headers():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": OWNER[0], "password": OWNER[1]}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_abc_supplier_exists():
    h = _headers()
    sups = requests.get(f"{BASE_URL}/api/suppliers", headers=h, timeout=30).json()
    names = [s["name"] for s in sups]
    assert "ABC Supply" in names, names


def test_existing_abc_materials_backfilled_into_supplier_materials():
    h = _headers()
    mats = requests.get(f"{BASE_URL}/api/materials", headers=h, timeout=30).json()
    abc_mats = [m for m in mats if m.get("abc_item_number")]
    assert abc_mats, "expected at least one ABC-linked material from prior slices"
    for m in abc_mats:
        sms = requests.get(f"{BASE_URL}/api/materials/{m['id']}/suppliers", headers=h, timeout=30).json()
        abc_sm = [s for s in sms if s["integration_provider"] == "abc_supply"]
        assert abc_sm, f"material {m['name']} not backfilled into supplier_materials"
        assert abc_sm[0]["supplier_item_number"] == m["abc_item_number"]
        # the (only) mapping should be preferred
        assert any(s["is_preferred"] for s in sms), f"no preferred supplier on {m['name']}"


def test_material_out_still_exposes_legacy_abc_fields():
    h = _headers()
    mats = requests.get(f"{BASE_URL}/api/materials", headers=h, timeout=30).json()
    m = next((x for x in mats if x.get("abc_item_number")), None)
    assert m is not None
    # legacy backward-compat fields still present (ABC ordering path depends on nothing being removed)
    assert "vendor" in m and "abc_item_number" in m


def test_add_existing_abc_item_ensures_preferred_supplier_material():
    h = _headers()
    # MOCK-SHINGLE-ARCH-WW was added in earlier slices and is cached; re-adding hits the dedupe path,
    # which must still guarantee a preferred ABC supplier mapping exists (no live ABC call needed).
    num = "MOCK-SHINGLE-ARCH-WW"
    r = requests.post(f"{BASE_URL}/api/integrations/abc/catalog/{num}/add-to-inventory", headers=h, json={}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    mid = r.json()["material_id"]
    sms = requests.get(f"{BASE_URL}/api/materials/{mid}/suppliers", headers=h, timeout=30).json()
    abc_sm = [s for s in sms if s["integration_provider"] == "abc_supply" and s["supplier_item_number"] == num]
    assert abc_sm, sms
    assert abc_sm[0]["is_preferred"] is True
    assert abc_sm[0]["supplier_name"] == "ABC Supply"
