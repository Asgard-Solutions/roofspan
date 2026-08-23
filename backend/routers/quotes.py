from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import (Quote, QuoteLineItem, QuotePackage, Estimate, EstimateLineItem, Job, User)
from core import get_current_user, require_roles, FIELD_ROLES, MANAGE_ROLES, log_action
from schemas_phase3 import (QuoteIn, QuoteUpdate, QuoteOut, QuoteAccept, QuoteAcceptResult, LineItemOut,
                            QuotePackageOut)
from sales_common import next_number, enforce_version
from services import estimating as calc

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


def _r2(v):
    return round(float(v or 0), 2)


def _sell(i):
    v = getattr(i, "selling_unit_price", None) if not isinstance(i, dict) else i.get("selling_unit_price")
    if v in (None, "", 0):
        v = getattr(i, "unit_price", None) if not isinstance(i, dict) else i.get("unit_price")
    return float(v or 0)


def _qty(i):
    v = getattr(i, "quantity", None) if not isinstance(i, dict) else i.get("quantity")
    return float(v or 0)


def _totals(items, tax_rate):
    """Customer-facing totals from selling prices only."""
    subtotal = _r2(sum(_r2(_qty(i) * _sell(i)) for i in items))
    tax = _r2(subtotal * (tax_rate or 0) / 100.0)
    return subtotal, tax, _r2(subtotal + tax)


def _line_out(i: QuoteLineItem) -> LineItemOut:
    # Customer-facing: selling price + quantity only. Internal cost NEVER exposed on quote output.
    return LineItemOut(id=str(i.id), description=i.description, quantity=i.quantity, unit=i.unit,
                       unit_price=i.unit_price, line_total=i.line_total, selling_unit_price=i.unit_price)


async def _out(db: AsyncSession, q: Quote) -> QuoteOut:
    base_items = (await db.execute(select(QuoteLineItem).where(QuoteLineItem.quote_id == q.id, QuoteLineItem.package_id.is_(None)).order_by(QuoteLineItem.sort))).scalars().all()
    packages = []
    if q.multi_package:
        pkgs = (await db.execute(select(QuotePackage).where(QuotePackage.quote_id == q.id).order_by(QuotePackage.sort, QuotePackage.tier))).scalars().all()
        for p in pkgs:
            pitems = (await db.execute(select(QuoteLineItem).where(QuoteLineItem.package_id == p.id).order_by(QuoteLineItem.sort))).scalars().all()
            packages.append(QuotePackageOut(id=str(p.id), name=p.name, tier=p.tier, subtotal=p.subtotal,
                                            tax=p.tax, total=p.total, notes=p.notes, items=[_line_out(i) for i in pitems]))
    return QuoteOut(
        id=str(q.id), number=q.number, estimate_id=str(q.estimate_id) if q.estimate_id else None,
        lead_id=str(q.lead_id) if q.lead_id else None, customer_id=str(q.customer_id) if q.customer_id else None,
        property_id=str(q.property_id) if q.property_id else None, status=q.status, issue_date=q.issue_date,
        expiration_date=q.expiration_date, tax_rate=q.tax_rate, subtotal=q.subtotal, tax=q.tax, total=q.total,
        terms=q.terms, accepted_at=q.accepted_at, accepted_by=q.accepted_by, acceptance_name=q.acceptance_name,
        version=q.version, created_at=q.created_at, items=[_line_out(i) for i in base_items],
        multi_package=q.multi_package, accepted_package_id=str(q.accepted_package_id) if q.accepted_package_id else None,
        packages=packages,
    )


def _persist_line(db, quote_id, it, idx, package_id=None):
    d = it.model_dump() if hasattr(it, "model_dump") else dict(it)
    sell = d.get("selling_unit_price")
    if sell in (None, ""):
        sell = d.get("unit_price") or 0
    sell = float(sell or 0)
    qty = float(d.get("quantity") or 0)
    ucost = calc.unit_cost(d.get("material_cost"), d.get("labor_cost"), d.get("equipment_cost"), d.get("subcontract_cost")) \
        if any(d.get(k) for k in ("material_cost", "labor_cost", "equipment_cost", "subcontract_cost")) else float(d.get("base_cost") or 0)
    db.add(QuoteLineItem(quote_id=quote_id, package_id=package_id, description=d.get("description") or "",
                         quantity=qty, unit=d.get("unit") or "ea", unit_price=sell, line_total=_r2(qty * sell),
                         sort=idx, material_id=d.get("material_id") or None, total_unit_cost=ucost,
                         markup_percent=d.get("markup_percent") or 0))


