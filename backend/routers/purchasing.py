from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import PurchaseOrder, POLineItem, Supplier, Material, InventoryTxn, IdempotencyKey, User, AbcOrderSubmission, PurchaseOrderStatusHistory, AbcCatalogItem


async def record_status(db: AsyncSession, po: PurchaseOrder, normalized: str, *, provider: str | None = None,
                        source: str = "roofspan", note: str | None = None, user_email: str | None = None):
    """Append a status event ONLY when the normalized status meaningfully changes (no duplicate events
    from repeated syncs). Raw provider status is stored separately."""
    if not normalized:
        return
    last = (await db.execute(select(PurchaseOrderStatusHistory).where(
        PurchaseOrderStatusHistory.purchase_order_id == po.id)
        .order_by(PurchaseOrderStatusHistory.created_at.desc()).limit(1))).scalars().first()
    if last and last.normalized_status == normalized and (last.provider_status or None) == (provider or None):
        return
    db.add(PurchaseOrderStatusHistory(purchase_order_id=po.id, normalized_status=normalized,
                                      provider_status=provider, source=source, note=note, created_by=user_email))
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_phase4 import POIn, POStatusIn, ReceiveIn, POOut, POLineOut, RefreshPriceIn, RefreshPriceOut, AbcSubmitReviewIn, AbcSubmitIn, AbcTemplateConvertIn
from sales_common import next_number

router = APIRouter(prefix="/api/purchase-orders", tags=["purchasing"])
# Normalized RoofSpan PO lifecycle (Slice 11). ABC raw provider status is preserved separately
# in po.abc_order_status / po.abc_normalized_status and is never overwritten by these.
VALID = ["draft", "ready_for_review", "ordered", "submitted", "acknowledged", "scheduled",
         "partially_received", "received", "backordered", "cancelled"]


