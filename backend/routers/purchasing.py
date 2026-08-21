from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import PurchaseOrder, POLineItem, Supplier, Material, InventoryTxn, IdempotencyKey, User
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_phase4 import POIn, POStatusIn, ReceiveIn, POOut, POLineOut, RefreshPriceIn, RefreshPriceOut
from sales_common import next_number

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
    unresolved = sum(1 for i in items if i.integration_provider == "abc_supply" and i.abc_price_status == "unavailable")
    warning = None
    if unresolved:
        warning = f"{unresolved} ABC Supply item{'s' if unresolved != 1 else ''} do not currently have pricing."
    return POOut(
        id=str(po.id), number=po.number, supplier_id=str(po.supplier_id) if po.supplier_id else None,
        supplier_name=supplier_name, job_id=str(po.job_id) if po.job_id else None, status=po.status,
        order_date=po.order_date, expected_date=po.expected_date, total=po.total, notes=po.notes, created_at=po.created_at,
        integration_provider=po.integration_provider, abc_ship_to_number=po.abc_ship_to_number, abc_branch_number=po.abc_branch_number,
        pricing_warning=warning,
        items=[POLineOut(id=str(i.id), material_id=str(i.material_id) if i.material_id else None, description=i.description,
                         quantity=i.quantity, unit=i.unit, unit_cost=i.unit_cost, line_total=i.line_total,
                         received_quantity=i.received_quantity,
                         integration_provider=i.integration_provider, abc_item_number=i.abc_item_number,
                         abc_branch_number=i.abc_branch_number, abc_ship_to_number=i.abc_ship_to_number,
                         abc_uom=i.abc_uom, abc_variation=i.abc_variation, abc_price=i.abc_price,
                         abc_price_status=i.abc_price_status, abc_price_timestamp=i.abc_price_timestamp,
                         abc_product_description=i.abc_product_description, abc_product_family=i.abc_product_family,
                         abc_product_image_url=i.abc_product_image_url, pricing_source=i.pricing_source) for i in items],
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
                       status="draft", expected_date=payload.expected_date, total=total, notes=payload.notes, created_by=user.email,
                       integration_provider=payload.integration_provider,
                       abc_ship_to_number=payload.abc_ship_to_number, abc_branch_number=payload.abc_branch_number)
    db.add(po)
    await db.flush()
    for idx, it in enumerate(payload.items):
        desc = it.description
        if not desc and it.material_id:
            m = await db.get(Material, it.material_id)
            desc = m.name if m else ""
        db.add(POLineItem(po_id=po.id, material_id=it.material_id, description=desc, quantity=it.quantity,
                          unit=it.unit, unit_cost=it.unit_cost, line_total=round((it.quantity or 0) * (it.unit_cost or 0), 2), sort=idx,
                          integration_provider=it.integration_provider, abc_item_number=it.abc_item_number,
                          abc_branch_number=it.abc_branch_number, abc_ship_to_number=it.abc_ship_to_number,
                          abc_uom=it.abc_uom, abc_variation=it.abc_variation, abc_price=it.abc_price,
                          abc_price_status=it.abc_price_status,
                          abc_price_timestamp=(datetime.now(timezone.utc) if it.abc_price is not None else None),
                          abc_product_description=it.abc_product_description, abc_product_family=it.abc_product_family,
                          abc_product_image_url=it.abc_product_image_url,
                          pricing_source=it.pricing_source or ("abc" if it.abc_item_number else None)))
    await db.commit()
    await db.refresh(po)
    await log_action(db, user=user, action="po.create", entity_type="purchase_order", entity_id=po.id, detail={"number": number, "total": total}, request=request)
    return await _out(db, po)


