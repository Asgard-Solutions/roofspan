import re

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Material, InventoryTxn, Supplier, SupplierMaterial, User
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_phase4 import MaterialIn, MaterialPatch, MaterialOut, AdjustIn, SupplierIn, SupplierOut
from integrations.abc_supply.schemas import SupplierMaterialOut

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


@router.get("/materials", response_model=list[MaterialOut])
async def list_materials(low_stock: bool | None = Query(None), q: str | None = Query(None), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Material).order_by(Material.name)
    if q:
        stmt = stmt.where(Material.name.ilike(f"%{q}%"))
    rows = (await db.execute(stmt)).scalars().all()
    out = [_mat_out(m) for m in rows]
    if low_stock:
        out = [m for m in out if m.low_stock]
    return out


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


@router.post("/materials/{material_id}/adjust", response_model=MaterialOut)
async def adjust_material(material_id: str, payload: AdjustIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    m = (await db.execute(select(Material).where(Material.id == material_id).with_for_update())).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Material not found")
    new_qty = round(m.quantity_on_hand + payload.delta, 3)
    if new_qty < 0:
        raise HTTPException(status_code=400, detail=f"Adjustment would make quantity negative (on hand {m.quantity_on_hand})")
    m.quantity_on_hand = new_qty
    db.add(InventoryTxn(material_id=m.id, delta=payload.delta, reason=payload.reason, note=payload.note, created_by=user.email))
    await db.commit()
    await db.refresh(m)
    await log_action(db, user=user, action="inventory.adjust", entity_type="material", entity_id=m.id, detail={"delta": payload.delta, "reason": payload.reason, "on_hand": new_qty}, request=request)
    return _mat_out(m)

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