@router.get("/abc/delivery-services")
async def abc_delivery_services(user: User = Depends(get_current_user)):
    """ABC `deliveryService` enum — single source of truth so the UI and backend cannot drift.
    Availability varies by branch (verify via the Locations API) and is subject to change."""
    from integrations.abc_supply import orders as abc_orders
    return {"services": abc_orders.DELIVERY_SERVICES, "default": abc_orders.DEFAULT_DELIVERY_SERVICE}




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
    supplier = None
    if payload.supplier_id:
        supplier = await db.get(Supplier, payload.supplier_id)
        if not supplier:
            raise HTTPException(status_code=404, detail="Supplier not found")
    if supplier is None:
        supplier = await _find_or_create_supplier(db, payload.supplier_name)
    number = await next_number(db, "po", "PO")
    total = round(sum((it.quantity or 0) * (it.unit_cost or 0) for it in payload.items), 2)

    # ABC identity resolution (server-side): an ABC PO is only useful if EVERY line carries its ABC
    # catalog identity (item number + UOM) and the PO has a Ship-To + branch. Reorder Suggestions only
    # sends general material info, so resolve each material's ABC mapping (Material.abc_* -> AbcCatalogItem)
    # and apply the integration's default Ship-To/branch. If anything required is missing we DO NOT create
    # an unsubmittable ABC PO — we fall back to a standard draft and flag exactly what needs fixing.
    is_abc_request = payload.integration_provider == "abc_supply"
    provider = payload.integration_provider
    po_ship_to = payload.abc_ship_to_number
    po_branch = payload.abc_branch_number
    line_abc: list[dict | None] = [None] * len(payload.items)
    abc_setup_warning = None
    if is_abc_request:
        from routers import abc_supply as abc_router
        row = await abc_router._get_or_create(db)
        po_ship_to = po_ship_to or row.default_ship_to_number
        po_branch = po_branch or row.default_branch_number
        unresolved = []
        for idx, it in enumerate(payload.items):
            item_no = (it.abc_item_number or "").strip() or None
            uom, pdesc, pfamily, pimg = it.abc_uom, it.abc_product_description, it.abc_product_family, it.abc_product_image_url
            if not item_no and it.material_id:
                m = await db.get(Material, it.material_id)
                if m and m.abc_item_number:
                    item_no, uom = m.abc_item_number, (uom or m.abc_uom)
                if not item_no and m:
                    cat = (await db.execute(select(AbcCatalogItem).where(AbcCatalogItem.material_id == m.id))).scalars().first()
                    if cat:
                        item_no = cat.abc_item_number
                        uom = uom or cat.unit_of_measure
                        pdesc = pdesc or cat.description
                        pfamily = pfamily or cat.family_name
                        pimg = pimg or cat.image_url
            if item_no:
                line_abc[idx] = {"abc_item_number": item_no, "abc_uom": uom or it.unit,
                                 "abc_product_description": pdesc, "abc_product_family": pfamily,
                                 "abc_product_image_url": pimg}
            else:
                unresolved.append((it.description or "an item").strip() or "an item")
        missing = []
        if unresolved:
            shown = ", ".join(unresolved[:4]) + ("…" if len(unresolved) > 4 else "")
            missing.append(f"{len(unresolved)} item(s) have no ABC Supply catalog mapping ({shown})")
        if not po_ship_to or not po_branch:
            missing.append("the ABC default Ship-To and branch are not set (configure them in Settings → ABC Supply)")
        if missing:
            abc_setup_warning = "Created as a standard draft PO — cannot order from ABC Supply yet because " + "; ".join(missing) + "."
            provider, po_ship_to, po_branch = None, None, None
            line_abc = [None] * len(payload.items)

    po = PurchaseOrder(number=number, supplier_id=supplier.id if supplier else None, job_id=payload.job_id,
                       status="draft", expected_date=payload.expected_date, total=total, notes=payload.notes, created_by=user.email,
                       integration_provider=provider,
                       abc_ship_to_number=po_ship_to, abc_branch_number=po_branch)
    db.add(po)
    await db.flush()
    for idx, it in enumerate(payload.items):
        desc = it.description
        if not desc and it.material_id:
            m = await db.get(Material, it.material_id)
            desc = m.name if m else ""
        line_total = round((it.quantity or 0) * (it.unit_cost or 0), 2)
        abc = line_abc[idx]
        if provider == "abc_supply" and abc:
            db.add(POLineItem(po_id=po.id, material_id=it.material_id, description=desc, quantity=it.quantity,
                              unit=it.unit, unit_cost=it.unit_cost, line_total=line_total, sort=idx,
                              integration_provider="abc_supply", abc_item_number=abc["abc_item_number"],
                              abc_branch_number=po_branch, abc_ship_to_number=po_ship_to, abc_uom=abc["abc_uom"],
                              abc_variation=it.abc_variation, abc_price=it.abc_price,
                              abc_price_status=it.abc_price_status or "unavailable",
                              abc_price_timestamp=(datetime.now(timezone.utc) if it.abc_price is not None else None),
                              abc_product_description=abc["abc_product_description"], abc_product_family=abc["abc_product_family"],
                              abc_product_image_url=abc["abc_product_image_url"], pricing_source="abc"))
        elif is_abc_request:
            # ABC PO was downgraded to a standard draft — never carry a partial ABC identity.
            db.add(POLineItem(po_id=po.id, material_id=it.material_id, description=desc, quantity=it.quantity,
                              unit=it.unit, unit_cost=it.unit_cost, line_total=line_total, sort=idx,
                              integration_provider=None))
        else:
            db.add(POLineItem(po_id=po.id, material_id=it.material_id, description=desc, quantity=it.quantity,
                              unit=it.unit, unit_cost=it.unit_cost, line_total=line_total, sort=idx,
                              integration_provider=it.integration_provider, abc_item_number=it.abc_item_number,
                              abc_branch_number=it.abc_branch_number, abc_ship_to_number=it.abc_ship_to_number,
                              abc_uom=it.abc_uom, abc_variation=it.abc_variation, abc_price=it.abc_price,
                              abc_price_status=it.abc_price_status,
                              abc_price_timestamp=(datetime.now(timezone.utc) if it.abc_price is not None else None),
                              abc_product_description=it.abc_product_description, abc_product_family=it.abc_product_family,
                              abc_product_image_url=it.abc_product_image_url,
                              pricing_source=it.pricing_source or ("abc" if it.abc_item_number else None)))
    note = "PO created" if not abc_setup_warning else "PO created as standard draft (ABC mapping/config incomplete)"
    await record_status(db, po, "draft", source="roofspan", note=note, user_email=user.email)
    await db.commit()
    await db.refresh(po)
    await log_action(db, user=user, action="po.create", entity_type="purchase_order", entity_id=po.id,
                     detail={"number": number, "total": total, "abc_setup_warning": abc_setup_warning}, request=request)
    result = await _out(db, po)
    result.abc_setup_warning = abc_setup_warning
    return result


