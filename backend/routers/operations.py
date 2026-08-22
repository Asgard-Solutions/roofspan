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
    SupplierPatch, ManualSupplierMaterialIn, ManualSupplierMaterialPatch, PriceHistoryOut,
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
    from integrations.supplier_connectors import capabilities_for  # noqa: F401
    qty = await inv_core.compute_quantities(db, m)
    pref = await inv_core.preferred_supplier_material(db, m.id)
    pref_name = pref_provider = pref_status = pref_updated = None
    if pref:
        if pref.supplier_id:
            s = await db.get(Supplier, pref.supplier_id)
            pref_name = s.name if s else None
            pref_provider = (s.integration_provider if s else None) or pref.integration_provider
        else:
            pref_provider = pref.integration_provider
        pref_status = pref.price_status or ("manual" if not pref_provider or pref_provider == "manual" else None)
        pref_updated = pref.price_updated_at
    best_sm = await inv_core.best_known_supplier_material(db, m.id)
    best = best_sm.current_cost if best_sm else None
    best_name = best_provider = best_status = best_updated = None
    if best_sm:
        if best_sm.supplier_id:
            bs = await db.get(Supplier, best_sm.supplier_id)
            best_name = bs.name if bs else None
            best_provider = (bs.integration_provider if bs else None) or best_sm.integration_provider
        else:
            best_provider = best_sm.integration_provider
        best_status = best_sm.price_status or ("manual" if not best_provider or best_provider == "manual" else None)
        best_updated = best_sm.price_updated_at
    count = await inv_core.supplier_material_count(db, m.id)
    return MaterialListItemOut(
        id=str(m.id), name=m.name, sku=m.sku, category=m.category, unit=m.unit, description=m.description,
        active=m.active, quantity_on_hand=m.quantity_on_hand, reorder_threshold=m.reorder_threshold,
        low_stock=(qty["available"] <= m.reorder_threshold),
        vendor=m.vendor, abc_item_number=m.abc_item_number,
        manufacturer=m.manufacturer, brand=m.brand, status=("active" if m.active else "inactive"),
        on_hand=qty["on_hand"], reserved=qty["reserved"], available=qty["available"],
        on_order=qty["on_order"], required=qty["required"], projected=qty["projected"],
        primary_supplier_name=pref_name, primary_supplier_cost=(pref.current_cost if pref else None),
        primary_supplier_provider=pref_provider, primary_supplier_status=pref_status,
        primary_supplier_updated_at=pref_updated,
        best_known_cost=best, best_supplier_name=best_name, best_supplier_provider=best_provider,
        best_supplier_status=best_status, best_supplier_updated_at=best_updated,
        supplier_count=count,
    )



