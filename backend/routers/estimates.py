from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Estimate, EstimateLineItem, Material, Supplier, SupplierMaterial, Quote, User
from core import get_current_user, require_roles, FIELD_ROLES, MANAGE_ROLES, log_action
from schemas_phase3 import EstimateIn, EstimateOut, LineItemOut
from schemas_estimating import CostRefreshPreviewOut, CostRefreshRow, CostRefreshApplyIn
from sales_common import next_number, check_idempotency, record_idempotency, enforce_version
from services import estimating as calc
from services import inventory_core as inv_core
from services import pricing as pricing_svc

router = APIRouter(prefix="/api/estimates", tags=["estimates"])

COST_ROLES = MANAGE_ROLES  # owner/administrator/office — sales sees selling price only


def _can_see_cost(user: User) -> bool:
    return user.role in COST_ROLES


def _line_out(i: EstimateLineItem, see_cost: bool) -> LineItemOut:
    ucost = calc.unit_cost(i.material_cost, i.labor_cost, i.equipment_cost, i.subcontract_cost)
    data = dict(
        id=str(i.id), description=i.description, quantity=i.quantity, unit=i.unit,
        unit_price=i.unit_price, line_total=i.line_total,
        material_id=str(i.material_id) if i.material_id else None,
        supplier_material_id=str(i.supplier_material_id) if i.supplier_material_id else None,
        line_kind=i.line_kind, measured_quantity=i.measured_quantity, waste_percent=i.waste_percent,
        order_quantity=i.order_quantity, purchase_unit=i.purchase_unit, conversion_factor=i.conversion_factor,
        selling_unit_price=i.selling_unit_price,
        assembly_id=str(i.assembly_id) if i.assembly_id else None,
        assembly_version=i.assembly_version, assembly_name=i.assembly_name,
    )
    if see_cost:
        data.update(
            base_cost=i.base_cost, material_cost=i.material_cost, labor_cost=i.labor_cost,
            equipment_cost=i.equipment_cost, subcontract_cost=i.subcontract_cost,
            unit_cost=ucost, extended_cost=calc.r2(i.quantity * ucost), markup_percent=i.markup_percent,
            cost_source_supplier_id=str(i.cost_source_supplier_id) if i.cost_source_supplier_id else None,
            cost_source_supplier_name=i.cost_source_supplier_name, supplier_item_number=i.supplier_item_number,
            cost_source=i.cost_source, cost_snapshot_at=i.cost_snapshot_at,
        )
    return LineItemOut(**data)


async def _margin_policy(db: AsyncSession) -> dict:
    from models import AppConfig
    row = (await db.execute(select(AppConfig).where(AppConfig.key == "margin_policy"))).scalar_one_or_none()
    val = row.value if row and isinstance(row.value, dict) else {}
    return {"enabled": bool(val.get("enabled", False)), "target_minimum_margin": float(val.get("target_minimum_margin", 30.0))}