@router.post("/from-abc-template", response_model=POOut, status_code=201)
async def create_po_from_abc_template(payload: AbcTemplateConvertIn, request: Request,
                                      user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """Convert an ABC order template into a NORMAL RoofSpan draft purchase order. This NEVER submits to
    ABC — it only creates an editable RoofSpan PO. Template prices are copied as an initial estimate;
    the mandatory fresh ABC pricing still runs at submit review/submit time."""
    from routers import abc_supply as abc_router
    from integrations.abc_supply import orders as abc_orders
    from integrations.abc_supply.exceptions import AbcError

    row = await abc_router._get_or_create(db)
    ship_to = payload.ship_to_number or row.default_ship_to_number
    branch = payload.branch_number or row.default_branch_number
    if not ship_to or not branch:
        raise HTTPException(status_code=400, detail="A default ABC Ship-To and branch are required (set them in Settings → ABC Supply, or pass them explicitly).")

    client, _ = await _abc_client(db, request)
    try:
        raw = await abc_orders.get_template(client, payload.template_id)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    tpl = abc_orders.normalize_template(raw)
    tpl_lines = [l for l in tpl["lines"] if l.get("item_number")]
    if not tpl_lines:
        raise HTTPException(status_code=400, detail="This ABC template has no orderable line items.")

    supplier = (await db.execute(select(Supplier).where(Supplier.integration_provider == "abc_supply"))).scalars().first()
    if not supplier:
        supplier = await _find_or_create_supplier(db, "ABC Supply")

    number = await next_number(db, "po", "PO")
    po = PurchaseOrder(number=number, supplier_id=supplier.id if supplier else None, job_id=payload.job_id,
                       status="draft", total=0, notes=payload.notes or f"From ABC template: {tpl['name'] or payload.template_id}",
                       created_by=user.email, integration_provider="abc_supply",
                       abc_ship_to_number=ship_to, abc_branch_number=branch)
    db.add(po)
    await db.flush()
    total = 0.0
    for idx, l in enumerate(tpl_lines):
        qty = float(l.get("quantity") or 1)
        est = float(l.get("unit_price") or 0)
        # Template price is only an initial estimate — fresh ABC pricing is mandatory before submit,
        # so the line is marked unavailable until the mandatory pricing check runs.
        db.add(POLineItem(po_id=po.id, material_id=None, description=l.get("description") or l.get("item_number"),
                          quantity=qty, unit=l.get("uom") or "each", unit_cost=est,
                          line_total=round(qty * est, 2), sort=idx,
                          integration_provider="abc_supply", abc_item_number=l.get("item_number"),
                          abc_branch_number=branch, abc_ship_to_number=ship_to, abc_uom=l.get("uom"),
                          abc_price=None, abc_price_status="unavailable",
                          abc_product_description=l.get("description"), pricing_source="abc_template"))
        total += qty * est
    po.total = round(total, 2)
    await record_status(db, po, "draft", source="roofspan", note=f"Created from ABC template {payload.template_id}", user_email=user.email)
    await db.commit()
    await db.refresh(po)
    await log_action(db, user=user, action="abc.template.convert", entity_type="purchase_order", entity_id=po.id,
                     detail={"template_id": payload.template_id, "lines": len(tpl_lines)}, request=request)
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
    result = await abc_pricing.price_items(client, ship_to_number=ship_to, branch_number=branch, lines=plines, purpose="ordering", request_id=po.number)
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
    # Strict ABC order limits (documented): PO reference field ≤ 20 chars; ≤ 99 order lines.
    from integrations.abc_supply.orders import MAX_ORDER_LINES, PO_FIELD_MAX
    if len(abc_items) > MAX_ORDER_LINES:
        errors.append(f"ABC Supply orders are limited to {MAX_ORDER_LINES} lines; this order has {len(abc_items)}.")
    if po.number and len(po.number) > PO_FIELD_MAX:
        errors.append(f"The PO number '{po.number}' exceeds ABC's {PO_FIELD_MAX}-character limit.")
    for i in abc_items:
        if not i.abc_uom:
            errors.append(f"Line '{i.description}' is missing a unit of measure.")
        if (i.abc_variation is None or not (i.abc_variation or {}).get("value")) and _is_dimensional(i):
            errors.append(f"Line '{i.description}' requires a length/variation.")
        if i.quantity is None or float(i.quantity) <= 0 or not float(i.quantity).is_integer():
            errors.append(f"Line '{i.description}' needs a whole-number quantity for ABC Supply pricing.")

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
                                                    branch_number=po.abc_branch_number, lines=plines,
                                                    purpose="ordering", request_id=po.number)
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
        "contact_email": d.get("contact_email"),
        "instructions": d.get("instructions"), "requested_date": d.get("requested_date"),
        # ABC deliveryAppointment: instructionsTypeCode + optional structured From/To military times.
        "appointment_type": d.get("appointment_type"),
        "appointment_from": d.get("appointment_from"),
        "appointment_to": d.get("appointment_to"),
    }.items()}