@router.get("/inventory/reorder-suggestions")
async def reorder_suggestions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Materials whose projected quantity falls below the reorder threshold, after accounting for
    inbound On Order. Recommends a replenishment quantity; never auto-orders."""
    mats = (await db.execute(select(Material).where(Material.active.is_(True)))).scalars().all()
    out = []
    for m in mats:
        q = await inv_core.compute_quantities(db, m)
        threshold = float(m.reorder_threshold or 0)
        # Do not suggest if inbound already covers projected need
        if q["projected"] >= threshold or threshold <= 0:
            continue
        pref = await inv_core.preferred_supplier_material(db, m.id)
        pref_name = None
        pref_supplier_id = None
        if pref and pref.supplier_id:
            s = await db.get(Supplier, pref.supplier_id)
            pref_name = s.name if s else None
            pref_supplier_id = str(pref.supplier_id)
        recommend = round(max(threshold - q["projected"], 0), 3)
        out.append({"material_id": str(m.id), "material_name": m.name, "unit": m.unit,
                    "on_hand": q["on_hand"], "reserved": q["reserved"], "available": q["available"],
                    "on_order": q["on_order"], "required": q["required"], "projected": q["projected"],
                    "reorder_threshold": threshold, "recommended_quantity": recommend,
                    "preferred_supplier": pref_name, "preferred_supplier_id": pref_supplier_id,
                    "preferred_supplier_material_id": str(pref.id) if pref else None,
                    "best_known_cost": await inv_core.best_known_cost(db, m.id)})
    return {"suggestions": out}


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
    from integrations.supplier_connectors import capabilities_for
    return MaterialFacetsOut(categories=sorted(cats), manufacturers=sorted(mfrs),
                             suppliers=[{"id": str(s.id), "name": s.name, "integration_provider": s.integration_provider,
                                         "capabilities": capabilities_for(s.integration_provider)} for s in sups])


@router.post("/materials", response_model=MaterialOut, status_code=201)
async def create_material(payload: MaterialIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    data = payload.model_dump()
    data["name"] = await _assert_unique_material_name(db, data["name"])
    m = Material(**data, created_by=user.email)
    db.add(m)
    await db.flush()
    from services import inventory_ops as _iops
    await _iops.sync_default_balance(db, m)
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
    if affects_on_hand:
        from services import inventory_ops as _iops
        await _iops.sync_default_balance(db, m)
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
    await db.flush()
    from services import inventory_ops as _iops
    from models import Material as _M
    fresh = (await db.execute(select(_M).where(_M.quantity_on_hand > 0))).scalars().all()
    for _m in fresh:
        await _iops.sync_default_balance(db, _m)
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
def _sup_out(s: Supplier):
    from integrations.supplier_connectors import capabilities_for
    status = s.integration_status or ("manual" if not s.integration_provider else None)
    return SupplierOut(
        id=str(s.id), name=s.name, contact_name=s.contact_name, phone=s.phone, email=s.email, notes=s.notes,
        active=s.active, supplier_type=s.supplier_type, account_number=s.account_number, sales_rep=s.sales_rep,
        ordering_email=s.ordering_email, website=s.website, payment_terms=s.payment_terms,
        default_branch=s.default_branch, delivery_terms=s.delivery_terms, minimum_order=s.minimum_order,
        freight_notes=s.freight_notes, tax_notes=s.tax_notes,
        integration_provider=s.integration_provider, integration_status=status,
        capabilities=capabilities_for(s.integration_provider),
    )


@router.get("/suppliers", response_model=list[SupplierOut])
async def list_suppliers(q: str | None = Query(None), active: bool | None = Query(None),
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Supplier).order_by(Supplier.name)
    if q:
        stmt = stmt.where(Supplier.name.ilike(f"%{q}%"))
    if active is not None:
        stmt = stmt.where(Supplier.active.is_(active))
    rows = (await db.execute(stmt)).scalars().all()
    return [_sup_out(s) for s in rows]


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
async def create_supplier(payload: SupplierIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(Supplier).where(Supplier.name == payload.name))).scalar_one_or_none()
    if existing:
        return _sup_out(existing)
    s = Supplier(**payload.model_dump(), integration_status="manual")  # manual supplier
    db.add(s)
    await db.commit(); await db.refresh(s)
    await log_action(db, user=user, action="supplier.create", entity_type="supplier", entity_id=s.id, request=request)
    return _sup_out(s)


@router.get("/suppliers/{supplier_id}")
async def supplier_detail(supplier_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = await db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(status_code=404, detail="Supplier not found")
    # products (supplier material mappings)
    sm_rows = (await db.execute(
        select(SupplierMaterial, Material.name).outerjoin(Material, Material.id == SupplierMaterial.material_id)
        .where(SupplierMaterial.supplier_id == s.id)
    )).all()
    products = [{"id": str(sm.id), "material_id": str(sm.material_id), "material_name": mname,
                 "supplier_item_number": sm.supplier_item_number, "supplier_uom": sm.supplier_uom,
                 "current_cost": sm.current_cost, "price_status": sm.price_status,
                 "price_updated_at": (sm.price_updated_at.isoformat() if sm.price_updated_at else None),
                 "is_preferred": sm.is_preferred, "active": sm.active} for sm, mname in sm_rows]
    # recent purchase orders for this supplier
    po_rows = (await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.supplier_id == s.id)
        .order_by(PurchaseOrder.created_at.desc()).limit(20)
    )).scalars().all()
    recent_pos = [{"id": str(p.id), "number": p.number, "status": p.status, "total": p.total,
                   "job_id": (str(p.job_id) if p.job_id else None),
                   "expected_date": (p.expected_date.isoformat() if p.expected_date else None),
                   "created_at": (p.created_at.isoformat() if p.created_at else None)} for p in po_rows]
    return {"supplier": _sup_out(s).model_dump(), "products": products, "purchase_orders": recent_pos}


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
async def update_supplier(supplier_id: str, payload: SupplierPatch, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    s = await db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(status_code=404, detail="Supplier not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    await db.commit(); await db.refresh(s)
    await log_action(db, user=user, action="supplier.update", entity_type="supplier", entity_id=s.id, request=request)
    return _sup_out(s)


@router.post("/suppliers/{supplier_id}/active", response_model=SupplierOut)
async def set_supplier_active(supplier_id: str, request: Request, active: bool = Query(...), user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    s = await db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(status_code=404, detail="Supplier not found")
    s.active = active
    await db.commit(); await db.refresh(s)
    await log_action(db, user=user, action=("supplier.reactivate" if active else "supplier.deactivate"), entity_type="supplier", entity_id=s.id, request=request)
    return _sup_out(s)


# ---- Manual SupplierMaterial mappings + price history (Slice 6) ----
async def _snapshot_price(db, sm: SupplierMaterial, source: str, user_email: str | None):
    from models import SupplierPriceHistory
    db.add(SupplierPriceHistory(supplier_material_id=sm.id, supplier_id=sm.supplier_id, material_id=sm.material_id,
                                branch_context=sm.branch_context, cost=sm.current_cost, source=source, created_by=user_email))


@router.post("/supplier-materials", response_model=SupplierMaterialOut, status_code=201)
async def create_manual_supplier_material(payload: ManualSupplierMaterialIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    sup = await db.get(Supplier, payload.supplier_id)
    if not sup:
        raise HTTPException(status_code=404, detail="Supplier not found")
    sm = await inv_core.upsert_supplier_material(
        db, material_id=payload.material_id, supplier_id=payload.supplier_id,
        integration_provider=(sup.integration_provider or "manual"),
        supplier_item_number=payload.supplier_item_number, supplier_description=payload.supplier_description,
        supplier_uom=payload.supplier_uom, current_cost=payload.current_cost)
    await db.flush()  # assign sm.id before snapshotting price history
    sm.conversion_factor = payload.conversion_factor or 1
    sm.manufacturer_part_number = payload.manufacturer_part_number
    sm.lead_time_days = payload.lead_time_days
    sm.meta = {**(sm.meta or {}), "notes": payload.notes} if payload.notes else sm.meta
    if payload.current_cost is not None:
        sm.price_status = "manual"
        await _snapshot_price(db, sm, "manual", user.email)
    await db.commit(); await db.refresh(sm)
    await log_action(db, user=user, action="supplier_material.create", entity_type="supplier_material", entity_id=sm.id, detail={"manual": True}, request=request)
    return await _sm_out(db, sm)


@router.patch("/supplier-materials/{sm_id}", response_model=SupplierMaterialOut)
async def update_manual_supplier_material(sm_id: str, payload: ManualSupplierMaterialPatch, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    sm = await db.get(SupplierMaterial, sm_id)
    if not sm:
        raise HTTPException(status_code=404, detail="Supplier mapping not found")
    data = payload.model_dump(exclude_unset=True)
    cost_changed = ("current_cost" in data and data["current_cost"] != sm.current_cost)
    for k, v in data.items():
        if k == "notes":
            sm.meta = {**(sm.meta or {}), "notes": v}
        else:
            setattr(sm, k, v)
    if cost_changed:
        sm.price_status = "manual"
        from datetime import datetime, timezone
        sm.price_updated_at = datetime.now(timezone.utc)
        await _snapshot_price(db, sm, "manual", user.email)
    await db.commit(); await db.refresh(sm)
    await log_action(db, user=user, action="supplier_material.update", entity_type="supplier_material", entity_id=sm.id, detail={"cost_changed": cost_changed}, request=request)
    return await _sm_out(db, sm)


@router.get("/supplier-materials/{sm_id}/price-history", response_model=list[PriceHistoryOut])
async def price_history(sm_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from models import SupplierPriceHistory
    rows = (await db.execute(select(SupplierPriceHistory).where(SupplierPriceHistory.supplier_material_id == sm_id).order_by(SupplierPriceHistory.created_at.desc()))).scalars().all()
    return [PriceHistoryOut(id=str(r.id), cost=r.cost, source=r.source, branch_context=r.branch_context, created_by=r.created_by, created_at=r.created_at) for r in rows]


async def _sm_out(db, sm: SupplierMaterial) -> SupplierMaterialOut:
    sname = None
    if sm.supplier_id:
        sup = await db.get(Supplier, sm.supplier_id)
        sname = sup.name if sup else None
    return SupplierMaterialOut(
        id=str(sm.id), material_id=str(sm.material_id), supplier_id=(str(sm.supplier_id) if sm.supplier_id else None),
        supplier_name=sname, integration_provider=sm.integration_provider, external_item_id=sm.external_item_id,
        supplier_item_number=sm.supplier_item_number, supplier_description=sm.supplier_description,
        supplier_uom=sm.supplier_uom, current_cost=sm.current_cost, price_status=sm.price_status,
        price_updated_at=sm.price_updated_at, availability_status=sm.availability_status,
        lead_time_days=sm.lead_time_days, is_preferred=sm.is_preferred, active=sm.active)
