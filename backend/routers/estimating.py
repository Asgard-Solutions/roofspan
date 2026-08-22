from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import (Assembly, AssemblyItem, PriceBook, PriceBookEntry, Material, Supplier,
                    SupplierMaterial, User)
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_estimating import (AssemblyIn, AssemblyOut, AssemblyItemOut, AssemblyExpandOut,
                                PriceBookIn, PriceBookPatch, PriceBookOut, PriceBookEntryIn, PriceBookEntryOut)
from services import estimating as calc
from services import inventory_core as inv_core

router = APIRouter(prefix="/api/estimating", tags=["estimating"])


# ============================ Assemblies ============================
async def _assembly_out(db: AsyncSession, a: Assembly) -> AssemblyOut:
    rows = (await db.execute(
        select(AssemblyItem, Material.name).outerjoin(Material, Material.id == AssemblyItem.material_id)
        .where(AssemblyItem.assembly_id == a.id).order_by(AssemblyItem.sort)
    )).all()
    items = []
    for it, mname in rows:
        cost = None
        if it.material_id:
            sm = await inv_core.preferred_supplier_material(db, it.material_id) or await inv_core.best_known_supplier_material(db, it.material_id)
            cost = sm.current_cost if sm else None
        items.append(AssemblyItemOut(id=str(it.id), material_id=str(it.material_id) if it.material_id else None,
                                     description=it.description, quantity_factor=it.quantity_factor, unit=it.unit,
                                     waste_override=it.waste_override, is_labor=it.is_labor, sort=it.sort,
                                     material_name=mname, current_cost=cost))
    return AssemblyOut(id=str(a.id), name=a.name, category=a.category, unit_basis=a.unit_basis, active=a.active,
                       notes=a.notes, version=a.version, created_at=a.created_at, items=items)


@router.get("/assemblies", response_model=list[AssemblyOut])
async def list_assemblies(active: bool | None = Query(None), q: str | None = Query(None),
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Assembly).order_by(Assembly.name)
    if active is not None:
        stmt = stmt.where(Assembly.active.is_(active))
    if q:
        stmt = stmt.where(Assembly.name.ilike(f"%{q}%"))
    return [await _assembly_out(db, a) for a in (await db.execute(stmt)).scalars().all()]