# ABC deliveryAppointment.instructionsTypeCode values (source: apidocs.abcsupply.com/place-orders).
# AT = Anytime, AM = Morning, PM = Afternoon, FS = First Stop, ST = Specific Time, TR = Time Range.
_APPT_TYPE_CODES = {"AT", "AM", "PM", "FS", "ST", "TR"}


def _validate_appointment(d: dict) -> list[str]:
    """Validate the ABC delivery appointment window. fromTime applies to ST/TR; toTime only to TR."""
    code = (d.get("appointment_type") or "").strip().upper()
    if not code:
        return []
    if code not in _APPT_TYPE_CODES:
        return [f"Delivery appointment type '{code}' is not a valid ABC code (AT, AM, PM, FS, ST, TR)."]
    errs = []
    if code in ("ST", "TR") and not (d.get("appointment_from") or "").strip():
        errs.append("A From time is required for the selected delivery appointment type.")
    if code == "TR" and not (d.get("appointment_to") or "").strip():
        errs.append("A To time is required for a time-range delivery appointment.")
    return errs


async def _abc_orderability_preflight(db: AsyncSession, request: Request, po: PurchaseOrder) -> list[str]:
    """Revalidate ABC account + branch orderability immediately before submit (a PO can sit for days).
    Checks: Ship-To still exists; account is orderable (isSellable — false == credit hold); status active;
    the selected branch is still associated with the Ship-To and active. Product-at-branch suitability is
    already enforced by the mandatory fresh pricing (unavailable lines block submit). Read-only, best-effort:
    a hard transport failure surfaces as a clear retry message rather than a silent pass."""
    from integrations.abc_supply import accounts as abc_accounts, locations as abc_locations
    from integrations.abc_supply.exceptions import AbcError, AbcTransportError
    if not po.abc_ship_to_number or not po.abc_branch_number:
        return ["This ABC order is missing a Ship-To or branch. Re-create it so RoofSpan can resolve the ABC defaults."]
    try:
        client, _ = await _abc_client(db, request)
        ship_to = await abc_accounts.get_ship_to(client, po.abc_ship_to_number)
    except (AbcError, AbcTransportError):
        return [f"Could not verify the ABC Ship-To {po.abc_ship_to_number} with ABC just now — try submitting again shortly."]
    if not isinstance(ship_to, dict) or not ship_to.get("number"):
        return [f"ABC Ship-To {po.abc_ship_to_number} no longer exists at ABC. Choose a current Ship-To."]
    errs = []
    status = str(ship_to.get("status") or "").strip().lower()
    if status and status not in ("active", "open"):
        errs.append(f"ABC Ship-To {po.abc_ship_to_number} is {status} and cannot place orders.")
    if ship_to.get("isSellable") is False:
        errs.append(f"ABC Ship-To {po.abc_ship_to_number} is on credit hold (not sellable) and cannot place orders — contact ABC.")
    branches = ship_to.get("branches") or []
    entry = next((b for b in branches if str(b.get("number")) == str(po.abc_branch_number)), None)
    branch_status = None
    if entry:
        branch_status = str(entry.get("status") or "").strip().lower()
    elif branches:
        errs.append(f"Branch {po.abc_branch_number} is no longer associated with ABC Ship-To {po.abc_ship_to_number}.")
    if branch_status is None:
        try:
            b = await abc_locations.get_branch(client, po.abc_branch_number)
            branch_status = str((b.get("branch") or {}).get("status") or "").strip().lower()
        except (AbcError, AbcTransportError):
            branch_status = None
    if branch_status and branch_status not in ("active", "open"):
        errs.append(f"ABC branch {po.abc_branch_number} is {branch_status} and not available for ordering.")
    return errs