async def _out(db: AsyncSession, e: Estimate, user: User) -> EstimateOut:
    items = (await db.execute(select(EstimateLineItem).where(EstimateLineItem.estimate_id == e.id).order_by(EstimateLineItem.sort))).scalars().all()
    see = _can_see_cost(user)
    summary = None
    warnings = None
    if see:
        line_dicts = [{
            "quantity": i.quantity, "material_cost": i.material_cost, "labor_cost": i.labor_cost,
            "equipment_cost": i.equipment_cost, "subcontract_cost": i.subcontract_cost,
            "line_total": i.line_total,
            "_unit_cost": calc.unit_cost(i.material_cost, i.labor_cost, i.equipment_cost, i.subcontract_cost),
        } for i in items]
        summary = calc.summarize(line_dicts, e.tax_rate)
        # Margin guardrail (warning only; NEVER on customer output; never blocks anything)
        policy = await _margin_policy(db)
        if policy["enabled"]:
            target = policy["target_minimum_margin"]
            below_lines = []
            for i in items:
                uc = calc.unit_cost(i.material_cost, i.labor_cost, i.equipment_cost, i.subcontract_cost)
                m = calc.margin_from_prices(uc, i.selling_unit_price)
                if i.selling_unit_price and m < target:
                    below_lines.append({"line_id": str(i.id), "description": i.description, "margin_percent": m})
            overall = summary.get("gross_margin_pct", 0)
            warnings = {"enabled": True, "target_minimum_margin": target,
                        "overall_margin_percent": overall, "overall_below": overall < target,
                        "below_lines": below_lines}
    return EstimateOut(
        id=str(e.id), number=e.number, lead_id=str(e.lead_id) if e.lead_id else None,
        customer_id=str(e.customer_id) if e.customer_id else None,
        property_id=str(e.property_id) if e.property_id else None,
        inspection_id=str(e.inspection_id) if e.inspection_id else None,
        status=e.status, tax_rate=e.tax_rate, subtotal=e.subtotal, tax=e.tax, total=e.total,
        notes=e.notes, version=e.version, price_book_id=str(e.price_book_id) if e.price_book_id else None,
        created_at=e.created_at,
        items=[_line_out(i, see) for i in items], cost_summary=summary, can_see_cost=see,
        margin_warnings=warnings,
    )


async def _snapshot_cost(db: AsyncSession, d: dict):
    """Populate base_cost + supplier provenance from the linked SupplierMaterial/Material.
    Never mutates the material's preferred supplier."""
    sm = None
    if d.get("supplier_material_id"):
        sm = await db.get(SupplierMaterial, d["supplier_material_id"])
    elif d.get("material_id"):
        sm = await inv_core.preferred_supplier_material(db, d["material_id"]) \
            or await inv_core.best_known_supplier_material(db, d["material_id"])
    if not sm:
        return
    d["supplier_material_id"] = str(sm.id)
    if d.get("base_cost") in (None, ""):
        d["base_cost"] = sm.current_cost or 0
    if d.get("material_cost") in (None, ""):
        d["material_cost"] = d["base_cost"]
    if sm.supplier_id:
        s = await db.get(Supplier, sm.supplier_id)
        d["cost_source_supplier_id"] = str(sm.supplier_id)
        d["cost_source_supplier_name"] = s.name if s else None
        d.setdefault("cost_source", sm.price_status or (s.integration_provider and "cached") or "manual")
    d["supplier_item_number"] = d.get("supplier_item_number") or sm.supplier_item_number
    if d.get("conversion_factor") in (None, ""):
        d["conversion_factor"] = sm.conversion_factor
    if d.get("purchase_unit") in (None, ""):
        d["purchase_unit"] = sm.supplier_uom


