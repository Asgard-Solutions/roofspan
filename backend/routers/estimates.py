from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Estimate, EstimateLineItem, User
from core import get_current_user, require_roles, FIELD_ROLES, log_action
from schemas_phase3 import EstimateIn, EstimateOut, LineItemOut
from sales_common import next_number, compute_totals, line_total, check_idempotency, record_idempotency, enforce_version

router = APIRouter(prefix="/api/estimates", tags=["estimates"])


async def _out(db: AsyncSession, e: Estimate) -> EstimateOut:
    items = (await db.execute(select(EstimateLineItem).where(EstimateLineItem.estimate_id == e.id).order_by(EstimateLineItem.sort))).scalars().all()
    return EstimateOut(
        id=str(e.id), number=e.number, lead_id=str(e.lead_id) if e.lead_id else None,
        customer_id=str(e.customer_id) if e.customer_id else None,
        property_id=str(e.property_id) if e.property_id else None,
        inspection_id=str(e.inspection_id) if e.inspection_id else None,
        status=e.status, tax_rate=e.tax_rate, subtotal=e.subtotal, tax=e.tax, total=e.total,
        notes=e.notes, version=e.version, created_at=e.created_at,
        items=[LineItemOut(id=str(i.id), description=i.description, quantity=i.quantity, unit=i.unit, unit_price=i.unit_price, line_total=i.line_total) for i in items],
    )


async def _apply_items(db, estimate_id, items):
    for idx, it in enumerate(items):
        db.add(EstimateLineItem(estimate_id=estimate_id, description=it.description, quantity=it.quantity, unit=it.unit, unit_price=it.unit_price, line_total=line_total(it.quantity, it.unit_price), sort=idx))


@router.get("", response_model=list[EstimateOut])
async def list_estimates(lead_id: str | None = Query(None), customer_id: str | None = Query(None), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Estimate).order_by(Estimate.created_at.desc())
    if lead_id:
        stmt = stmt.where(Estimate.lead_id == lead_id)
    if customer_id:
        stmt = stmt.where(Estimate.customer_id == customer_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [await _out(db, e) for e in rows]


@router.post("", response_model=EstimateOut, status_code=201)
async def create_estimate(payload: EstimateIn, request: Request, idempotency_key: str | None = Header(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    existing_id = await check_idempotency(db, idempotency_key, "estimate")
    if existing_id:
        e = await db.get(Estimate, existing_id)
        if e:
            return await _out(db, e)
    subtotal, tax, total = compute_totals(payload.items, payload.tax_rate)
    number = await next_number(db, "estimate", "EST")
    e = Estimate(number=number, lead_id=payload.lead_id, customer_id=payload.customer_id, property_id=payload.property_id,
                 inspection_id=payload.inspection_id, tax_rate=payload.tax_rate, subtotal=subtotal, tax=tax, total=total,
                 notes=payload.notes, created_by=user.email)
    db.add(e)
    await db.flush()
    await _apply_items(db, e.id, payload.items)
    await record_idempotency(db, idempotency_key, "estimate", e.id)
    await db.commit()
    await db.refresh(e)
    await log_action(db, user=user, action="estimate.create", entity_type="estimate", entity_id=e.id, detail={"number": number, "total": total}, request=request)
    return await _out(db, e)


@router.get("/{estimate_id}", response_model=EstimateOut)
async def get_estimate(estimate_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    e = await db.get(Estimate, estimate_id)
    if not e:
        raise HTTPException(status_code=404, detail="Estimate not found")
    return await _out(db, e)


@router.put("/{estimate_id}", response_model=EstimateOut)
async def update_estimate(estimate_id: str, payload: EstimateIn, request: Request, if_match: str | None = Header(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    e = await db.get(Estimate, estimate_id)
    if not e:
        raise HTTPException(status_code=404, detail="Estimate not found")
    enforce_version(e, if_match, "Estimate")
    await db.execute(EstimateLineItem.__table__.delete().where(EstimateLineItem.estimate_id == e.id))
    await _apply_items(db, e.id, payload.items)
    subtotal, tax, total = compute_totals(payload.items, payload.tax_rate)
    e.tax_rate = payload.tax_rate
    e.subtotal, e.tax, e.total = subtotal, tax, total
    e.notes = payload.notes
    e.version += 1
    await db.commit()
    await db.refresh(e)
    await log_action(db, user=user, action="estimate.update", entity_type="estimate", entity_id=e.id, request=request)
    return await _out(db, e)
