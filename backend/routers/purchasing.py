from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import PurchaseOrder, POLineItem, Supplier, Material, InventoryTxn, IdempotencyKey, User, AbcOrderSubmission
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_phase4 import POIn, POStatusIn, ReceiveIn, POOut, POLineOut, RefreshPriceIn, RefreshPriceOut, AbcSubmitReviewIn, AbcSubmitIn
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
    abc_delivery = None
    if po.integration_provider == "abc_supply":
        sub = (await db.execute(select(AbcOrderSubmission).where(
            AbcOrderSubmission.purchase_order_id == po.id, AbcOrderSubmission.status.in_(["confirmed", "unknown"]))
            .order_by(AbcOrderSubmission.attempted_at.desc()))).scalars().first()
        if sub:
            abc_delivery = sub.delivery
    return POOut(
        id=str(po.id), number=po.number, supplier_id=str(po.supplier_id) if po.supplier_id else None,
        supplier_name=supplier_name, job_id=str(po.job_id) if po.job_id else None, status=po.status,
        order_date=po.order_date, expected_date=po.expected_date, total=po.total, notes=po.notes, created_at=po.created_at,
        integration_provider=po.integration_provider, abc_ship_to_number=po.abc_ship_to_number, abc_branch_number=po.abc_branch_number,
        external_order_number=po.external_order_number, external_confirmation_number=po.external_confirmation_number,
        external_tracking_id=po.external_tracking_id, abc_order_status=po.abc_order_status,
        abc_normalized_status=po.abc_normalized_status, abc_submitted_at=po.abc_submitted_at, abc_last_sync_at=po.abc_last_sync_at,
        abc_delivery=abc_delivery,
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


# ============================ ABC Supply Ordering (Phase 3) ============================
async def _abc_client(db: AsyncSession, request: Request):
    from routers import abc_supply as abc_router
    from integrations.abc_supply.client import AbcClient
    row = await abc_router._get_or_create(db)
    access = await abc_router._ensure_user_token(db, row, request)
    return AbcClient(abc_router._build_cfg(row, redirect_uri=abc_router._effective_redirect(row, request)), access_token=access), row


async def _validate_and_price(db: AsyncSession, po: PurchaseOrder, request: Request, *, apply_changes: bool):
    """Server-side pre-submit validation + MANDATORY fresh pricing. Returns (errors, changes, items, priced)."""
    from routers import abc_supply as abc_router
    from integrations.abc_supply import pricing as abc_pricing

    errors: list[str] = []
    row = await abc_router._get_or_create(db)
    if row.status != "connected":
        errors.append("ABC Supply is not connected.")
    if not po.abc_ship_to_number:
        errors.append("A Ship-To account is required.")
    if not po.abc_branch_number:
        errors.append("A branch is required.")
    items = (await db.execute(select(POLineItem).where(POLineItem.po_id == po.id).order_by(POLineItem.sort))).scalars().all()
    abc_items = [i for i in items if i.integration_provider == "abc_supply" and i.abc_item_number]
    if not abc_items:
        errors.append("The purchase order has no ABC Supply line items.")
    for i in abc_items:
        if not i.abc_uom:
            errors.append(f"Line '{i.description}' is missing a unit of measure.")
        if (i.abc_variation is None or not (i.abc_variation or {}).get("value")) and _is_dimensional(i):
            errors.append(f"Line '{i.description}' requires a length/variation.")

    changes: list[dict] = []
    priced: dict = {}
    if not errors:
        from integrations.abc_supply.exceptions import AbcError
        try:
            client, _ = await _abc_client(db, request)
            plines = []
            for i in abc_items:
                length = i.abc_variation or {}
                plines.append(abc_pricing.build_line(line_id=str(i.id), item_number=i.abc_item_number, quantity=i.quantity,
                                                     uom=i.abc_uom, length_value=length.get("value"), length_uom=length.get("uom")))
            results = await abc_pricing.price_items(client, ship_to_number=po.abc_ship_to_number,
                                                    branch_number=po.abc_branch_number, lines=plines, purpose="ordering")
        except AbcError as e:
            errors.append(e.user_message)
            return errors, changes, abc_items, priced
        priced = {str(r["id"]): r for r in results}
        for i in abc_items:
            r = priced.get(str(i.id)) or {}
            if r.get("price_status") != "priced" or r.get("unit_price") is None:
                errors.append(f"Line '{i.description}' has no available ABC price (contact the branch).")
                continue
            new_price = round(float(r["unit_price"]), 2)
            old_price = round(float(i.abc_price if i.abc_price is not None else i.unit_cost or 0), 2)
            if new_price != old_price:
                changes.append({"po_item_id": str(i.id), "description": i.description,
                                "previous_price": old_price, "current_price": new_price,
                                "difference": round(new_price - old_price, 2)})
            if apply_changes:
                i.abc_price = new_price
                i.abc_price_status = "priced"
                i.abc_price_timestamp = datetime.now(timezone.utc)
                i.unit_cost = new_price
                i.line_total = round(i.quantity * new_price, 2)
                i.pricing_source = "abc"
        if apply_changes:
            po.total = round(sum(x.line_total for x in items), 2)
    return errors, changes, abc_items, priced


def _is_dimensional(line: POLineItem) -> bool:
    v = line.abc_variation or {}
    return bool(v) and ("value" in v)


async def _default_delivery(db: AsyncSession, po: PurchaseOrder) -> dict:
    """Default the PHYSICAL delivery address from the RoofSpan job's property/customer.
    This is order-specific; it never modifies job/property/customer records and is independent
    of the ABC Ship-To account (which controls eligibility/pricing, not the delivery destination)."""
    from models import Job, Property, Customer
    d = {"name": "", "line1": "", "line2": "", "city": "", "state": "", "postal": "", "country": "USA",
         "contact_name": "", "contact_phone": "", "instructions": ""}
    if not po.job_id:
        return d
    job = await db.get(Job, po.job_id)
    if not job:
        return d
    if job.property_id:
        prop = await db.get(Property, job.property_id)
        if prop:
            d.update({"line1": prop.address_line1 or "", "line2": prop.address_line2 or "",
                      "city": prop.city or "", "state": prop.state or "", "postal": prop.zip_code or ""})
    if job.customer_id:
        cust = await db.get(Customer, job.customer_id)
        if cust:
            d["name"] = cust.name or ""
            d["contact_name"] = cust.name or ""
            d["contact_phone"] = cust.phone or ""
    d["name"] = d["name"] or job.number
    return d


def _normalize_delivery(d: dict | None) -> dict:
    d = d or {}
    return {k: (str(v).strip() if v is not None else "") for k, v in {
        "name": d.get("name"), "line1": d.get("line1"), "line2": d.get("line2"), "city": d.get("city"),
        "state": d.get("state"), "postal": d.get("postal"), "country": d.get("country") or "USA",
        "contact_name": d.get("contact_name"), "contact_phone": d.get("contact_phone"),
        "instructions": d.get("instructions"), "requested_date": d.get("requested_date"),
    }.items()}


def _validate_delivery(d: dict) -> list[str]:
    """Validate the PHYSICAL delivery override. The override is optional: when no address fields are
    supplied the order falls back to the ABC Ship-To account's registered delivery address (the submit
    builder omits ship_to.address). Only when the user provides a partial address do we require the full
    set so we never send ABC an incomplete override."""
    addr_fields = ("line1", "line2", "city", "state", "postal")
    provided = any((d.get(f) or "").strip() for f in addr_fields)
    if not provided:
        return []
    errs = []
    for field, label in (("line1", "street address"), ("city", "city"), ("state", "state"), ("postal", "ZIP code")):
        if not (d.get(field) or "").strip():
            errs.append(f"Delivery address is missing a {label}.")
    return errs


@router.post("/{po_id}/abc-submit-review")
async def abc_submit_review(po_id: str, payload: AbcSubmitReviewIn, request: Request,
                            user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """Validate the PO and run the MANDATORY fresh ABC pricing. Returns validation errors and any price
    changes for explicit user confirmation. Never submits. Optionally applies accepted price changes."""
    po = await db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.integration_provider != "abc_supply":
        raise HTTPException(status_code=400, detail="This purchase order is not an ABC Supply order")
    existing = (await db.execute(select(AbcOrderSubmission).where(
        AbcOrderSubmission.purchase_order_id == po.id, AbcOrderSubmission.status == "confirmed"))).scalars().first()
    already = bool(existing)
    errors, changes, abc_items, priced = await _validate_and_price(db, po, request, apply_changes=payload.apply_price_changes)
    await db.commit()
    await db.refresh(po)
    prev_total = round(sum((x.abc_price if x.abc_price is not None else x.unit_cost or 0) * 0 + (x.unit_cost or 0) * x.quantity for x in abc_items), 2)
    updated_total = round(sum((priced.get(str(x.id), {}).get("unit_price") or x.unit_cost or 0) * x.quantity for x in abc_items), 2)
    await log_action(db, user=user, action="abc.order.review", entity_type="purchase_order", entity_id=po.id,
                     detail={"errors": len(errors), "changes": len(changes)}, request=request)
    existing_sub = (await db.execute(select(AbcOrderSubmission).where(
        AbcOrderSubmission.purchase_order_id == po.id, AbcOrderSubmission.status.in_(["confirmed", "unknown"])))).scalars().first()
    delivery = (existing_sub.delivery if (existing_sub and existing_sub.delivery) else await _default_delivery(db, po))
    return {
        "ok": not errors,
        "already_submitted": already,
        "errors": errors,
        "price_changes": changes,
        "previous_total": prev_total,
        "updated_total": updated_total,
        "prices_verified_at": datetime.now(timezone.utc).isoformat(),
        "delivery": delivery,
        "review": {
            "po_number": po.number, "ship_to_number": po.abc_ship_to_number, "branch_number": po.abc_branch_number,
            "estimated_total": po.total,
            "lines": [{"abc_item_number": i.abc_item_number, "description": i.description, "quantity": i.quantity,
                       "uom": i.abc_uom, "unit_cost": i.unit_cost, "line_total": i.line_total} for i in abc_items],
        },
    }


@router.post("/{po_id}/abc-submit")
async def abc_submit(po_id: str, payload: AbcSubmitIn, request: Request,
                     user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """Submit the ABC-linked PO to ABC. Row-locks the PO (concurrency), re-runs mandatory pricing server-side,
    blocks on price changes unless accepted, is idempotent via submission_key, and preserves unknown states."""
    from integrations.abc_supply import orders as abc_orders
    from integrations.abc_supply.exceptions import AbcError, AbcTransportError

    # Lock the PO row so concurrent submissions serialize.
    po = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update())).scalars().first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.integration_provider != "abc_supply":
        raise HTTPException(status_code=400, detail="This purchase order is not an ABC Supply order")

    # Duplicate protection: only one confirmed submission per PO.
    confirmed = (await db.execute(select(AbcOrderSubmission).where(
        AbcOrderSubmission.purchase_order_id == po.id, AbcOrderSubmission.status == "confirmed"))).scalars().first()
    if confirmed:
        return {"status": "already_submitted", "confirmation_number": confirmed.abc_confirmation_number,
                "order_number": confirmed.abc_order_number}

    # Idempotency by submission_key.
    sub = (await db.execute(select(AbcOrderSubmission).where(AbcOrderSubmission.submission_key == payload.submission_key))).scalars().first()
    if sub:
        if sub.status == "confirmed":
            return {"status": "already_submitted", "confirmation_number": sub.abc_confirmation_number}
        if sub.status == "pending":
            return {"status": "pending", "message": "A submission is already in progress for this order."}
        if sub.status == "unknown":
            return {"status": "unknown", "message": "Submission status is unknown. Verify the ABC order before retrying."}
        # failed -> allow retry with same key

    # MANDATORY fresh pricing immediately before submit.
    errors, changes, abc_items, priced = await _validate_and_price(db, po, request, apply_changes=payload.accept_price_changes)
    # Physical delivery address: default from the job/property, overlaid with any reviewed override.
    delivery = _normalize_delivery({**(await _default_delivery(db, po)), **(payload.delivery or {})})
    errors = errors + _validate_delivery(delivery)
    if errors:
        await db.commit()
        return {"status": "validation_failed", "errors": errors}
    if changes and not payload.accept_price_changes:
        await db.commit()
        prev_total = round(sum((x.unit_cost or 0) * x.quantity for x in abc_items), 2)
        updated_total = round(sum((priced.get(str(x.id), {}).get("unit_price") or 0) * x.quantity for x in abc_items), 2)
        await log_action(db, user=user, action="abc.order.price_changed", entity_type="purchase_order", entity_id=po.id,
                         detail={"changes": len(changes)}, request=request)
        return {"status": "price_changed", "price_changes": changes, "previous_total": prev_total, "updated_total": updated_total}

    # Create the durable submission record (unique submission_key guards concurrent duplicates).
    if not sub:
        sub = AbcOrderSubmission(purchase_order_id=po.id, submission_key=payload.submission_key, status="pending",
                                 delivery=delivery, created_by=user.email,
                                 request_fingerprint=f"{po.id}:{len(abc_items)}:{po.total}")
        db.add(sub)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            existing = (await db.execute(select(AbcOrderSubmission).where(AbcOrderSubmission.submission_key == payload.submission_key))).scalars().first()
            return {"status": existing.status if existing else "pending", "confirmation_number": existing.abc_confirmation_number if existing else None}
    else:
        sub.status = "pending"
        sub.attempted_at = datetime.now(timezone.utc)
        sub.delivery = delivery
    await log_action(db, user=user, action="abc.order.delivery_override", entity_type="purchase_order", entity_id=po.id,
                     detail={"override": bool(payload.delivery)}, request=request)
    await log_action(db, user=user, action="abc.order.submit_attempt", entity_type="purchase_order", entity_id=po.id,
                     detail={"key": payload.submission_key, "lines": len(abc_items)}, request=request)

    # Build the ABC order payload.
    contacts = []
    if delivery.get("contact_name"):
        contacts.append({"name": delivery["contact_name"], "functionCode": "SM", "email": delivery.get("contact_email", ""),
                         "phones": [{"number": delivery.get("contact_phone", ""), "type": "MOBILE", "ext": ""}]})
    ship_to = {"number": po.abc_ship_to_number, "name": delivery.get("name") or po.number}
    if delivery.get("line1"):
        ship_to["address"] = {"line1": delivery.get("line1"), "line2": delivery.get("line2", ""), "line3": delivery.get("line3", ""),
                              "city": delivery.get("city", ""), "state": delivery.get("state", ""),
                              "postal": delivery.get("postal", ""), "country": delivery.get("country", "USA")}
    if contacts:
        ship_to["contacts"] = contacts
    order_lines = []
    for i in abc_items:
        length = i.abc_variation or {}
        order_lines.append(abc_orders.build_order_line(
            line_id=i.sort + 1, item_number=i.abc_item_number, item_description=i.abc_product_description or i.description,
            quantity=i.quantity, uom=i.abc_uom, unit_price=i.unit_cost, price_uom=i.abc_uom,
            length_value=length.get("value"), length_uom=length.get("uom")))
    order = {"requestId": payload.submission_key, "purchaseOrder": po.number[:20], "branchNumber": po.abc_branch_number,
             "deliveryService": payload.delivery_service, "typeCode": "SO", "currency": "USD", "shipTo": ship_to, "lines": order_lines}
    if delivery.get("requested_date"):
        order["dates"] = {"deliveryRequestedFor": delivery["requested_date"]}

    client, _ = await _abc_client(db, request)
    try:
        result = await abc_orders.place_order(client, order)
    except AbcTransportError:
        sub.status = "unknown"
        await db.commit()
        await log_action(db, user=user, action="abc.order.submit_unknown", entity_type="purchase_order", entity_id=po.id, request=request)
        return {"status": "unknown", "message": "ABC order submission status is unknown. Verify the ABC order before submitting again."}
    except AbcError as e:
        # 502/503/504 after sending are genuinely ambiguous -> unknown, not failed.
        if e.status in (502, 503, 504):
            sub.status = "unknown"
            await db.commit()
            await log_action(db, user=user, action="abc.order.submit_unknown", entity_type="purchase_order", entity_id=po.id, request=request)
            return {"status": "unknown", "message": "ABC order submission status is unknown. Verify the ABC order before submitting again."}
        sub.status = "failed"
        sub.last_error = e.user_message
        await db.commit()
        await log_action(db, user=user, action="abc.order.submit_failed", entity_type="purchase_order", entity_id=po.id,
                         detail={"message": e.user_message}, request=request)
        return {"status": "failed", "message": e.user_message}

    if not result.get("ok"):
        sub.status = "failed"
        sub.last_error = result.get("message")
        await db.commit()
        await log_action(db, user=user, action="abc.order.submit_failed", entity_type="purchase_order", entity_id=po.id,
                         detail={"message": result.get("message")}, request=request)
        return {"status": "failed", "message": result.get("message") or "ABC Supply did not accept this order."}

    now = datetime.now(timezone.utc)
    sub.status = "confirmed"
    sub.completed_at = now
    sub.abc_confirmation_number = result.get("confirmation_number")
    po.external_confirmation_number = result.get("confirmation_number")
    po.abc_order_status = "Submitted"
    po.abc_normalized_status = "processing"
    po.abc_submitted_at = now
    po.abc_last_sync_at = now
    po.status = "ordered"
    po.order_date = po.order_date or now
    # Register the minimal routing index so the Relay can map future ABC webhooks to this installation.
    from models import AbcOrderRoute
    import os as _os
    db.add(AbcOrderRoute(installation_id=_os.environ.get("ABC_INSTALLATION_ID", "install-local"),
                         abc_confirmation_number=sub.abc_confirmation_number, abc_order_number=None,
                         roofspan_po_number=po.number, purchase_order_id=po.id))
    await db.commit()
    await log_action(db, user=user, action="abc.order.submitted", entity_type="purchase_order", entity_id=po.id,
                     detail={"confirmation": sub.abc_confirmation_number}, request=request)
    return {"status": "confirmed", "confirmation_number": sub.abc_confirmation_number, "message": result.get("message")}


@router.post("/{po_id}/abc-refresh-status")
async def abc_refresh_status(po_id: str, request: Request,
                             user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    from integrations.abc_supply import orders as abc_orders
    from integrations.abc_supply.exceptions import AbcError
    po = await db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if not po.external_confirmation_number:
        raise HTTPException(status_code=400, detail="This purchase order has no ABC confirmation to look up")
    client, _ = await _abc_client(db, request)
    try:
        detail = await abc_orders.get_order_by_confirmation(client, po.external_confirmation_number)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    po.abc_order_status = detail.get("abc_status") or po.abc_order_status
    po.abc_normalized_status = detail.get("normalized_status") or po.abc_normalized_status
    po.external_order_number = detail.get("order_number") or po.external_order_number
    po.abc_last_sync_at = datetime.now(timezone.utc)
    await db.commit()
    await log_action(db, user=user, action="abc.order.status_refresh", entity_type="purchase_order", entity_id=po.id,
                     detail={"status": po.abc_order_status}, request=request)
    return {"po_id": str(po.id), "abc_status": po.abc_order_status, "normalized_status": po.abc_normalized_status,
            "order_number": po.external_order_number, "detail": detail}


@router.post("/{po_id}/abc-reconcile")
async def abc_reconcile(po_id: str, request: Request,
                        user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """Reconcile an unknown submission: look up ABC order history for an order carrying this PO number."""
    from integrations.abc_supply import orders as abc_orders
    from integrations.abc_supply.exceptions import AbcError
    po = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update())).scalars().first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    sub = (await db.execute(select(AbcOrderSubmission).where(
        AbcOrderSubmission.purchase_order_id == po.id, AbcOrderSubmission.status == "unknown"))).scalars().first()
    client, _ = await _abc_client(db, request)
    try:
        history = await abc_orders.get_order_history(client, ship_to=po.abc_ship_to_number, branch=po.abc_branch_number)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    match = next((o for o in history if str(o.get("purchaseOrder")) == po.number), None)
    await log_action(db, user=user, action="abc.order.reconcile", entity_type="purchase_order", entity_id=po.id,
                     detail={"found": bool(match)}, request=request)
    if not match:
        await db.commit()
        return {"status": "not_found", "message": "No matching ABC order was found yet. Try again later."}
    now = datetime.now(timezone.utc)
    if sub:
        sub.status = "confirmed"
        sub.completed_at = now
        sub.abc_confirmation_number = match.get("confirmationNumber")
        sub.abc_order_number = match.get("orderNumber")
    po.external_confirmation_number = match.get("confirmationNumber")
    po.external_order_number = match.get("orderNumber")
    po.abc_order_status = match.get("status") or "Submitted"
    po.abc_normalized_status = abc_orders.normalize_status(match.get("status"))
    po.abc_submitted_at = po.abc_submitted_at or now
    po.abc_last_sync_at = now
    if po.status == "draft":
        po.status = "ordered"
        po.order_date = po.order_date or now
    await db.commit()
    return {"status": "reconciled", "confirmation_number": po.external_confirmation_number, "order_number": po.external_order_number}


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