async def _apply_items(db: AsyncSession, estimate_id, items, price_book_id=None) -> list[dict]:
    """Snapshot cost, apply Price Book rule (deterministic priority, respecting explicit user pricing),
    compute authoritative fields, persist. Returns computed line dicts (for totals)."""
    computed = []
    for idx, it in enumerate(items):
        d = it.model_dump() if hasattr(it, "model_dump") else dict(it)
        if d.get("material_id") or d.get("supplier_material_id"):
            await _snapshot_cost(db, d)
        # Price Book auto-application (only when the user hasn't explicitly priced the line).
        applied_book = applied_type = applied_value = None
        if price_book_id and (d.get("material_id") or d.get("assembly_id")):
            user_priced = (
                d.get("pricing_mode") in ("fixed", "markup", "margin")
                or (d.get("selling_unit_price") not in (None, "") and float(d.get("selling_unit_price") or 0) > 0)
                or (d.get("markup_percent") not in (None, ""))
            )
            if not user_priced:
                rule = await pricing_svc.find_rule(db, price_book_id, d.get("material_id"), d.get("assembly_id"))
                if rule:
                    ucost = calc.unit_cost(d.get("material_cost"), d.get("labor_cost"), d.get("equipment_cost"), d.get("subcontract_cost"))
                    sell = pricing_svc.apply_rule(rule, ucost)
                    if sell is not None:
                        d["selling_unit_price"] = sell
                        applied_book = price_book_id
                        applied_type = rule.rule_type
                        applied_value = pricing_svc.rule_value(rule)
        calc.compute_line(d)
        computed.append(d)
        db.add(EstimateLineItem(
            estimate_id=estimate_id, description=d.get("description") or "", quantity=d["quantity"],
            unit=d.get("unit") or "ea", unit_price=d["unit_price"], line_total=d["line_total"], sort=idx,
            material_id=d.get("material_id") or None, supplier_material_id=d.get("supplier_material_id") or None,
            line_kind=d.get("line_kind") or ("material" if d.get("material_id") else "custom"),
            base_cost=d.get("base_cost") or 0, material_cost=d.get("material_cost") or 0,
            labor_cost=d.get("labor_cost") or 0, equipment_cost=d.get("equipment_cost") or 0,
            subcontract_cost=d.get("subcontract_cost") or 0,
            measured_quantity=d.get("measured_quantity") or 0, waste_percent=d.get("waste_percent") or 0,
            order_quantity=d.get("order_quantity"), purchase_unit=d.get("purchase_unit"),
            conversion_factor=d.get("conversion_factor"), markup_percent=d.get("markup_percent") or 0,
            selling_unit_price=d["selling_unit_price"],
            cost_source_supplier_id=d.get("cost_source_supplier_id") or None,
            cost_source_supplier_name=d.get("cost_source_supplier_name"),
            supplier_item_number=d.get("supplier_item_number"), cost_source=d.get("cost_source"),
            cost_snapshot_at=(datetime.now(timezone.utc) if (d.get("material_id") or d.get("supplier_material_id")) else None),
            assembly_id=d.get("assembly_id") or None, assembly_version=d.get("assembly_version"),
            assembly_name=d.get("assembly_name"),
            applied_price_book_id=applied_book, applied_price_rule_type=applied_type, applied_price_rule_value=applied_value,
        ))
    return computed


