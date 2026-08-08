from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Quote, QuoteLineItem, Estimate, EstimateLineItem, Job, User
from core import get_current_user, require_roles, FIELD_ROLES, MANAGE_ROLES, log_action
from schemas_phase3 import QuoteIn, QuoteUpdate, QuoteOut, QuoteAccept, QuoteAcceptResult, JobOut, LineItemOut
from sales_common import next_number, compute_totals, line_total, enforce_version, check_idempotency, record_idempotency

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


async def _out(db: AsyncSession, q: Quote) -> QuoteOut:
    items = (await db.execute(select(QuoteLineItem).where(QuoteLineItem.quote_id == q.id).order_by(QuoteLineItem.sort))).scalars().all()
    return QuoteOut(
        id=str(q.id), number=q.number, estimate_id=str(q.estimate_id) if q.estimate_id else None,
        lead_id=str(q.lead_id) if q.lead_id else None, customer_id=str(q.customer_id) if q.customer_id else None,
        property_id=str(q.property_id) if q.property_id else None, status=q.status, issue_date=q.issue_date,
        expiration_date=q.expiration_date, tax_rate=q.tax_rate, subtotal=q.subtotal, tax=q.tax, total=q.total,
        terms=q.terms, accepted_at=q.accepted_at, accepted_by=q.accepted_by, acceptance_name=q.acceptance_name,
        version=q.version, created_at=q.created_at,
        items=[LineItemOut(id=str(i.id), description=i.description, quantity=i.quantity, unit=i.unit, unit_price=i.unit_price, line_total=i.line_total) for i in items],
    )


async def _apply_items(db, quote_id, items):
    for idx, it in enumerate(items):
        db.add(QuoteLineItem(quote_id=quote_id, description=it.description, quantity=it.quantity, unit=it.unit, unit_price=it.unit_price, line_total=line_total(it.quantity, it.unit_price), sort=idx))


@router.get("", response_model=list[QuoteOut])
async def list_quotes(lead_id: str | None = Query(None), customer_id: str | None = Query(None), status: str | None = Query(None), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Quote).order_by(Quote.created_at.desc())
    if lead_id:
        stmt = stmt.where(Quote.lead_id == lead_id)
    if customer_id:
        stmt = stmt.where(Quote.customer_id == customer_id)
    if status:
        stmt = stmt.where(Quote.status == status)
    return [await _out(db, q) for q in (await db.execute(stmt)).scalars().all()]


