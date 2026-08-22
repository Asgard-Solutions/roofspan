from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import (Material, InventoryLocation, InventoryBalance, InventoryTxn, PurchaseOrder, Job, User)
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from services import inventory_ops as ops

router = APIRouter(prefix="/api/inventory", tags=["inventory-ops"])


# --------- schemas ---------
class LocationIn(BaseModel):
    name: str
    type: str = "warehouse"
    address: str | None = None
    notes: str | None = None
    active: bool = True


class LocationPatch(BaseModel):
    name: str | None = None
    type: str | None = None
    address: str | None = None
    notes: str | None = None
    active: bool | None = None


class TransferIn(BaseModel):
    material_id: str
    source_location_id: str
    destination_location_id: str
    quantity: float
    notes: str | None = None
    override: bool = False


class IssueIn(BaseModel):
    material_id: str
    location_id: str
    quantity: float
    job_id: str
    override: bool = False


class ReturnIn(BaseModel):
    material_id: str
    location_id: str
    quantity: float
    job_id: str | None = None
    reason: str | None = None


class DispositionIn(BaseModel):
    material_id: str
    location_id: str
    quantity: float
    kind: str  # waste | damage | loss
    job_id: str | None = None
    reason: str | None = None
    override: bool = False


class CycleCountLine(BaseModel):
    material_id: str
    counted_quantity: float


class CycleCountIn(BaseModel):
    location_id: str
    lines: list[CycleCountLine]
    notes: str | None = None


def _loc_out(l: InventoryLocation) -> dict:
    return {"id": str(l.id), "name": l.name, "type": l.type, "active": l.active, "is_default": l.is_default,
            "address": l.address, "notes": l.notes}