async def _apply_packages(db, q: Quote, packages, tax_rate):
    await db.execute(QuotePackage.__table__.delete().where(QuotePackage.quote_id == q.id))
    first_totals = None
    for pidx, pkg in enumerate(packages):
        p = QuotePackage(quote_id=q.id, name=pkg.name, tier=pkg.tier, notes=pkg.notes, sort=pidx)
        db.add(p)
        await db.flush()
        for idx, it in enumerate(pkg.items):
            _persist_line(db, q.id, it, idx, package_id=p.id)
        sub, tax, tot = _totals(pkg.items, tax_rate)
        p.subtotal, p.tax, p.total = sub, tax, tot
        if first_totals is None:
            first_totals = (sub, tax, tot)
    return first_totals or (0, 0, 0)


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
        # snapshot customer selling price + internal cost from estimate. Be resilient to which field
        # actually holds the value (quantity vs measured_quantity; selling_unit_price vs unit_price;
        # or derive price from line_total) so the quote never comes through as 0 when the estimate has data.
        items = []
        for i in est_items:
            qty = i.quantity if i.quantity not in (None, 0) else (i.measured_quantity or 0)
            price = i.selling_unit_price if i.selling_unit_price not in (None, 0) else (i.unit_price or 0)
            if (not price) and i.line_total and qty:
                price = round(float(i.line_total) / float(qty), 4)
            items.append(LineItemIn(description=i.description, quantity=qty, unit=i.unit,
                                    unit_price=price, selling_unit_price=price,
                                    material_id=str(i.material_id) if i.material_id else None,
                                    base_cost=calc.unit_cost(i.material_cost, i.labor_cost, i.equipment_cost, i.subcontract_cost),
                                    markup_percent=i.markup_percent))
        tax_rate = est.tax_rate
        lead_id = lead_id or (str(est.lead_id) if est.lead_id else None)
        customer_id = customer_id or (str(est.customer_id) if est.customer_id else None)
        property_id = property_id or (str(est.property_id) if est.property_id else None)
    number = await next_number(db, "quote", "QUO")
    q = Quote(number=number, estimate_id=est_id, lead_id=lead_id, customer_id=customer_id, property_id=property_id,
              status="draft", issue_date=payload.issue_date or datetime.now(timezone.utc), expiration_date=payload.expiration_date,
              tax_rate=tax_rate, terms=payload.terms, created_by=user.email, multi_package=payload.multi_package)
    db.add(q)
    await db.flush()
    if payload.multi_package and payload.packages:
        sub, tax, tot = await _apply_packages(db, q, payload.packages, tax_rate)
    else:
        for idx, it in enumerate(items):
            _persist_line(db, q.id, it, idx)
        sub, tax, tot = _totals(items, tax_rate)
    q.subtotal, q.tax, q.total = sub, tax, tot
    await db.commit()
    await db.refresh(q)
    await log_action(db, user=user, action="quote.create", entity_type="quote", entity_id=q.id, detail={"number": number, "total": q.total}, request=request)
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
    tax_rate = payload.tax_rate if payload.tax_rate is not None else q.tax_rate
    if payload.multi_package is not None:
        q.multi_package = payload.multi_package
    if q.multi_package and payload.packages is not None:
        await db.execute(QuoteLineItem.__table__.delete().where(QuoteLineItem.quote_id == q.id))
        sub, tax, tot = await _apply_packages(db, q, payload.packages, tax_rate)
        q.tax_rate, q.subtotal, q.tax, q.total = tax_rate, sub, tax, tot
    elif "items" in data and payload.items is not None:
        await db.execute(QuoteLineItem.__table__.delete().where(QuoteLineItem.quote_id == q.id))
        for idx, it in enumerate(payload.items):
            _persist_line(db, q.id, it, idx)
        sub, tax, tot = _totals(payload.items, tax_rate)
        q.tax_rate, q.subtotal, q.tax, q.total = tax_rate, sub, tax, tot
    elif payload.tax_rate is not None:
        items = (await db.execute(select(QuoteLineItem).where(QuoteLineItem.quote_id == q.id, QuoteLineItem.package_id.is_(None)))).scalars().all()
        sub, tax, tot = _totals(items, payload.tax_rate)
        q.tax_rate, q.subtotal, q.tax, q.total = payload.tax_rate, sub, tax, tot
    for f in ("status", "issue_date", "expiration_date", "terms"):
        if f in data:
            setattr(q, f, data[f])
    q.version += 1
    await db.commit()
    await db.refresh(q)
    await log_action(db, user=user, action="quote.update", entity_type="quote", entity_id=q.id, request=request)
    return await _out(db, q)