@router.post("", response_model=QuoteOut, status_code=201)
async def create_quote(payload: QuoteIn, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    items = payload.items
    tax_rate = payload.tax_rate
    est_id = payload.estimate_id
    lead_id, customer_id, property_id = payload.lead_id, payload.customer_id, payload.property_id
    if est_id:
        est = await db.get(Estimate, est_id)
        if not est:
            raise HTTPException(status_code=404, detail="Estimate not found")
        est_items = (await db.execute(select(EstimateLineItem).where(EstimateLineItem.estimate_id == est.id).order_by(EstimateLineItem.sort))).scalars().all()
        from schemas_phase3 import LineItemIn
        items = [LineItemIn(description=i.description, quantity=i.quantity, unit=i.unit, unit_price=i.unit_price) for i in est_items]
        tax_rate = est.tax_rate
        lead_id = lead_id or (str(est.lead_id) if est.lead_id else None)
        customer_id = customer_id or (str(est.customer_id) if est.customer_id else None)
        property_id = property_id or (str(est.property_id) if est.property_id else None)
    subtotal, tax, total = compute_totals(items, tax_rate)
    number = await next_number(db, "quote", "QUO")
    q = Quote(number=number, estimate_id=est_id, lead_id=lead_id, customer_id=customer_id, property_id=property_id,
              status="draft", issue_date=payload.issue_date or datetime.now(timezone.utc), expiration_date=payload.expiration_date,
              tax_rate=tax_rate, subtotal=subtotal, tax=tax, total=total, terms=payload.terms, created_by=user.email)
    db.add(q)
    await db.flush()
    await _apply_items(db, q.id, items)
    await db.commit()
    await db.refresh(q)
    await log_action(db, user=user, action="quote.create", entity_type="quote", entity_id=q.id, detail={"number": number, "total": total}, request=request)
    return await _out(db, q)


@router.get("/{quote_id}", response_model=QuoteOut)
async def get_quote(quote_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    q = await db.get(Quote, quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    return await _out(db, q)


@router.put("/{quote_id}", response_model=QuoteOut)
async def update_quote(quote_id: str, payload: QuoteUpdate, request: Request, if_match: str | None = Header(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    q = await db.get(Quote, quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    if q.status == "accepted":
        raise HTTPException(status_code=400, detail="An accepted quote cannot be edited")
    enforce_version(q, if_match, "Quote")
    data = payload.model_dump(exclude_unset=True)
    if "items" in data and payload.items is not None:
        await db.execute(QuoteLineItem.__table__.delete().where(QuoteLineItem.quote_id == q.id))
        await _apply_items(db, q.id, payload.items)
        tax_rate = payload.tax_rate if payload.tax_rate is not None else q.tax_rate
        subtotal, tax, total = compute_totals(payload.items, tax_rate)
        q.tax_rate, q.subtotal, q.tax, q.total = tax_rate, subtotal, tax, total
    elif payload.tax_rate is not None:
        items = (await db.execute(select(QuoteLineItem).where(QuoteLineItem.quote_id == q.id))).scalars().all()
        subtotal, tax, total = compute_totals(items, payload.tax_rate)
        q.tax_rate, q.subtotal, q.tax, q.total = payload.tax_rate, subtotal, tax, total
    for f in ("status", "issue_date", "expiration_date", "terms"):
        if f in data:
            setattr(q, f, data[f])
    q.version += 1
    await db.commit()
    await db.refresh(q)
    await log_action(db, user=user, action="quote.update", entity_type="quote", entity_id=q.id, request=request)
    return await _out(db, q)


@router.post("/{quote_id}/accept", response_model=QuoteAcceptResult)
async def accept_quote(quote_id: str, payload: QuoteAccept, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    q = await db.get(Quote, quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    # Idempotent: if already accepted, return existing job (quote-to-job plumbing preserved via quote_id unique)
    existing_job = (await db.execute(select(Job).where(Job.quote_id == q.id))).scalar_one_or_none()
    if q.status == "accepted" and existing_job:
        return QuoteAcceptResult(quote=await _out(db, q), job_id=str(existing_job.id))

    q.status = "accepted"
    q.accepted_at = datetime.now(timezone.utc)
    q.accepted_by = user.email
    q.acceptance_name = payload.acceptance_name
    if payload.notes:
        q.terms = (q.terms or "") + f"\n[Acceptance] {payload.notes}"

    job = existing_job
    if not job:
        number = await next_number(db, "job", "JOB")
        job = Job(number=number, quote_id=q.id, customer_id=q.customer_id, property_id=q.property_id, status="created", total=q.total,
                  scope=f"From quote {q.number}", created_by=user.email)
        db.add(job)
        await db.flush()
    await db.commit()
    await db.refresh(q)
    await log_action(db, user=user, action="quote.accept", entity_type="quote", entity_id=q.id, detail={"job_id": str(job.id)}, request=request)
    return QuoteAcceptResult(quote=await _out(db, q), job_id=str(job.id))


@router.post("/{quote_id}/decline", response_model=QuoteOut)
async def decline_quote(quote_id: str, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    q = await db.get(Quote, quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    q.status = "declined"
    await db.commit()
    await db.refresh(q)
    await log_action(db, user=user, action="quote.decline", entity_type="quote", entity_id=q.id, request=request)
    return await _out(db, q)
