"""Inventory Core 2.0 hardening tests: standards-compliant CSV parsing + DB preferred-supplier invariant."""
import asyncio
import os
import uuid

import pytest
import requests
from sqlalchemy.exc import IntegrityError

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")


def _headers():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": OWNER[0], "password": OWNER[1]}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------- CSV parser ----------------
def test_csv_quoted_commas_and_escaped_quotes():
    h = _headers()
    tag = uuid.uuid4().hex[:6]
    # quoted field with comma + escaped "" quotes + comma inside description + CRLF line endings
    csv_text = (
        "sku,name,description,manufacturer\r\n"
        f'ABC-{tag},"Roofing Nail, 1-1/4""","Coil nail, galvanized, 7,200 count","Example Manufacturer"\r\n'
    )
    r = requests.post(f"{BASE_URL}/api/materials/import/preview", headers=h, json={"csv_text": csv_text}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    assert data["header_errors"] == []
    assert len(data["rows"]) == 1
    row = data["rows"][0]
    assert row["action"] == "create"
    assert row["name"] == 'Roofing Nail, 1-1/4"'  # comma + unescaped quote preserved
    assert row["sku"] == f"ABC-{tag}"


def test_csv_lf_only_and_blank_optional_fields():
    h = _headers()
    tag = uuid.uuid4().hex[:6]
    csv_text = "name,sku,category,manufacturer\n" f"Plain Item {tag},PLN-{tag},,\n"  # LF only, blank category/mfr
    r = requests.post(f"{BASE_URL}/api/materials/import/preview", headers=h, json={"csv_text": csv_text}, timeout=30)
    data = r.json()
    assert len(data["rows"]) == 1 and data["rows"][0]["action"] == "create"


def test_csv_header_validation():
    h = _headers()
    r = requests.post(f"{BASE_URL}/api/materials/import/preview", headers=h,
                      json={"csv_text": "foo,bar\n1,2\n"}, timeout=30)
    data = r.json()
    assert data["header_errors"], "expected header error when neither sku nor name present"
    c = requests.post(f"{BASE_URL}/api/materials/import/commit", headers=h,
                      json={"csv_text": "foo,bar\n1,2\n", "confirm_updates": True}, timeout=30)
    assert c.status_code == 400


def test_csv_commit_via_text_creates():
    h = _headers()
    tag = uuid.uuid4().hex[:6]
    csv_text = "name,sku,quantity_on_hand\n" f'"Widget, Deluxe {tag}",WID-{tag},5\n'
    r = requests.post(f"{BASE_URL}/api/materials/import/commit", headers=h,
                      json={"csv_text": csv_text, "confirm_updates": True}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    assert r.json()["created"] == 1


# ---------------- DB preferred-supplier invariant ----------------
def test_db_rejects_two_active_preferred():
    async def run():
        from db import SessionLocal
        from models import Material, SupplierMaterial
        from services import inventory_core as inv
        async with SessionLocal() as db:
            tag = uuid.uuid4().hex[:8]
            m = Material(name=f"PrefTest {tag}", unit="each", quantity_on_hand=0)
            db.add(m); await db.flush()
            a = SupplierMaterial(material_id=m.id, integration_provider="manual", is_preferred=True, active=True)
            b = SupplierMaterial(material_id=m.id, integration_provider="manual", is_preferred=False, active=True)
            db.add_all([a, b]); await db.commit()
            # Service switch keeps exactly one preferred
            await inv.set_preferred_supplier(db, m.id, b.id)
            await db.commit()
            rows = (await db.execute(
                __import__("sqlalchemy").select(SupplierMaterial).where(SupplierMaterial.material_id == m.id)
            )).scalars().all() if False else None
            # reload
            from sqlalchemy import select
            rows = (await db.execute(select(SupplierMaterial).where(SupplierMaterial.material_id == m.id))).scalars().all()
            preferred = [r for r in rows if r.is_preferred and r.active]
            assert len(preferred) == 1 and str(preferred[0].id) == str(b.id)

            # Directly forcing a 2nd active preferred must be rejected by the DB partial unique index.
            a2 = await db.get(SupplierMaterial, a.id)
            raised = False
            try:
                async with db.begin_nested():
                    a2.is_preferred = True
                    await db.flush()
            except IntegrityError:
                raised = True
            assert raised, "DB partial unique index did not reject a second active preferred mapping"

            # cleanup (FK cascade removes supplier_materials)
            m2 = await db.get(Material, m.id)
            if m2:
                await db.delete(m2)
                await db.commit()
    asyncio.run(run())


def test_prefer_endpoint_keeps_single_preferred():
    h = _headers()
    mats = requests.get(f"{BASE_URL}/api/materials", headers=h, timeout=30).json()
    m = next((x for x in mats if x.get("abc_item_number")), None)
    assert m
    sms = requests.get(f"{BASE_URL}/api/materials/{m['id']}/suppliers", headers=h, timeout=30).json()
    r = requests.post(f"{BASE_URL}/api/materials/{m['id']}/suppliers/{sms[0]['id']}/prefer", headers=h, timeout=30)
    assert r.status_code == 200
    preferred = [s for s in r.json() if s["is_preferred"]]
    assert len(preferred) == 1