@router.delete("/{quote_id}")
async def delete_quote(quote_id: str, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """Delete a quote unless it has been accepted (an accepted quote is contractually locked and may
    have created a Job/Invoice). Packages and line items cascade."""
    q = await db.get(Quote, quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    if q.status == "accepted":
        raise HTTPException(status_code=409, detail="An accepted quote cannot be deleted.")
    await db.delete(q)
    await db.commit()
    await log_action(db, user=user, action="quote.delete", entity_type="quote", entity_id=quote_id, request=request)
    return {"deleted": True, "id": quote_id}


@router.post("/{quote_id}/accept", response_model=QuoteAcceptResult)
async def accept_quote(quote_id: str, payload: QuoteAccept, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    q = await db.get(Quote, quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    existing_job = (await db.execute(select(Job).where(Job.quote_id == q.id))).scalar_one_or_none()
    if q.status == "accepted" and existing_job:
        return QuoteAcceptResult(quote=await _out(db, q), job_id=str(existing_job.id))

    accepted_total = q.total
    if q.multi_package:
        if not payload.package_id:
            raise HTTPException(status_code=400, detail="Select a package to accept for this multi-option quote")
        pkg = await db.get(QuotePackage, payload.package_id)
        if not pkg or pkg.quote_id != q.id:
            raise HTTPException(status_code=404, detail="Package not found on this quote")
        q.accepted_package_id = pkg.id
        accepted_total = pkg.total
        q.subtotal, q.tax, q.total = pkg.subtotal, pkg.tax, pkg.total

    q.status = "accepted"
    q.accepted_at = datetime.now(timezone.utc)
    q.accepted_by = user.email
    q.acceptance_name = payload.acceptance_name
    if payload.notes:
        q.terms = (q.terms or "") + f"\n[Acceptance] {payload.notes}"

    job = existing_job
    if not job:
        number = await next_number(db, "job", "JOB")
        job = Job(number=number, quote_id=q.id, customer_id=q.customer_id, property_id=q.property_id, status="created", total=accepted_total,
                  scope=f"From quote {q.number}", created_by=user.email)
        db.add(job)
        await db.flush()
    await db.commit()
    await db.refresh(q)
    await log_action(db, user=user, action="quote.accept", entity_type="quote", entity_id=q.id, detail={"job_id": str(job.id), "package_id": str(q.accepted_package_id) if q.accepted_package_id else None}, request=request)
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


# ---- Customer Proposal (customer-safe; built from stored snapshot; never exposes internal cost) ----
from fastapi.responses import StreamingResponse as _Streaming
import io as _io
from services import proposal as _proposal


@router.get("/{quote_id}/proposal")
async def quote_proposal(quote_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    q = await db.get(Quote, quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    return await _proposal.proposal_data(db, q)


@router.get("/{quote_id}/proposal.pdf")
async def quote_proposal_pdf(quote_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    q = await db.get(Quote, quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    data = await _proposal.proposal_data(db, q)
    pdf = _proposal.build_pdf(data)
    return _Streaming(_io.BytesIO(pdf), media_type="application/pdf",
                      headers={"Content-Disposition": f'inline; filename="Proposal-{q.number}.pdf"'})
