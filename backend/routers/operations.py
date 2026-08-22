import re

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Material, InventoryTxn, Supplier, SupplierMaterial, JobMaterial, PurchaseOrder, POLineItem, Job, User
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_phase4 import (
    MaterialIn, MaterialPatch, MaterialOut, MaterialListItemOut, MaterialFacetsOut, QuantitiesOut,
    MaterialDetailOut, TxnOut, OpenPOLineOut, JobRequirementOut, AdjustIn, SupplierIn, SupplierOut,
    CsvPreviewIn, CsvPreviewOut, CsvPreviewRowOut, CsvCommitIn,
)
from integrations.abc_supply.schemas import SupplierMaterialOut
from services import inventory_core as inv_core

router = APIRouter(prefix="/api", tags=["operations"])


def _norm_name(name: str) -> str:
    """Trim and collapse internal whitespace so case/spacing dupes don't create competing inventory."""
    return re.sub(r"\s+", " ", (name or "").strip())


async def _assert_unique_material_name(db: AsyncSession, name: str, exclude_id=None) -> str:
    norm = _norm_name(name)
    if not norm:
        raise HTTPException(status_code=422, detail="Material name is required")
    stmt = select(Material).where(func.lower(Material.name) == norm.lower())
    if exclude_id is not None:
        stmt = stmt.where(Material.id != exclude_id)
    if (await db.execute(stmt)).scalars().first():
        raise HTTPException(status_code=409, detail=f"A material named '{norm}' already exists")
    return norm


def _mat_out(m: Material) -> MaterialOut:
    return MaterialOut(
        id=str(m.id), name=m.name, sku=m.sku, category=m.category, unit=m.unit, description=m.description,
        active=m.active, quantity_on_hand=m.quantity_on_hand, reorder_threshold=m.reorder_threshold,
        low_stock=(m.quantity_on_hand <= m.reorder_threshold),
        vendor=m.vendor, abc_item_number=m.abc_item_number,
    )


async def _mat_list_item(db: AsyncSession, m: Material) -> MaterialListItemOut:
    qty = await inv_core.compute_quantities(db, m)
    pref = await inv_core.preferred_supplier_material(db, m.id)
    pref_name = None
    if pref and pref.supplier_id:
        s = await db.get(Supplier, pref.supplier_id)
        pref_name = s.name if s else None
    best = await inv_core.best_known_cost(db, m.id)
    return MaterialListItemOut(
        id=str(m.id), name=m.name, sku=m.sku, category=m.category, unit=m.unit, description=m.description,
        active=m.active, quantity_on_hand=m.quantity_on_hand, reorder_threshold=m.reorder_threshold,
        low_stock=(qty["available"] <= m.reorder_threshold),
        vendor=m.vendor, abc_item_number=m.abc_item_number,
        manufacturer=m.manufacturer, brand=m.brand, status=("active" if m.active else "inactive"),
        on_hand=qty["on_hand"], reserved=qty["reserved"], available=qty["available"],
        on_order=qty["on_order"], required=qty["required"], projected=qty["projected"],
        primary_supplier_name=pref_name, primary_supplier_cost=(pref.current_cost if pref else None),
        best_known_cost=best,
    )


