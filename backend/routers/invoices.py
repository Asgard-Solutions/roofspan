from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Invoice, InvoiceLineItem, Quote, QuoteLineItem, Job, User
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_phase3 import InvoiceIn, InvoiceOut, InvoiceStatusIn, LineItemOut
from sales_common import next_number, compute_totals, line_total, check_idempotency, record_idempotency

router = APIRouter(prefix="/api/invoices", tags=["invoices"])
VALID_STATUS = ["draft", "issued", "paid", "void"]


async def _out(db: AsyncSession, inv: Invoice) -> InvoiceOut:
    items = (await db.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id).order_by(InvoiceLineItem.sort))).scalars().all()
    return InvoiceOut(
        id=str(inv.id), number=inv.number, quote_id=str(inv.quote_id) if inv.quote_id else None,
        job_id=str(inv.job_id) if inv.job_id else None, customer_id=str(inv.customer_id) if inv.customer_id else None,
        property_id=str(inv.property_id) if inv.property_id else None, status=inv.status, issue_date=inv.issue_date,
        due_date=inv.due_date, tax_rate=inv.tax_rate, subtotal=inv.subtotal, tax=inv.tax, total=inv.total, notes=inv.notes,
        created_at=inv.created_at,
        items=[LineItemOut(id=str(i.id), description=i.description, quantity=i.quantity, unit=i.unit, unit_price=i.unit_price, line_total=i.line_total) for i in items],
    )


@router.get("", response_model=list[InvoiceOut])
async def list_invoices(customer_id: str | None = Query(None), status: str | None = Query(None), user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    stmt = select(Invoice).order_by(Invoice.created_at.desc())
    if customer_id:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if status:
        stmt = stmt.where(Invoice.status == status)
    return [await _out(db, i) for i in (await db.execute(stmt)).scalars().all()]


@router.post("", response_model=InvoiceOut, status_code=201)
async def create_invoice(payload: InvoiceIn, request: Request, idempotency_key: str | None = Header(None), user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    existing_id = await check_idempotency(db, idempotency_key, "invoice")
    if existing_id:
        inv = await db.get(Invoice, existing_id)
        if inv:
            return await _out(db, inv)

    items = payload.items
    tax_rate = payload.tax_rate
    customer_id, property_id, quote_id, job_id = payload.customer_id, payload.property_id, payload.quote_id, payload.job_id
    if quote_id:
        q = await db.get(Quote, quote_id)
        if not q:
            raise HTTPException(status_code=404, detail="Quote not found")
        if q.status != "accepted":
            raise HTTPException(status_code=400, detail="Invoices can only be created from an accepted quote")
        qitems = (await db.execute(select(QuoteLineItem).where(QuoteLineItem.quote_id == q.id).order_by(QuoteLineItem.sort))).scalars().all()
        from schemas_phase3 import LineItemIn
        items = [LineItemIn(description=i.description, quantity=i.quantity, unit=i.unit, unit_price=i.unit_price) for i in qitems]
        tax_rate = q.tax_rate
        customer_id = customer_id or (str(q.customer_id) if q.customer_id else None)
        property_id = property_id or (str(q.property_id) if q.property_id else None)
        if not job_id:
            j = (await db.execute(select(Job).where(Job.quote_id == q.id))).scalar_one_or_none()
            job_id = str(j.id) if j else None

    subtotal, tax, total = compute_totals(items, tax_rate)
    number = await next_number(db, "invoice", "INV")
    inv = Invoice(number=number, customer_id=customer_id, property_id=property_id, quote_id=quote_id, job_id=job_id,
                  status="draft", issue_date=datetime.now(timezone.utc), due_date=payload.due_date, tax_rate=tax_rate,
                  subtotal=subtotal, tax=tax, total=total, notes=payload.notes, created_by=user.email)
    db.add(inv)
    await db.flush()
    for idx, it in enumerate(items):
        db.add(InvoiceLineItem(invoice_id=inv.id, description=it.description, quantity=it.quantity, unit=it.unit, unit_price=it.unit_price, line_total=line_total(it.quantity, it.unit_price), sort=idx))
    await record_idempotency(db, idempotency_key, "invoice", inv.id)
    await db.commit()
    await db.refresh(inv)
    await log_action(db, user=user, action="invoice.create", entity_type="invoice", entity_id=inv.id, detail={"number": number, "total": total}, request=request)
    return await _out(db, inv)


@router.get("/{invoice_id}", response_model=InvoiceOut)
async def get_invoice(invoice_id: str, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    inv = await db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return await _out(db, inv)


@router.post("/{invoice_id}/status", response_model=InvoiceOut)
async def set_status(invoice_id: str, payload: InvoiceStatusIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    inv = await db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if payload.status not in VALID_STATUS:
        raise HTTPException(status_code=422, detail=f"Status must be one of {VALID_STATUS}")
    inv.status = payload.status
    await db.commit()
    await db.refresh(inv)
    await log_action(db, user=user, action="invoice.status", entity_type="invoice", entity_id=inv.id, detail={"status": payload.status}, request=request)
    return await _out(db, inv)
