from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import PurchaseOrder, POLineItem, Supplier, Material, InventoryTxn, User
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_phase4 import POIn, POStatusIn, ReceiveIn, POOut, POLineOut
from sales_common import next_number, check_idempotency, record_idempotency

router = APIRouter(prefix="/api/purchase-orders", tags=["purchasing"])
VALID = ["draft", "ordered", "partially_received", "received", "cancelled"]


async def _find_or_create_supplier(db: AsyncSession, name: str | None):
    if not name or not name.strip():
        return None
    name = name.strip()
    s = (await db.execute(select(Supplier).where(Supplier.name == name))).scalar_one_or_none()
    if not s:
        s = Supplier(name=name)
        db.add(s)
        await db.flush()
    return s


async def _out(db: AsyncSession, po: PurchaseOrder) -> POOut:
    items = (await db.execute(select(POLineItem).where(POLineItem.po_id == po.id).order_by(POLineItem.sort))).scalars().all()
    supplier_name = None
    if po.supplier_id:
        s = await db.get(Supplier, po.supplier_id)
        supplier_name = s.name if s else None
    return POOut(
        id=str(po.id), number=po.number, supplier_id=str(po.supplier_id) if po.supplier_id else None,
        supplier_name=supplier_name, job_id=str(po.job_id) if po.job_id else None, status=po.status,
        order_date=po.order_date, expected_date=po.expected_date, total=po.total, notes=po.notes, created_at=po.created_at,
        items=[POLineOut(id=str(i.id), material_id=str(i.material_id) if i.material_id else None, description=i.description,
                         quantity=i.quantity, unit=i.unit, unit_cost=i.unit_cost, line_total=i.line_total,
                         received_quantity=i.received_quantity) for i in items],
    )


@router.get("", response_model=list[POOut])
async def list_pos(job_id: str | None = Query(None), status: str | None = Query(None), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())
    if job_id:
        stmt = stmt.where(PurchaseOrder.job_id == job_id)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    return [await _out(db, po) for po in (await db.execute(stmt)).scalars().all()]


@router.post("", response_model=POOut, status_code=201)
async def create_po(payload: POIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    supplier = await _find_or_create_supplier(db, payload.supplier_name)
    number = await next_number(db, "po", "PO")
    total = round(sum((it.quantity or 0) * (it.unit_cost or 0) for it in payload.items), 2)
    po = PurchaseOrder(number=number, supplier_id=supplier.id if supplier else None, job_id=payload.job_id,
                       status="draft", expected_date=payload.expected_date, total=total, notes=payload.notes, created_by=user.email)
    db.add(po)
    await db.flush()
    for idx, it in enumerate(payload.items):
        desc = it.description
        if not desc and it.material_id:
            m = await db.get(Material, it.material_id)
            desc = m.name if m else ""
        db.add(POLineItem(po_id=po.id, material_id=it.material_id, description=desc, quantity=it.quantity,
                          unit=it.unit, unit_cost=it.unit_cost, line_total=round((it.quantity or 0) * (it.unit_cost or 0), 2), sort=idx))
    await db.commit()
    await db.refresh(po)
    await log_action(db, user=user, action="po.create", entity_type="purchase_order", entity_id=po.id, detail={"number": number, "total": total}, request=request)
    return await _out(db, po)


@router.get("/{po_id}", response_model=POOut)
async def get_po(po_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    po = await db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return await _out(db, po)


@router.post("/{po_id}/status", response_model=POOut)
async def set_status(po_id: str, payload: POStatusIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    po = await db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if payload.status not in VALID:
        raise HTTPException(status_code=422, detail=f"Status must be one of {VALID}")
    if payload.status == "ordered" and not po.order_date:
        po.order_date = datetime.now(timezone.utc)
    po.status = payload.status
    await db.commit()
    await db.refresh(po)
    await log_action(db, user=user, action="po.status", entity_type="purchase_order", entity_id=po.id, detail={"status": payload.status}, request=request)
    return await _out(db, po)


@router.post("/{po_id}/receive", response_model=POOut)
async def receive(po_id: str, payload: ReceiveIn, request: Request, idempotency_key: str | None = Header(None), user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    # Idempotent receiving: same Idempotency-Key returns without double-incrementing inventory.
    prior = await check_idempotency(db, idempotency_key, "receipt")
    po = await db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if prior:
        return await _out(db, po)
    if po.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot receive against a cancelled purchase order")
    if not payload.items:
        raise HTTPException(status_code=400, detail="No items to receive")

    for line in payload.items:
        item = await db.get(POLineItem, line.po_item_id)
        if not item or item.po_id != po.id:
            raise HTTPException(status_code=404, detail="PO line item not found on this purchase order")
        remaining = item.quantity - item.received_quantity
        if line.quantity > remaining + 1e-9:
            raise HTTPException(status_code=400, detail=f"Cannot receive {line.quantity}; only {remaining} remaining on '{item.description}'")
        item.received_quantity = round(item.received_quantity + line.quantity, 3)
        if item.material_id:
            m = (await db.execute(select(Material).where(Material.id == item.material_id).with_for_update())).scalar_one_or_none()
            if m:
                m.quantity_on_hand = round(m.quantity_on_hand + line.quantity, 3)
                db.add(InventoryTxn(material_id=m.id, delta=line.quantity, reason="receipt", po_id=po.id, created_by=user.email))

    items = (await db.execute(select(POLineItem).where(POLineItem.po_id == po.id))).scalars().all()
    fully = all(i.received_quantity >= i.quantity - 1e-9 for i in items)
    any_recv = any(i.received_quantity > 0 for i in items)
    po.status = "received" if fully else ("partially_received" if any_recv else po.status)
    await record_idempotency(db, idempotency_key, "receipt", po.id)
    await db.commit()
    await db.refresh(po)
    await log_action(db, user=user, action="po.receive", entity_type="purchase_order", entity_id=po.id, detail={"status": po.status, "lines": len(payload.items)}, request=request)
    return await _out(db, po)