@router.get("/materials", response_model=list[MaterialListItemOut])
async def list_materials(low_stock: bool | None = Query(None), q: str | None = Query(None),
                         category: str | None = Query(None), manufacturer: str | None = Query(None),
                         supplier_id: str | None = Query(None), active: bool | None = Query(None),
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Material).order_by(Material.name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((Material.name.ilike(like)) | (Material.sku.ilike(like)) | (Material.manufacturer.ilike(like)))
    if category:
        stmt = stmt.where(Material.category == category)
    if manufacturer:
        stmt = stmt.where(Material.manufacturer == manufacturer)
    if active is not None:
        stmt = stmt.where(Material.active.is_(active))
    if supplier_id:
        stmt = stmt.where(Material.id.in_(select(SupplierMaterial.material_id).where(SupplierMaterial.supplier_id == supplier_id)))
    rows = (await db.execute(stmt)).scalars().all()
    out = [await _mat_list_item(db, m) for m in rows]
    if low_stock:
        out = [m for m in out if m.low_stock]
    return out


@router.get("/materials/facets", response_model=MaterialFacetsOut)
async def material_facets(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cats = [c for c in (await db.execute(select(Material.category).distinct().where(Material.category.isnot(None)))).scalars().all() if c]
    mfrs = [c for c in (await db.execute(select(Material.manufacturer).distinct().where(Material.manufacturer.isnot(None)))).scalars().all() if c]
    sups = (await db.execute(select(Supplier).order_by(Supplier.name))).scalars().all()
    return MaterialFacetsOut(categories=sorted(cats), manufacturers=sorted(mfrs),
                             suppliers=[{"id": str(s.id), "name": s.name} for s in sups])


@router.post("/materials", response_model=MaterialOut, status_code=201)
async def create_material(payload: MaterialIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    data = payload.model_dump()
    data["name"] = await _assert_unique_material_name(db, data["name"])
    m = Material(**data, created_by=user.email)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    await log_action(db, user=user, action="material.create", entity_type="material", entity_id=m.id, request=request)
    return _mat_out(m)


@router.patch("/materials/{material_id}", response_model=MaterialOut)
async def update_material(material_id: str, payload: MaterialPatch, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    m = await db.get(Material, material_id)
    if not m:
        raise HTTPException(status_code=404, detail="Material not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        data["name"] = await _assert_unique_material_name(db, data["name"], exclude_id=m.id)
    for k, v in data.items():
        setattr(m, k, v)
    await db.commit()
    await db.refresh(m)
    await log_action(db, user=user, action="material.update", entity_type="material", entity_id=m.id, request=request)
    return _mat_out(m)


@router.get("/materials/{material_id}/quantities", response_model=QuantitiesOut)
async def material_quantities(material_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    m = await db.get(Material, material_id)
    if not m:
        raise HTTPException(status_code=404, detail="Material not found")
    return QuantitiesOut(**await inv_core.compute_quantities(db, m))


@router.get("/materials/{material_id}/detail", response_model=MaterialDetailOut)
async def material_detail(material_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    m = await db.get(Material, material_id)
    if not m:
        raise HTTPException(status_code=404, detail="Material not found")
    qty = await inv_core.compute_quantities(db, m)
    # suppliers
    sm_rows = (await db.execute(
        select(SupplierMaterial, Supplier.name).outerjoin(Supplier, Supplier.id == SupplierMaterial.supplier_id)
        .where(SupplierMaterial.material_id == m.id).order_by(SupplierMaterial.is_preferred.desc())
    )).all()
    suppliers = [SupplierMaterialOut(
        id=str(sm.id), material_id=str(sm.material_id), supplier_id=(str(sm.supplier_id) if sm.supplier_id else None),
        supplier_name=sname, integration_provider=sm.integration_provider, external_item_id=sm.external_item_id,
        supplier_item_number=sm.supplier_item_number, supplier_description=sm.supplier_description,
        supplier_uom=sm.supplier_uom, current_cost=sm.current_cost, price_status=sm.price_status,
        price_updated_at=sm.price_updated_at, availability_status=sm.availability_status,
        lead_time_days=sm.lead_time_days, is_preferred=sm.is_preferred, active=sm.active,
    ).model_dump() for sm, sname in sm_rows]
    # open PO lines
    po_rows = (await db.execute(
        select(POLineItem, PurchaseOrder.number, PurchaseOrder.status)
        .join(PurchaseOrder, PurchaseOrder.id == POLineItem.po_id)
        .where(POLineItem.material_id == m.id, PurchaseOrder.status.in_(inv_core._OPEN_PO_STATUSES))
    )).all()
    open_po = [OpenPOLineOut(po_id=str(li.po_id), po_number=num, status=st, quantity=li.quantity,
                             received_quantity=li.received_quantity, remaining=max(li.quantity - li.received_quantity, 0),
                             unit_cost=li.unit_cost) for li, num, st in po_rows]
    # jobs requiring
    job_rows = (await db.execute(
        select(JobMaterial, Job.number).join(Job, Job.id == JobMaterial.job_id)
        .where(JobMaterial.material_id == m.id, Job.status.notin_(inv_core._ACTIVE_JOB_STATUSES_EXCLUDED))
    )).all()
    jobs = [JobRequirementOut(job_id=str(jm.job_id), job_title=num, planned_quantity=jm.planned_quantity) for jm, num in job_rows]
    # transaction history
    txn_rows = (await db.execute(
        select(InventoryTxn).where(InventoryTxn.material_id == m.id).order_by(InventoryTxn.created_at.desc()).limit(200)
    )).scalars().all()
    txns = [TxnOut(id=str(t.id), txn_type=t.reason, delta=t.delta, note=t.note,
                   po_id=(str(t.po_id) if t.po_id else None), job_id=(str(t.job_id) if t.job_id else None),
                   location=t.location, created_by=t.created_by, created_at=t.created_at) for t in txn_rows]
    return MaterialDetailOut(material=await _mat_list_item(db, m), quantities=QuantitiesOut(**qty),
                             suppliers=suppliers, open_po_lines=open_po, jobs=jobs, transactions=txns)


@router.post("/materials/{material_id}/adjust", response_model=MaterialOut)
async def adjust_material(material_id: str, payload: AdjustIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    if payload.reason not in inv_core.TXN_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid transaction type '{payload.reason}'.")
    m = (await db.execute(select(Material).where(Material.id == material_id).with_for_update())).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Material not found")
    # Reservations do NOT reduce physical On Hand; they are tracked as ledger entries only.
    affects_on_hand = payload.reason != "job_reservation"
    if affects_on_hand:
        new_qty = round(m.quantity_on_hand + payload.delta, 3)
        if new_qty < 0:
            raise HTTPException(status_code=400, detail=f"Adjustment would make quantity negative (on hand {m.quantity_on_hand})")
        m.quantity_on_hand = new_qty
    db.add(InventoryTxn(material_id=m.id, delta=payload.delta, reason=payload.reason, note=payload.note,
                        job_id=(payload.job_id or None), location=payload.location, created_by=user.email))
    await db.commit()
    await db.refresh(m)
    await log_action(db, user=user, action="inventory.adjust", entity_type="material", entity_id=m.id, detail={"delta": payload.delta, "reason": payload.reason, "on_hand": m.quantity_on_hand}, request=request)
    return _mat_out(m)


@router.post("/materials/{material_id}/suppliers/{sm_id}/prefer", response_model=list[SupplierMaterialOut])
async def set_preferred(material_id: str, sm_id: str, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    sm = await db.get(SupplierMaterial, sm_id)
    if not sm or str(sm.material_id) != material_id:
        raise HTTPException(status_code=404, detail="Supplier mapping not found for this material")
    chosen = await inv_core.set_preferred_supplier(db, material_id, sm_id)
    if not chosen:
        raise HTTPException(status_code=404, detail="Supplier mapping not found")
    await db.commit()
    await log_action(db, user=user, action="material.set_preferred_supplier", entity_type="material", entity_id=material_id, detail={"supplier_material_id": sm_id}, request=request)
    return await material_suppliers(material_id, user, db)


# ---- CSV import (create + update-by-SKU with explicit preview/confirm) ----
import csv as _csv
import io as _io

_CSV_FIELDS = ("name", "category", "unit", "manufacturer", "description", "reorder_threshold", "quantity_on_hand")
_CSV_KNOWN_HEADERS = ("sku",) + _CSV_FIELDS


def _parse_csv_text(text: str) -> tuple[list[dict], list[str]]:
    """Standards-compliant CSV parse (quoted fields, commas inside quotes, escaped "" quotes, CRLF/LF,
    UTF-8). Returns (rows, header_errors)."""
    if text is None:
        return [], ["No CSV content provided."]
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")  # strip UTF-8 BOM
    reader = _csv.DictReader(_io.StringIO(text))
    headers = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    errors: list[str] = []
    if not headers:
        return [], ["CSV has no header row."]
    if "sku" not in headers and "name" not in headers:
        errors.append("CSV header must include at least 'sku' or 'name'.")
    rows: list[dict] = []
    for raw in reader:
        row = {}
        for k, v in raw.items():
            if k is None:
                continue
            row[(k or "").strip().lower()] = (v.strip() if isinstance(v, str) else v)
        if any((v not in (None, "")) for v in row.values()):
            rows.append(row)
    return rows, errors


def _coerce_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def _csv_diff(db: AsyncSession, rows: list[dict], header_errors: list[str] | None = None) -> CsvPreviewOut:
    out_rows: list[CsvPreviewRowOut] = []
    creates = updates = errors = 0
    for i, raw in enumerate(rows, start=1):
        sku = (str(raw.get("sku")).strip() if raw.get("sku") not in (None, "") else None)
        name = (str(raw.get("name")).strip() if raw.get("name") not in (None, "") else None)
        row_errors: list[str] = []
        existing = None
        if sku:
            existing = (await db.execute(select(Material).where(func.lower(Material.sku) == sku.lower()))).scalars().first()
        if not existing and not name:
            row_errors.append("Row needs a name (for create) or a SKU matching an existing material (for update).")
        if existing:
            changes = {}
            for f in _CSV_FIELDS:
                if f in raw and raw.get(f) not in (None, ""):
                    newv = _coerce_num(raw[f]) if f in ("reorder_threshold", "quantity_on_hand") else str(raw[f]).strip()
                    oldv = getattr(existing, f, None)
                    if newv is not None and newv != oldv:
                        changes[f] = {"from": oldv, "to": newv}
            updates += 1
            out_rows.append(CsvPreviewRowOut(row_number=i, action="update", sku=sku, name=name or existing.name,
                                             material_id=str(existing.id), changes=changes, errors=row_errors))
        elif row_errors:
            errors += 1
            out_rows.append(CsvPreviewRowOut(row_number=i, action="error", sku=sku, name=name, errors=row_errors))
        else:
            creates += 1
            out_rows.append(CsvPreviewRowOut(row_number=i, action="create", sku=sku, name=name, changes={}))
    return CsvPreviewOut(rows=out_rows, create_count=creates, update_count=updates, error_count=errors,
                         header_errors=(header_errors or []))


def _rows_from_payload(payload) -> tuple[list[dict], list[str]]:
    if getattr(payload, "csv_text", None):
        return _parse_csv_text(payload.csv_text)
    return payload.rows, []


@router.post("/materials/import/preview", response_model=CsvPreviewOut)
async def csv_preview(payload: CsvPreviewIn, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    rows, header_errors = _rows_from_payload(payload)
    return await _csv_diff(db, rows, header_errors)


@router.post("/materials/import/commit")
async def csv_commit(payload: CsvCommitIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    rows, header_errors = _rows_from_payload(payload)
    if header_errors:
        raise HTTPException(status_code=400, detail="; ".join(header_errors))
    preview = await _csv_diff(db, rows)
    if preview.update_count > 0 and not payload.confirm_updates:
        raise HTTPException(status_code=409, detail="This import updates existing materials. Re-submit with confirm_updates=true to apply.")
    created = updated = skipped = 0
    for pr, raw in zip(preview.rows, rows):
        if pr.action == "error":
            skipped += 1
            continue
        if pr.action == "update":
            m = await db.get(Material, pr.material_id)
            if not m:
                continue
            for f, ch in pr.changes.items():
                setattr(m, f, ch["to"])
            updated += 1
        else:  # create
            name = await _assert_unique_material_name(db, (raw.get("name") or "").strip())
            m = Material(name=name, sku=(str(raw.get("sku")).strip() if raw.get("sku") else None),
                         category=(str(raw.get("category")).strip() if raw.get("category") else None),
                         unit=(str(raw.get("unit")).strip() if raw.get("unit") else "each"),
                         manufacturer=(str(raw.get("manufacturer")).strip() if raw.get("manufacturer") else None),
                         description=(str(raw.get("description")).strip() if raw.get("description") else None),
                         reorder_threshold=(_coerce_num(raw.get("reorder_threshold")) or 0),
                         quantity_on_hand=(_coerce_num(raw.get("quantity_on_hand")) or 0),
                         created_by=user.email)
            db.add(m)
            created += 1
    await db.commit()
    await log_action(db, user=user, action="material.csv_import", entity_type="material", entity_id=None,
                     detail={"created": created, "updated": updated, "skipped": skipped}, request=request)
    return {"created": created, "updated": updated, "skipped": skipped}







@router.get("/materials/{material_id}/suppliers", response_model=list[SupplierMaterialOut])
async def material_suppliers(material_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(SupplierMaterial, Supplier.name)
        .outerjoin(Supplier, Supplier.id == SupplierMaterial.supplier_id)
        .where(SupplierMaterial.material_id == material_id)
        .order_by(SupplierMaterial.is_preferred.desc())
    )).all()
    return [
        SupplierMaterialOut(
            id=str(sm.id), material_id=str(sm.material_id), supplier_id=(str(sm.supplier_id) if sm.supplier_id else None),
            supplier_name=sname, integration_provider=sm.integration_provider, external_item_id=sm.external_item_id,
            supplier_item_number=sm.supplier_item_number, supplier_description=sm.supplier_description,
            supplier_uom=sm.supplier_uom, current_cost=sm.current_cost, price_status=sm.price_status,
            price_updated_at=sm.price_updated_at, availability_status=sm.availability_status,
            lead_time_days=sm.lead_time_days, is_preferred=sm.is_preferred, active=sm.active,
        ) for sm, sname in rows
    ]




# ---- Suppliers (minimal) ----
def _sup_out(s: Supplier) -> SupplierOut:
    return SupplierOut(id=str(s.id), name=s.name, contact_name=s.contact_name, phone=s.phone, email=s.email, notes=s.notes, active=s.active)


@router.get("/suppliers", response_model=list[SupplierOut])
async def list_suppliers(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Supplier).order_by(Supplier.name))).scalars().all()
    return [_sup_out(s) for s in rows]


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
async def create_supplier(payload: SupplierIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(Supplier).where(Supplier.name == payload.name))).scalar_one_or_none()
    if existing:
        return _sup_out(existing)
    s = Supplier(**payload.model_dump())
    db.add(s)
    await db.commit()
    await db.refresh(s)
    await log_action(db, user=user, action="supplier.create", entity_type="supplier", entity_id=s.id, request=request)
    return _sup_out(s)
