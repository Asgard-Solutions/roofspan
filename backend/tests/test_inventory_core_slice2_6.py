"""Inventory Core 2.0 — Slices 2-6 tests.

- compute_quantities math (async unit, real DB via SessionLocal): On Order = remaining on open POs,
  Required = active-job plans, Reserved from job_reservation ledger, Available/Projected formulas.
- HTTP invariants: reservation never reduces On Hand, invalid txn type rejected, structured types
  accepted, facets, detail structure, preferred-supplier switch, CSV preview + confirm-before-update.
"""
import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")


def _headers():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": OWNER[0], "password": OWNER[1]}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _first_abc_material(h):
    mats = requests.get(f"{BASE_URL}/api/materials", headers=h, timeout=30).json()
    return next(x for x in mats if x.get("abc_item_number"))


# ---------------- async unit: quantity math ----------------
def test_compute_quantities_math():
    async def run():
        from db import SessionLocal
        from models import Material, PurchaseOrder, POLineItem, Job, JobMaterial, InventoryTxn
        from services import inventory_core as inv
        async with SessionLocal() as db:
            tag = uuid.uuid4().hex[:8]
            m = Material(name=f"QtyTest {tag}", unit="each", quantity_on_hand=100, reorder_threshold=0)
            db.add(m); await db.flush()
            # open PO with a line: qty 40, received 10 -> on_order 30
            po = PurchaseOrder(number=f"QT-{tag}", status="ordered", total=0)
            db.add(po); await db.flush()
            db.add(POLineItem(po_id=po.id, material_id=m.id, description="x", quantity=40, received_quantity=10, unit_cost=5))
            # cancelled PO must NOT count toward on_order
            po2 = PurchaseOrder(number=f"QTX-{tag}", status="cancelled", total=0)
            db.add(po2); await db.flush()
            db.add(POLineItem(po_id=po2.id, material_id=m.id, description="x", quantity=99, received_quantity=0, unit_cost=5))
            # active job requiring 25; completed job requiring 999 (excluded)
            j = Job(number=f"JQ-{tag}", status="in_progress", total=0)
            jc = Job(number=f"JQC-{tag}", status="completed", total=0)
            db.add_all([j, jc]); await db.flush()
            db.add(JobMaterial(job_id=j.id, material_id=m.id, planned_quantity=25))
            db.add(JobMaterial(job_id=jc.id, material_id=m.id, planned_quantity=999))
            # reservation of 15 (stored negative), must not change on_hand
            db.add(InventoryTxn(material_id=m.id, delta=-15, reason="job_reservation"))
            await db.commit(); await db.refresh(m)
            q = await inv.compute_quantities(db, m)
            assert q["on_hand"] == 100
            assert q["on_order"] == 30, q          # remaining only, cancelled excluded
            assert q["required"] == 25, q          # active job only
            assert q["reserved"] == 15, q
            assert q["available"] == 85, q         # on_hand - reserved
            assert q["projected"] == 105, q        # on_hand + on_order - required
            # cleanup
            await db.delete(m); await db.delete(po); await db.delete(po2); await db.delete(j); await db.delete(jc)
            await db.commit()
    asyncio.run(run())


# ---------------- HTTP invariants ----------------
def test_reservation_does_not_reduce_on_hand():
    h = _headers()
    m = _first_abc_material(h)
    before = requests.get(f"{BASE_URL}/api/materials/{m['id']}/quantities", headers=h, timeout=30).json()["on_hand"]
    requests.post(f"{BASE_URL}/api/materials/{m['id']}/adjust", headers=h,
                  json={"delta": -2, "reason": "job_reservation", "note": "t"}, timeout=30)
    after = requests.get(f"{BASE_URL}/api/materials/{m['id']}/quantities", headers=h, timeout=30).json()
    assert after["on_hand"] == before  # physical on hand unchanged
    assert after["reserved"] >= 2


def test_invalid_txn_type_rejected():
    h = _headers()
    m = _first_abc_material(h)
    r = requests.post(f"{BASE_URL}/api/materials/{m['id']}/adjust", headers=h, json={"delta": 1, "reason": "not_a_type"}, timeout=30)
    assert r.status_code == 400


def test_structured_txn_type_accepted():
    h = _headers()
    m = _first_abc_material(h)
    r = requests.post(f"{BASE_URL}/api/materials/{m['id']}/adjust", headers=h,
                      json={"delta": 5, "reason": "receive_po", "note": "manual receive"}, timeout=30)
    assert r.status_code == 200


def test_materials_list_has_quantities_and_supplier():
    h = _headers()
    mats = requests.get(f"{BASE_URL}/api/materials", headers=h, timeout=30).json()
    m = mats[0]
    for k in ("on_hand", "reserved", "available", "on_order", "required", "projected", "best_known_cost", "status"):
        assert k in m


def test_facets():
    h = _headers()
    f = requests.get(f"{BASE_URL}/api/materials/facets", headers=h, timeout=30).json()
    assert "categories" in f and "manufacturers" in f and "suppliers" in f
    assert any(s["name"] == "ABC Supply" for s in f["suppliers"])


def test_detail_structure():
    h = _headers()
    m = _first_abc_material(h)
    d = requests.get(f"{BASE_URL}/api/materials/{m['id']}/detail", headers=h, timeout=30).json()
    for k in ("material", "quantities", "suppliers", "open_po_lines", "jobs", "transactions"):
        assert k in d
    assert len(d["suppliers"]) >= 1


def test_preferred_supplier_switch():
    h = _headers()
    m = _first_abc_material(h)
    sms = requests.get(f"{BASE_URL}/api/materials/{m['id']}/suppliers", headers=h, timeout=30).json()
    sm_id = sms[0]["id"]
    r = requests.post(f"{BASE_URL}/api/materials/{m['id']}/suppliers/{sm_id}/prefer", headers=h, timeout=30)
    assert r.status_code == 200
    result = r.json()
    preferred = [s for s in result if s["is_preferred"]]
    assert len(preferred) == 1 and preferred[0]["id"] == sm_id  # only one preferred


# ---------------- CSV import ----------------
def test_csv_preview_and_commit_requires_confirm_for_updates():
    h = _headers()
    tag = uuid.uuid4().hex[:6]
    existing = _first_abc_material(h)
    rows = [
        {"name": f"CSV New {tag}", "sku": f"CSVNEW-{tag}", "category": "Test", "unit": "each", "quantity_on_hand": 7},
        {"sku": existing["sku"], "reorder_threshold": 3},  # update-by-SKU
    ]
    prev = requests.post(f"{BASE_URL}/api/materials/import/preview", headers=h, json={"rows": rows}, timeout=30).json()
    actions = {r["action"] for r in prev["rows"]}
    assert "create" in actions
    if existing.get("sku"):
        assert prev["update_count"] >= 1
        # commit without confirm -> blocked
        blocked = requests.post(f"{BASE_URL}/api/materials/import/commit", headers=h, json={"rows": rows, "confirm_updates": False}, timeout=30)
        assert blocked.status_code == 409
    # commit with confirm
    ok = requests.post(f"{BASE_URL}/api/materials/import/commit", headers=h, json={"rows": rows, "confirm_updates": True}, timeout=30)
    assert ok.status_code == 200, ok.text[:200]
    assert ok.json()["created"] >= 1