@router.post("/{po_id}/refresh-price", response_model=RefreshPriceOut)
async def refresh_abc_price(po_id: str, payload: RefreshPriceIn, request: Request,
                            user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """Refresh the real-time ABC price for one ABC-linked PO line, using the line's current Ship-To,
    branch, quantity, UOM and variation. Optionally apply the new price to the line cost. Never auto-submits."""
    from routers import abc_supply as abc_router
    from integrations.abc_supply import pricing as abc_pricing
    from integrations.abc_supply.client import AbcClient

    po = await db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    line = await db.get(POLineItem, payload.po_item_id)
    if not line or line.po_id != po.id:
        raise HTTPException(status_code=404, detail="PO line item not found on this purchase order")
    if line.integration_provider != "abc_supply" or not line.abc_item_number:
        raise HTTPException(status_code=400, detail="This line is not an ABC Supply product")

    ship_to = line.abc_ship_to_number or po.abc_ship_to_number
    branch = line.abc_branch_number or po.abc_branch_number
    if not ship_to or not branch:
        raise HTTPException(status_code=400, detail="ABC Ship-To and branch are required to refresh pricing")

    row = await abc_router._get_or_create(db)
    access = await abc_router._ensure_user_token(db, row, request)
    client = AbcClient(abc_router._build_cfg(row, redirect_uri=abc_router._effective_redirect(row, request)), access_token=access)

    length = line.abc_variation or {}
    plines = [abc_pricing.build_line(line_id=str(line.id), item_number=line.abc_item_number,
                                     quantity=line.quantity, uom=line.abc_uom,
                                     length_value=length.get("value"), length_uom=length.get("uom"))]
    result = await abc_pricing.price_items(client, ship_to_number=ship_to, branch_number=branch, lines=plines, purpose="ordering")
    r = result[0] if result else {"price_status": "unavailable", "unit_price": None, "status_message": "No response"}

    previous = line.unit_cost
    line.abc_price = r.get("unit_price")
    line.abc_price_status = r.get("price_status")
    line.abc_price_timestamp = datetime.now(timezone.utc)
    priced = r.get("price_status") == "priced" and r.get("unit_price") is not None
    changed = priced and round(float(r["unit_price"]), 4) != round(float(previous or 0), 4)
    applied = False
    if payload.apply and priced:
        line.unit_cost = float(r["unit_price"])
        line.line_total = round(line.quantity * line.unit_cost, 2)
        line.pricing_source = "abc"
        applied = True
    await db.flush()
    if applied:
        items = (await db.execute(select(POLineItem).where(POLineItem.po_id == po.id))).scalars().all()
        po.total = round(sum(i.line_total for i in items), 2)
    await db.commit()
    await log_action(db, user=user, action=("abc.price.apply" if applied else "abc.price.refresh"),
                     entity_type="purchase_order", entity_id=po.id,
                     detail={"line": str(line.id), "status": line.abc_price_status, "applied": applied}, request=request)
    return RefreshPriceOut(po_item_id=str(line.id), previous_unit_cost=previous, abc_price=line.abc_price,
                           price_status=line.abc_price_status, changed=changed, applied=applied,
                           message=r.get("status_message"))


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
    # Atomic idempotent receiving: a unique Idempotency-Key row is reserved BEFORE any inventory
    # mutation, so concurrent or repeated requests with the same key cannot double-post inventory.
    po = await db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot receive against a cancelled purchase order")
    if not payload.items:
        raise HTTPException(status_code=400, detail="No items to receive")

    if idempotency_key:
        existing = await db.get(IdempotencyKey, idempotency_key)
        if existing:
            if existing.entity_type == "receipt" and existing.entity_id == str(po.id):
                return await _out(db, po)  # replay -> return current state, no mutation
            raise HTTPException(status_code=409, detail="Idempotency-Key already used for a different operation")
        db.add(IdempotencyKey(key=idempotency_key, entity_type="receipt", entity_id=str(po.id)))
        try:
            await db.flush()  # unique PK enforces atomicity against concurrent duplicates
        except IntegrityError:
            await db.rollback()
            po = await db.get(PurchaseOrder, po_id)
            return await _out(db, po)

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
    await db.commit()
    await db.refresh(po)
    await log_action(db, user=user, action="po.receive", entity_type="purchase_order", entity_id=po.id, detail={"status": po.status, "lines": len(payload.items)}, request=request)
    return await _out(db, po)