def _build_delivery_appointment(d: dict) -> tuple[dict | None, str | None]:
    """Build the ABC `deliveryAppointment` object from the normalized delivery override.
    Returns (appointment | None, overflow_instructions | None). ABC caps
    deliveryAppointment.instructions at 255 chars, so anything beyond 255 is returned as
    overflow for the caller to route into orderComments (never silently dropped). Times are
    local military time (e.g. 13:00); fromTime is sent for ST/TR, toTime only for TR."""
    code = (d.get("appointment_type") or "").strip().upper()
    instructions = (d.get("instructions") or "").strip()
    if not code and not instructions:
        return None, None
    if not code:
        code = "AT"  # instructions with no explicit window -> Anytime delivery.
    appt: dict = {"instructionsTypeCode": code}
    overflow = None
    if instructions:
        appt["instructions"] = instructions[:255]
        if len(instructions) > 255:
            overflow = instructions[255:]
    if code in ("ST", "TR") and (d.get("appointment_from") or "").strip():
        appt["fromTime"] = d["appointment_from"].strip()
    if code == "TR" and (d.get("appointment_to") or "").strip():
        appt["toTime"] = d["appointment_to"].strip()
    return appt, overflow


def _validate_delivery(d: dict) -> list[str]:
    """Validate the PHYSICAL delivery override + the delivery appointment. The address override is
    optional: when no address fields are supplied the order falls back to the ABC Ship-To account's
    registered delivery address (the submit builder omits ship_to.address). Only when the user provides
    a partial address do we require the full set so we never send ABC an incomplete override."""
    errs = []
    addr_fields = ("line1", "line2", "city", "state", "postal")
    if any((d.get(f) or "").strip() for f in addr_fields):
        for field, label in (("line1", "street address"), ("city", "city"), ("state", "state"), ("postal", "ZIP code")):
            if not (d.get(field) or "").strip():
                errs.append(f"Delivery address is missing a {label}.")
    errs += _validate_appointment(d)
    return errs