@router.get("", response_model=list[EstimateOut])
async def list_estimates(lead_id: str | None = Query(None), customer_id: str | None = Query(None), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Estimate).order_by(Estimate.created_at.desc())
    if lead_id:
        stmt = stmt.where(Estimate.lead_id == lead_id)
    if customer_id:
        stmt = stmt.where(Estimate.customer_id == customer_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [await _out(db, e, user) for e in rows]


@router.post("", response_model=EstimateOut, status_code=201)
async def create_estimate(payload: EstimateIn, request: Request, idempotency_key: str | None = Header(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    existing_id = await check_idempotency(db, idempotency_key, "estimate")
    if existing_id:
        e = await db.get(Estimate, existing_id)
        if e:
            return await _out(db, e, user)
    number = await next_number(db, "estimate", "EST")
    pb_id = getattr(payload, "price_book_id", None) or await pricing_svc.default_price_book_id(db)
    e = Estimate(number=number, lead_id=payload.lead_id, customer_id=payload.customer_id, property_id=payload.property_id,
                 inspection_id=payload.inspection_id, tax_rate=payload.tax_rate, notes=payload.notes,
                 price_book_id=pb_id, created_by=user.email)
    db.add(e)
    await db.flush()
    computed = await _apply_items(db, e.id, payload.items, price_book_id=pb_id)
    s = calc.summarize(computed, payload.tax_rate)
    e.subtotal, e.tax, e.total = s["subtotal"], s["tax"], s["total"]
    await record_idempotency(db, idempotency_key, "estimate", e.id)
    await db.commit()
    await db.refresh(e)
    await log_action(db, user=user, action="estimate.create", entity_type="estimate", entity_id=e.id, detail={"number": number, "total": e.total}, request=request)
    return await _out(db, e, user)


@router.get("/{estimate_id}", response_model=EstimateOut)
async def get_estimate(estimate_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    e = await db.get(Estimate, estimate_id)
    if not e:
        raise HTTPException(status_code=404, detail="Estimate not found")
    return await _out(db, e, user)


@router.put("/{estimate_id}", response_model=EstimateOut)
async def update_estimate(estimate_id: str, payload: EstimateIn, request: Request, if_match: str | None = Header(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    e = await db.get(Estimate, estimate_id)
    if not e:
        raise HTTPException(status_code=404, detail="Estimate not found")
    if await _has_accepted_quote(db, e.id):
        raise HTTPException(status_code=409, detail="This estimate has an accepted quote and can no longer be edited.")
    enforce_version(e, if_match, "Estimate")
    if getattr(payload, "price_book_id", None) is not None:
        e.price_book_id = payload.price_book_id
    await db.execute(EstimateLineItem.__table__.delete().where(EstimateLineItem.estimate_id == e.id))
    computed = await _apply_items(db, e.id, payload.items, price_book_id=e.price_book_id)
    s = calc.summarize(computed, payload.tax_rate)
    e.tax_rate = payload.tax_rate
    e.subtotal, e.tax, e.total = s["subtotal"], s["tax"], s["total"]
    e.notes = payload.notes
    e.version += 1
    await db.commit()
    await db.refresh(e)
    await log_action(db, user=user, action="estimate.update", entity_type="estimate", entity_id=e.id, request=request)
    return await _out(db, e, user)


@router.post("/{estimate_id}/duplicate", response_model=EstimateOut, status_code=201)
async def duplicate_estimate(estimate_id: str, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """Copy an estimate (header + all line items, preserving their snapshots) into a brand-new draft."""
    src = await db.get(Estimate, estimate_id)
    if not src:
        raise HTTPException(status_code=404, detail="Estimate not found")
    number = await next_number(db, "estimate", "EST")
    dup = Estimate(number=number, lead_id=src.lead_id, customer_id=src.customer_id, property_id=src.property_id,
                   inspection_id=src.inspection_id, status="draft", tax_rate=src.tax_rate,
                   subtotal=src.subtotal, tax=src.tax, total=src.total,
                   notes=(f"{src.notes} (copy)" if src.notes else "Copy of " + src.number),
                   price_book_id=src.price_book_id, created_by=user.email)
    db.add(dup)
    await db.flush()
    src_lines = (await db.execute(select(EstimateLineItem).where(EstimateLineItem.estimate_id == src.id)
                                  .order_by(EstimateLineItem.sort))).scalars().all()
    skip = {"id", "estimate_id"}
    for li in src_lines:
        data = {c.name: getattr(li, c.name) for c in EstimateLineItem.__table__.columns if c.name not in skip}
        db.add(EstimateLineItem(estimate_id=dup.id, **data))
    await db.commit()
    await db.refresh(dup)
    await log_action(db, user=user, action="estimate.duplicate", entity_type="estimate", entity_id=dup.id, detail={"source": str(src.id), "number": number}, request=request)
    return await _out(db, dup, user)


async def _has_accepted_quote(db: AsyncSession, estimate_id) -> bool:
    n = (await db.execute(select(func.count()).select_from(Quote).where(
        Quote.estimate_id == estimate_id, Quote.status == "accepted"))).scalar() or 0
    return int(n) > 0


@router.delete("/{estimate_id}")
async def delete_estimate(estimate_id: str, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """Delete an estimate unless it has an accepted quote (history stays intact). Line items cascade;
    any non-accepted quotes keep their own snapshot (their estimate_id is set null)."""
    e = await db.get(Estimate, estimate_id)
    if not e:
        raise HTTPException(status_code=404, detail="Estimate not found")
    if await _has_accepted_quote(db, e.id):
        raise HTTPException(status_code=409, detail="This estimate has an accepted quote and can't be deleted.")
    await db.delete(e)
    await db.commit()
    await log_action(db, user=user, action="estimate.delete", entity_type="estimate", entity_id=estimate_id, request=request)
    return {"deleted": True, "id": estimate_id}


# ---- Slice 8: explicit cost refresh (never auto-applied) ----
async def _current_cost(db: AsyncSession, line: EstimateLineItem):
    sm = None
    if line.supplier_material_id:
        sm = await db.get(SupplierMaterial, line.supplier_material_id)
    elif line.material_id:
        sm = await inv_core.preferred_supplier_material(db, line.material_id) \
            or await inv_core.best_known_supplier_material(db, line.material_id)
    return sm


@router.get("/{estimate_id}/cost-refresh/preview", response_model=CostRefreshPreviewOut)
async def cost_refresh_preview(estimate_id: str, user: User = Depends(require_roles(*COST_ROLES)), db: AsyncSession = Depends(get_db)):
    e = await db.get(Estimate, estimate_id)
    if not e:
        raise HTTPException(status_code=404, detail="Estimate not found")
    items = (await db.execute(select(EstimateLineItem).where(EstimateLineItem.estimate_id == e.id).order_by(EstimateLineItem.sort))).scalars().all()
    rows = []
    for i in items:
        if not (i.material_id or i.supplier_material_id):
            continue
        sm = await _current_cost(db, i)
        if not sm:
            continue
        cur = sm.current_cost or 0
        old = i.base_cost or 0
        delta = calc.r2(cur - old)
        sname = None
        if sm.supplier_id:
            s = await db.get(Supplier, sm.supplier_id)
            sname = s.name if s else None
        rows.append(CostRefreshRow(line_id=str(i.id), description=i.description, material_id=str(i.material_id) if i.material_id else None,
                                   supplier_name=sname, old_cost=old, current_cost=cur, delta=delta,
                                   changed=(abs(delta) >= 0.005), cost_source=sm.price_status or "manual"))
    return CostRefreshPreviewOut(estimate_id=str(e.id), rows=rows, changed_count=sum(1 for r in rows if r.changed))


@router.post("/{estimate_id}/cost-refresh/apply", response_model=EstimateOut)
async def cost_refresh_apply(estimate_id: str, payload: CostRefreshApplyIn, request: Request, user: User = Depends(require_roles(*COST_ROLES)), db: AsyncSession = Depends(get_db)):
    e = await db.get(Estimate, estimate_id)
    if not e:
        raise HTTPException(status_code=404, detail="Estimate not found")
    ids = set(payload.line_ids)
    items = (await db.execute(select(EstimateLineItem).where(EstimateLineItem.estimate_id == e.id).order_by(EstimateLineItem.sort))).scalars().all()
    computed = []
    for i in items:
        if str(i.id) in ids:
            sm = await _current_cost(db, i)
            if sm:
                new_cost = sm.current_cost or 0
                i.material_cost = i.material_cost - (i.base_cost or 0) + new_cost  # shift material_cost by cost delta
                i.base_cost = new_cost
                i.cost_snapshot_at = datetime.now(timezone.utc)
                i.cost_source = sm.price_status or "manual"
                if payload.recalc_selling_price:
                    ucost = calc.unit_cost(i.material_cost, i.labor_cost, i.equipment_cost, i.subcontract_cost)
                    i.selling_unit_price = calc.price_from_markup(ucost, i.markup_percent)
                    i.unit_price = i.selling_unit_price
                    i.line_total = calc.r2(i.quantity * i.selling_unit_price)
                else:
                    i.markup_percent = calc.markup_from_prices(
                        calc.unit_cost(i.material_cost, i.labor_cost, i.equipment_cost, i.subcontract_cost), i.selling_unit_price)
        computed.append({"quantity": i.quantity, "material_cost": i.material_cost, "labor_cost": i.labor_cost,
                         "equipment_cost": i.equipment_cost, "subcontract_cost": i.subcontract_cost,
                         "line_total": i.line_total,
                         "_unit_cost": calc.unit_cost(i.material_cost, i.labor_cost, i.equipment_cost, i.subcontract_cost)})
    s = calc.summarize(computed, e.tax_rate)
    e.subtotal, e.tax, e.total = s["subtotal"], s["tax"], s["total"]
    e.version += 1
    await db.commit()
    await db.refresh(e)
    await log_action(db, user=user, action="estimate.cost_refresh", entity_type="estimate", entity_id=e.id,
                     detail={"lines": len(ids), "recalc_price": payload.recalc_selling_price}, request=request)
    return await _out(db, e, user)



# ---- Price Book: preview & apply repricing (explicit; existing estimates never silently repriced) ----
from pydantic import BaseModel as _BM


class PriceBookApplyIn(_BM):
    price_book_id: str
    apply: bool = False


@router.post("/{estimate_id}/price-book/preview")
async def price_book_preview(estimate_id: str, payload: PriceBookApplyIn, user: User = Depends(require_roles(*COST_ROLES)), db: AsyncSession = Depends(get_db)):
    e = await db.get(Estimate, estimate_id)
    if not e:
        raise HTTPException(status_code=404, detail="Estimate not found")
    items = (await db.execute(select(EstimateLineItem).where(EstimateLineItem.estimate_id == e.id).order_by(EstimateLineItem.sort))).scalars().all()
    rows = []
    for i in items:
        if not (i.material_id or i.assembly_id):
            continue  # manual lines with no matching rule remain unchanged
        rule = await pricing_svc.find_rule(db, payload.price_book_id, i.material_id, i.assembly_id)
        if not rule:
            continue
        uc = calc.unit_cost(i.material_cost, i.labor_cost, i.equipment_cost, i.subcontract_cost)
        new_sell = pricing_svc.apply_rule(rule, uc)
        if new_sell is None:
            continue
        rows.append({"line_id": str(i.id), "description": i.description, "current_sell": i.selling_unit_price,
                     "new_sell": new_sell, "difference": calc.r4(new_sell - (i.selling_unit_price or 0)),
                     "rule_type": rule.rule_type, "rule_value": pricing_svc.rule_value(rule)})
    return {"price_book_id": payload.price_book_id, "affected": len(rows), "lines": rows}


@router.post("/{estimate_id}/price-book/apply", response_model=EstimateOut)
async def price_book_apply(estimate_id: str, payload: PriceBookApplyIn, request: Request, user: User = Depends(require_roles(*COST_ROLES)), db: AsyncSession = Depends(get_db)):
    e = await db.get(Estimate, estimate_id)
    if not e:
        raise HTTPException(status_code=404, detail="Estimate not found")
    e.price_book_id = payload.price_book_id
    items = (await db.execute(select(EstimateLineItem).where(EstimateLineItem.estimate_id == e.id).order_by(EstimateLineItem.sort))).scalars().all()
    computed = []
    for i in items:
        if i.material_id or i.assembly_id:
            rule = await pricing_svc.find_rule(db, payload.price_book_id, i.material_id, i.assembly_id)
            if rule:
                uc = calc.unit_cost(i.material_cost, i.labor_cost, i.equipment_cost, i.subcontract_cost)
                new_sell = pricing_svc.apply_rule(rule, uc)
                if new_sell is not None:
                    i.selling_unit_price = new_sell
                    i.unit_price = new_sell
                    i.line_total = calc.r2(i.quantity * new_sell)
                    i.markup_percent = calc.markup_from_prices(uc, new_sell)
                    i.applied_price_book_id = e.price_book_id
                    i.applied_price_rule_type = rule.rule_type
                    i.applied_price_rule_value = pricing_svc.rule_value(rule)
        computed.append({"quantity": i.quantity, "material_cost": i.material_cost, "labor_cost": i.labor_cost,
                         "equipment_cost": i.equipment_cost, "subcontract_cost": i.subcontract_cost,
                         "line_total": i.line_total,
                         "_unit_cost": calc.unit_cost(i.material_cost, i.labor_cost, i.equipment_cost, i.subcontract_cost)})
    s = calc.summarize(computed, e.tax_rate)
    e.subtotal, e.tax, e.total = s["subtotal"], s["tax"], s["total"]
    e.version += 1
    await db.commit()
    await db.refresh(e)
    await log_action(db, user=user, action="estimate.price_book_apply", entity_type="estimate", entity_id=e.id,
                     detail={"price_book_id": payload.price_book_id}, request=request)
    return await _out(db, e, user)