# --------- locations ---------
@router.get("/locations")
async def list_locations(active: bool | None = Query(None), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(InventoryLocation).order_by(InventoryLocation.is_default.desc(), InventoryLocation.name)
    if active is not None:
        stmt = stmt.where(InventoryLocation.active.is_(active))
    return [_loc_out(l) for l in (await db.execute(stmt)).scalars().all()]


@router.post("/locations", status_code=201)
async def create_location(payload: LocationIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    l = InventoryLocation(name=payload.name, type=payload.type, address=payload.address, notes=payload.notes, active=payload.active)
    db.add(l)
    await db.commit(); await db.refresh(l)
    await log_action(db, user=user, action="location.create", entity_type="inventory_location", entity_id=l.id, request=request)
    return _loc_out(l)


@router.patch("/locations/{loc_id}")
async def update_location(loc_id: str, payload: LocationPatch, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    l = await db.get(InventoryLocation, loc_id)
    if not l:
        raise HTTPException(status_code=404, detail="Location not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(l, k, v)
    await db.commit(); await db.refresh(l)
    await log_action(db, user=user, action="location.update", entity_type="inventory_location", entity_id=l.id, request=request)
    return _loc_out(l)


@router.get("/locations/{loc_id}")
async def location_detail(loc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    l = await db.get(InventoryLocation, loc_id)
    if not l:
        raise HTTPException(status_code=404, detail="Location not found")
    rows = (await db.execute(select(InventoryBalance, Material.name, Material.unit)
                             .join(Material, Material.id == InventoryBalance.material_id)
                             .where(InventoryBalance.location_id == l.id, InventoryBalance.quantity_on_hand != 0)
                             .order_by(Material.name))).all()
    materials = [{"material_id": str(b.material_id), "material_name": n, "unit": u, "quantity_on_hand": ops._r3(b.quantity_on_hand)} for b, n, u in rows]
    txns = (await db.execute(select(InventoryTxn).where(
        (InventoryTxn.source_location_id == l.id) | (InventoryTxn.destination_location_id == l.id))
        .order_by(InventoryTxn.created_at.desc()).limit(25))).scalars().all()
    recent = [{"id": str(t.id), "material_id": str(t.material_id), "delta": t.delta, "reason": t.reason,
               "created_at": t.created_at.isoformat() if t.created_at else None, "note": t.note} for t in txns]
    return {"location": _loc_out(l), "materials": materials, "recent_transactions": recent}


# --------- balances for a material ---------
@router.get("/balances")
async def material_balances(material_id: str = Query(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(InventoryBalance, InventoryLocation.name, InventoryLocation.type)
                             .join(InventoryLocation, InventoryLocation.id == InventoryBalance.location_id)
                             .where(InventoryBalance.material_id == material_id, InventoryBalance.quantity_on_hand != 0)
                             .order_by(InventoryLocation.name))).all()
    return {"balances": [{"location_id": str(b.location_id), "location_name": n, "location_type": t,
                          "quantity_on_hand": ops._r3(b.quantity_on_hand)} for b, n, t in rows]}


# --------- movements ---------
async def _mat(db, mid) -> Material:
    m = (await db.execute(select(Material).where(Material.id == mid).with_for_update())).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Material not found")
    return m


@router.post("/transfer")
async def do_transfer(payload: TransferIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    m = await _mat(db, payload.material_id)
    await ops.transfer(db, m, payload.source_location_id, payload.destination_location_id, payload.quantity, user.email, payload.notes, payload.override)
    await db.commit()
    await log_action(db, user=user, action="inventory.transfer", entity_type="material", entity_id=m.id, detail={"qty": payload.quantity}, request=request)
    return {"ok": True}


@router.post("/issue")
async def do_issue(payload: IssueIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    m = await _mat(db, payload.material_id)
    await ops.issue(db, m, payload.location_id, payload.quantity, payload.job_id, user.email, payload.override)
    await db.commit()
    await log_action(db, user=user, action="inventory.issue", entity_type="job", entity_id=payload.job_id, detail={"material": payload.material_id, "qty": payload.quantity}, request=request)
    return {"ok": True}


@router.post("/return")
async def do_return(payload: ReturnIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    m = await _mat(db, payload.material_id)
    await ops.return_to_stock(db, m, payload.location_id, payload.quantity, payload.job_id, user.email, payload.reason)
    await db.commit()
    await log_action(db, user=user, action="inventory.return", entity_type="job", entity_id=payload.job_id, detail={"material": payload.material_id, "qty": payload.quantity}, request=request)
    return {"ok": True}


@router.post("/disposition")
async def do_disposition(payload: DispositionIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    m = await _mat(db, payload.material_id)
    await ops.disposition(db, m, payload.location_id, payload.quantity, payload.kind, user.email, payload.job_id, payload.reason, payload.override)
    await db.commit()
    await log_action(db, user=user, action=f"inventory.{payload.kind}", entity_type="material", entity_id=m.id, detail={"qty": payload.quantity, "job": payload.job_id}, request=request)
    return {"ok": True}


@router.post("/cycle-count")
async def do_cycle_count(payload: CycleCountIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    results = []
    for ln in payload.lines:
        m = await _mat(db, ln.material_id)
        r = await ops.cycle_count_adjust(db, m, payload.location_id, ln.counted_quantity, user.email, payload.notes)
        results.append({"material_id": ln.material_id, **r})
    await db.commit()
    await log_action(db, user=user, action="inventory.cycle_count", entity_type="inventory_location", entity_id=payload.location_id, detail={"lines": len(payload.lines)}, request=request)
    return {"results": results}


# --------- transaction history ---------
@router.get("/transactions")
async def transactions(material_id: str | None = Query(None), location_id: str | None = Query(None),
                       job_id: str | None = Query(None), po_id: str | None = Query(None),
                       reason: str | None = Query(None), limit: int = Query(100, le=500),
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(InventoryTxn, Material.name).join(Material, Material.id == InventoryTxn.material_id).order_by(InventoryTxn.created_at.desc()).limit(limit)
    if material_id:
        stmt = stmt.where(InventoryTxn.material_id == material_id)
    if job_id:
        stmt = stmt.where(InventoryTxn.job_id == job_id)
    if po_id:
        stmt = stmt.where(InventoryTxn.po_id == po_id)
    if reason:
        stmt = stmt.where(InventoryTxn.reason == reason)
    if location_id:
        stmt = stmt.where((InventoryTxn.source_location_id == location_id) | (InventoryTxn.destination_location_id == location_id))
    rows = (await db.execute(stmt)).all()
    # resolve location names
    locs = {str(l.id): l.name for l in (await db.execute(select(InventoryLocation))).scalars().all()}
    see_cost = user.role in MANAGE_ROLES  # cost basis is hidden from Sales
    return {"transactions": [{
        "id": str(t.id), "created_at": t.created_at.isoformat() if t.created_at else None, "material_id": str(t.material_id),
        "material_name": n, "delta": t.delta, "reason": t.reason, "job_id": str(t.job_id) if t.job_id else None,
        "po_id": str(t.po_id) if t.po_id else None, "note": t.note, "created_by": t.created_by,
        "unit_cost": (float(t.unit_cost) if t.unit_cost is not None else None) if see_cost else None,
        "extended_cost": (float(t.extended_cost) if t.extended_cost is not None else None) if see_cost else None,
        "source_location": locs.get(str(t.source_location_id)) if t.source_location_id else None,
        "destination_location": locs.get(str(t.destination_location_id)) if t.destination_location_id else None,
    } for t, n in rows]}