@router.post("/{po_id}/abc-refresh-all-prices")
async def abc_refresh_all_prices(po_id: str, payload: AbcSubmitReviewIn, request: Request,
                                 user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """Bulk-refresh live ABC pricing for every ABC line on the PO in a single user action. Lines are
    batched (≤50/request) inside price_items and reconciled by stable line id. Optionally applies the
    refreshed prices (never auto-submits). Purpose=ordering."""
    po = await db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.integration_provider != "abc_supply":
        raise HTTPException(status_code=400, detail="This purchase order is not an ABC Supply order")
    errors, changes, abc_items, priced = await _validate_and_price(db, po, request, apply_changes=payload.apply_price_changes)
    await db.commit()
    await db.refresh(po)
    lines = []
    for i in abc_items:
        r = priced.get(str(i.id)) or {}
        lines.append({"po_item_id": str(i.id), "abc_item_number": i.abc_item_number, "description": i.description,
                      "quantity": i.quantity, "uom": i.abc_uom,
                      "unit_price": r.get("unit_price"), "price_status": r.get("price_status") or i.abc_price_status,
                      "currency_symbol": r.get("currency_symbol", "$"), "status_message": r.get("status_message"),
                      "request_id": r.get("request_id")})
    await log_action(db, user=user, action="abc.price.refresh", entity_type="purchase_order", entity_id=po.id,
                     detail={"lines": len(abc_items), "applied": payload.apply_price_changes, "changes": len(changes)}, request=request)
    return {"ok": not errors, "errors": errors, "price_changes": changes, "applied": payload.apply_price_changes,
            "lines": lines, "estimated_total": po.total, "prices_verified_at": datetime.now(timezone.utc).isoformat()}


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
                       "uom": i.abc_uom, "unit_cost": i.unit_cost, "line_total": i.line_total,
                       "price_status": (priced.get(str(i.id), {}) or {}).get("price_status") or i.abc_price_status,
                       "status_message": (priced.get(str(i.id), {}) or {}).get("status_message")} for i in abc_items],
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
    if not abc_orders.is_valid_delivery_service(payload.delivery_service):
        errors = errors + [f"Delivery service '{payload.delivery_service}' is not a valid ABC code."]
    # Server-side orderability preflight against ABC, run immediately before submit (a PO can sit for
    # days). Confirms the Ship-To still exists + is sellable (not on credit hold), and the selected
    # branch is still associated + active. Never trusts stale UI data.
    errors = errors + await _abc_orderability_preflight(db, request, po)
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
    line_comments = payload.line_comments or {}
    for i in abc_items:
        length = i.abc_variation or {}
        ol = abc_orders.build_order_line(
            line_id=i.sort + 1, item_number=i.abc_item_number, item_description=i.abc_product_description or i.description,
            quantity=i.quantity, uom=i.abc_uom, unit_price=i.unit_cost, price_uom=i.abc_uom,
            length_value=length.get("value"), length_uom=length.get("uom"))
        lc = (line_comments.get(str(i.id)) or "").strip()
        if lc:
            # ABC contract: a line-item comment is a single {code, description} object ("D" = detail comment).
            ol["comments"] = {"code": "D", "description": lc[:500]}
        order_lines.append(ol)
    order = {"requestId": payload.submission_key, "purchaseOrder": po.number, "branchNumber": po.abc_branch_number,
             "deliveryService": payload.delivery_service, "typeCode": "SO", "currency": "USD", "shipTo": ship_to, "lines": order_lines}
    dates = {}
    if delivery.get("requested_date"):
        dates["deliveryRequestedFor"] = delivery["requested_date"]
    if dates:
        order["dates"] = dates
    # ABC contract: the time window + delivery instructions live in a separate `deliveryAppointment`
    # object (NOT dates.deliveryAppointmentTime). Instructions over ABC's 255-char limit overflow into
    # orderComments so a long delivery note is never lost.
    appointment, instr_overflow = _build_delivery_appointment(delivery)
    if appointment:
        order["deliveryAppointment"] = appointment
    # ABC contract: order-level comments are an array of {code, description} objects.
    order_comments = []
    if (payload.order_comments or "").strip():
        # "H" = header comment (the RoofSpan order-level note).
        order_comments.append({"code": "H", "description": payload.order_comments.strip()[:1000]})
    if instr_overflow:
        # "D" = detail comment carrying the remainder of a >255-char delivery instruction.
        order_comments.append({"code": "D", "description": ("Delivery instructions (continued): " + instr_overflow)[:1000]})
    if order_comments:
        order["orderComments"] = order_comments

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
    await record_status(db, po, "ordered", provider=po.abc_order_status, source="abc", note="Submitted to ABC", user_email=user.email)
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
    # Map ABC's normalized state onto a RoofSpan PO status where sensible, and record the event.
    _abc_to_po = {"delivered": "received", "invoiced": "received", "shipped": "scheduled",
                  "scheduled": "scheduled", "acknowledged": "acknowledged", "cancelled": "cancelled"}
    mapped = _abc_to_po.get((po.abc_normalized_status or "").lower())
    if mapped and po.status not in ("received", "partially_received", "cancelled"):
        po.status = mapped
    await record_status(db, po, po.status, provider=po.abc_order_status, source="abc", note="ABC status refresh", user_email=user.email)
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
    # Search ABC order history over a window around the attempted submission (documented
    # /orders/orderHistory has no purchaseOrder field, so fetch each candidate's detail and
    # match on the strong RoofSpan purchaseOrder identifier). Never guess; never resubmit.
    anchor = (sub.attempted_at if sub and sub.attempted_at else po.abc_submitted_at) or datetime.now(timezone.utc)
    start = (anchor - timedelta(days=3)).strftime("%Y-%m-%d")
    end = (anchor + timedelta(days=3)).strftime("%Y-%m-%d")
    match = None
    try:
        page, items_per_page = 1, 50
        while page <= 20 and match is None:
            hist = await abc_orders.get_order_history(
                client, start_date=start, end_date=end, page_number=page, items_per_page=items_per_page)
            items = hist.get("items") or []
            for it in items:
                onum = it.get("orderNumber")
                if not onum:
                    continue
                try:
                    detail = await abc_orders.get_order_by_number(client, str(onum))
                except Exception:
                    continue
                # get_order_by_number returns a NORMALIZED order (snake_case keys).
                if isinstance(detail, dict) and str(detail.get("purchase_order")) == po.number:
                    match = {"confirmationNumber": detail.get("confirmation_number"),
                             "orderNumber": detail.get("order_number") or onum,
                             "status": detail.get("abc_status")}
                    break
            pag = hist.get("pagination") or {}
            if page >= (pag.get("totalPages") or page):
                break
            page += 1
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
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
    # SAFETY: a confirmed ABC Supply order cannot be locally "cancelled" — ABC publishes NO order
    # cancellation API, so a local cancel would falsely imply the ABC order stopped while ABC is still
    # processing/delivering it. Keep the ABC status authoritative and direct the user to the branch.
    if payload.status == "cancelled" and po.integration_provider == "abc_supply" and po.external_confirmation_number:
        raise HTTPException(status_code=409, detail=(
            f"This ABC Supply order is confirmed (#{po.external_confirmation_number}). ABC provides no "
            "cancellation API, so RoofSpan cannot cancel it — contact the ABC branch to cancel or change "
            "the order. The ABC order status remains authoritative."))
    if payload.status == "ordered" and not po.order_date:
        po.order_date = datetime.now(timezone.utc)
    po.status = payload.status
    await record_status(db, po, payload.status, source="roofspan", user_email=user.email)
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

    from services import inventory_ops as ops
    recv_loc_id = payload.location_id
    if not recv_loc_id:
        dl = await ops.default_location(db)
        recv_loc_id = dl.id if dl else None
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
                # MWAC: fold this receipt's exact unit cost into the moving average BEFORE adding qty.
                uc, ext = ops.record_receipt_cost(m, line.quantity, item.unit_cost)
                if recv_loc_id:
                    await ops.add_at_location(db, m, recv_loc_id, line.quantity)  # updates balance + company On Hand once
                else:
                    m.quantity_on_hand = round(m.quantity_on_hand + line.quantity, 3)
                db.add(InventoryTxn(material_id=m.id, delta=line.quantity, reason="receipt", po_id=po.id,
                                    destination_location_id=recv_loc_id, unit_cost=uc, extended_cost=ext,
                                    created_by=user.email))

    items = (await db.execute(select(POLineItem).where(POLineItem.po_id == po.id))).scalars().all()
    fully = all(i.received_quantity >= i.quantity - 1e-9 for i in items)
    any_recv = any(i.received_quantity > 0 for i in items)
    po.status = "received" if fully else ("partially_received" if any_recv else po.status)
    await record_status(db, po, po.status, source="roofspan", note="Receiving", user_email=user.email)
    await db.commit()
    await db.refresh(po)
    await log_action(db, user=user, action="po.receive", entity_type="purchase_order", entity_id=po.id, detail={"status": po.status, "lines": len(payload.items)}, request=request)
    return await _out(db, po)


@router.get("/{po_id}/status-history")
async def status_history(po_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    po = await db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    rows = (await db.execute(select(PurchaseOrderStatusHistory).where(
        PurchaseOrderStatusHistory.purchase_order_id == po.id)
        .order_by(PurchaseOrderStatusHistory.created_at.asc()))).scalars().all()
    return {"events": [{
        "id": str(r.id), "normalized_status": r.normalized_status, "provider_status": r.provider_status,
        "source": r.source, "note": r.note, "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}