@router.post("/assemblies", response_model=AssemblyOut, status_code=201)
async def create_assembly(payload: AssemblyIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    a = Assembly(name=payload.name, category=payload.category, unit_basis=payload.unit_basis,
                 active=payload.active, notes=payload.notes, created_by=user.email)
    db.add(a)
    await db.flush()
    for idx, it in enumerate(payload.items):
        db.add(AssemblyItem(assembly_id=a.id, material_id=it.material_id or None, description=it.description,
                            quantity_factor=it.quantity_factor, unit=it.unit, waste_override=it.waste_override,
                            is_labor=it.is_labor, sort=idx))
    await db.commit(); await db.refresh(a)
    await log_action(db, user=user, action="assembly.create", entity_type="assembly", entity_id=a.id, request=request)
    return await _assembly_out(db, a)


@router.get("/assemblies/{assembly_id}", response_model=AssemblyOut)
async def get_assembly(assembly_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    a = await db.get(Assembly, assembly_id)
    if not a:
        raise HTTPException(status_code=404, detail="Assembly not found")
    return await _assembly_out(db, a)


@router.put("/assemblies/{assembly_id}", response_model=AssemblyOut)
async def update_assembly(assembly_id: str, payload: AssemblyIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    a = await db.get(Assembly, assembly_id)
    if not a:
        raise HTTPException(status_code=404, detail="Assembly not found")
    a.name, a.category, a.unit_basis, a.active, a.notes = payload.name, payload.category, payload.unit_basis, payload.active, payload.notes
    a.version += 1  # snapshot bump — estimates created from prior versions keep their stored lines
    await db.execute(AssemblyItem.__table__.delete().where(AssemblyItem.assembly_id == a.id))
    for idx, it in enumerate(payload.items):
        db.add(AssemblyItem(assembly_id=a.id, material_id=it.material_id or None, description=it.description,
                            quantity_factor=it.quantity_factor, unit=it.unit, waste_override=it.waste_override,
                            is_labor=it.is_labor, sort=idx))
    await db.commit(); await db.refresh(a)
    await log_action(db, user=user, action="assembly.update", entity_type="assembly", entity_id=a.id, request=request)
    return await _assembly_out(db, a)


@router.post("/assemblies/{assembly_id}/active", response_model=AssemblyOut)
async def set_assembly_active(assembly_id: str, active: bool = Query(...), request: Request = None, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    a = await db.get(Assembly, assembly_id)
    if not a:
        raise HTTPException(status_code=404, detail="Assembly not found")
    a.active = active
    await db.commit(); await db.refresh(a)
    await log_action(db, user=user, action="assembly.active", entity_type="assembly", entity_id=a.id, detail={"active": active}, request=request)
    return await _assembly_out(db, a)


@router.post("/assemblies/{assembly_id}/expand", response_model=AssemblyExpandOut)
async def expand_assembly(assembly_id: str, quantity: float = Query(1), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Generate estimate lines from an assembly for a given quantity of its unit_basis.
    Snapshots current material cost + the assembly version. Returned lines are added to the estimate editor."""
    a = await db.get(Assembly, assembly_id)
    if not a:
        raise HTTPException(status_code=404, detail="Assembly not found")
    rows = (await db.execute(select(AssemblyItem).where(AssemblyItem.assembly_id == a.id).order_by(AssemblyItem.sort))).scalars().all()
    lines = []
    for it in rows:
        base_cost = 0.0
        sm_id = sup_id = sup_name = item_no = None
        conv = None
        purchase_unit = None
        cost_source = "manual"
        if it.material_id:
            sm = await inv_core.preferred_supplier_material(db, it.material_id) or await inv_core.best_known_supplier_material(db, it.material_id)
            if sm:
                base_cost = sm.current_cost or 0
                sm_id = str(sm.id)
                item_no = sm.supplier_item_number
                conv = sm.conversion_factor
                purchase_unit = sm.supplier_uom
                cost_source = sm.price_status or "manual"
                if sm.supplier_id:
                    s = await db.get(Supplier, sm.supplier_id)
                    sup_id, sup_name = str(sm.supplier_id), (s.name if s else None)
        line = {
            "description": it.description, "unit": it.unit,
            "measured_quantity": calc.r4(it.quantity_factor * (quantity or 0)),
            "waste_percent": it.waste_override if it.waste_override is not None else 0,
            "material_id": str(it.material_id) if it.material_id else None,
            "supplier_material_id": sm_id,
            "line_kind": "labor" if it.is_labor else ("material" if it.material_id else "custom"),
            "material_cost": 0 if it.is_labor else base_cost,
            "labor_cost": base_cost if it.is_labor else 0,
            "base_cost": base_cost, "conversion_factor": conv, "purchase_unit": purchase_unit,
            "cost_source_supplier_id": sup_id, "cost_source_supplier_name": sup_name,
            "supplier_item_number": item_no, "cost_source": cost_source,
            "assembly_id": str(a.id), "assembly_version": a.version, "assembly_name": a.name,
            "markup_percent": 0,
        }
        calc.compute_line(line)
        lines.append(line)
    return AssemblyExpandOut(assembly_id=str(a.id), assembly_name=a.name, assembly_version=a.version,
                             unit_basis=a.unit_basis, quantity=quantity, lines=lines)


# ============================ Price Books ============================
async def _pb_entry_out(db: AsyncSession, en: PriceBookEntry) -> PriceBookEntryOut:
    mname = aname = None
    if en.material_id:
        m = await db.get(Material, en.material_id); mname = m.name if m else None
    if en.assembly_id:
        a = await db.get(Assembly, en.assembly_id); aname = a.name if a else None
    return PriceBookEntryOut(id=str(en.id), target_type=en.target_type,
                             material_id=str(en.material_id) if en.material_id else None,
                             assembly_id=str(en.assembly_id) if en.assembly_id else None,
                             label=en.label, rule_type=en.rule_type, fixed_price=en.fixed_price,
                             markup_percent=en.markup_percent, margin_percent=en.margin_percent,
                             active=en.active, sort=en.sort, material_name=mname, assembly_name=aname)


async def _pb_out(db: AsyncSession, pb: PriceBook) -> PriceBookOut:
    ens = (await db.execute(select(PriceBookEntry).where(PriceBookEntry.price_book_id == pb.id).order_by(PriceBookEntry.sort))).scalars().all()
    return PriceBookOut(id=str(pb.id), name=pb.name, description=pb.description, active=pb.active,
                        is_default=pb.is_default, created_at=pb.created_at,
                        entries=[await _pb_entry_out(db, e) for e in ens])


@router.get("/price-books", response_model=list[PriceBookOut])
async def list_price_books(active: bool | None = Query(None), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(PriceBook).order_by(PriceBook.is_default.desc(), PriceBook.name)
    if active is not None:
        stmt = stmt.where(PriceBook.active.is_(active))
    return [await _pb_out(db, pb) for pb in (await db.execute(stmt)).scalars().all()]


async def _clear_other_defaults(db: AsyncSession, keep_id=None):
    rows = (await db.execute(select(PriceBook).where(PriceBook.is_default.is_(True)))).scalars().all()
    for r in rows:
        if str(r.id) != str(keep_id):
            r.is_default = False
    await db.flush()


@router.post("/price-books", response_model=PriceBookOut, status_code=201)
async def create_price_book(payload: PriceBookIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    pb = PriceBook(name=payload.name, description=payload.description, active=payload.active,
                   is_default=payload.is_default, created_by=user.email)
    if payload.is_default:
        await _clear_other_defaults(db)
    db.add(pb)
    await db.commit(); await db.refresh(pb)
    await log_action(db, user=user, action="pricebook.create", entity_type="price_book", entity_id=pb.id, request=request)
    return await _pb_out(db, pb)


@router.get("/price-books/{pb_id}", response_model=PriceBookOut)
async def get_price_book(pb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    pb = await db.get(PriceBook, pb_id)
    if not pb:
        raise HTTPException(status_code=404, detail="Price book not found")
    return await _pb_out(db, pb)


@router.patch("/price-books/{pb_id}", response_model=PriceBookOut)
async def update_price_book(pb_id: str, payload: PriceBookPatch, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    pb = await db.get(PriceBook, pb_id)
    if not pb:
        raise HTTPException(status_code=404, detail="Price book not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_default"):
        await _clear_other_defaults(db, keep_id=pb.id)
    for k, v in data.items():
        setattr(pb, k, v)
    await db.commit(); await db.refresh(pb)
    await log_action(db, user=user, action="pricebook.update", entity_type="price_book", entity_id=pb.id, request=request)
    return await _pb_out(db, pb)


@router.put("/price-books/{pb_id}/entries", response_model=PriceBookOut)
async def set_price_book_entries(pb_id: str, entries: list[PriceBookEntryIn], request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    pb = await db.get(PriceBook, pb_id)
    if not pb:
        raise HTTPException(status_code=404, detail="Price book not found")
    await db.execute(PriceBookEntry.__table__.delete().where(PriceBookEntry.price_book_id == pb.id))
    for idx, en in enumerate(entries):
        db.add(PriceBookEntry(price_book_id=pb.id, target_type=en.target_type, material_id=en.material_id or None,
                              assembly_id=en.assembly_id or None, label=en.label, rule_type=en.rule_type,
                              fixed_price=en.fixed_price, markup_percent=en.markup_percent,
                              margin_percent=en.margin_percent, active=en.active, sort=idx))
    await db.commit(); await db.refresh(pb)
    await log_action(db, user=user, action="pricebook.entries", entity_type="price_book", entity_id=pb.id, request=request)
    return await _pb_out(db, pb)
