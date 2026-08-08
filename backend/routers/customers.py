from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Customer, CustomerProperty, Lead, User
from core import get_current_user, require_roles, FIELD_ROLES, log_action
from schemas_phase3 import CustomerIn, CustomerPatch, CustomerOut

router = APIRouter(prefix="/api/customers", tags=["customers"])


async def _out(db: AsyncSession, c: Customer) -> CustomerOut:
    pids = (await db.execute(select(CustomerProperty.property_id).where(CustomerProperty.customer_id == c.id))).scalars().all()
    return CustomerOut(
        id=str(c.id), name=c.name, phone=c.phone, email=c.email, billing_address=c.billing_address,
        status=c.status, notes=c.notes, created_at=c.created_at, property_ids=[str(p) for p in pids],
    )


@router.get("", response_model=list[CustomerOut])
async def list_customers(q: str | None = Query(None), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Customer).order_by(Customer.created_at.desc())
    if q:
        stmt = stmt.where(Customer.name.ilike(f"%{q}%"))
    rows = (await db.execute(stmt)).scalars().all()
    return [await _out(db, c) for c in rows]


@router.post("", response_model=CustomerOut, status_code=201)
async def create_customer(payload: CustomerIn, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    c = Customer(**payload.model_dump(), created_by=user.email)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    await log_action(db, user=user, action="customer.create", entity_type="customer", entity_id=c.id, request=request)
    return await _out(db, c)


@router.post("/from-lead/{lead_id}", response_model=CustomerOut, status_code=201)
async def create_from_lead(lead_id: str, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.customer_id:
        existing = await db.get(Customer, lead.customer_id)
        if existing:
            return await _out(db, existing)
    c = Customer(name=lead.name or "New Customer", phone=lead.phone, email=lead.email, billing_address=lead.address, created_by=user.email)
    db.add(c)
    await db.flush()
    if lead.property_id:
        db.add(CustomerProperty(customer_id=c.id, property_id=lead.property_id))
    lead.customer_id = c.id
    lead.status = "converted"
    await db.commit()
    await db.refresh(c)
    await log_action(db, user=user, action="customer.from_lead", entity_type="customer", entity_id=c.id, detail={"lead_id": lead_id}, request=request)
    return await _out(db, c)


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await db.get(Customer, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return await _out(db, c)


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(customer_id: str, payload: CustomerPatch, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    c = await db.get(Customer, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    await db.commit()
    await db.refresh(c)
    await log_action(db, user=user, action="customer.update", entity_type="customer", entity_id=c.id, request=request)
    return await _out(db, c)


@router.post("/{customer_id}/properties", response_model=CustomerOut)
async def link_property(customer_id: str, body: dict, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    c = await db.get(Customer, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    pid = body.get("property_id")
    exists = (await db.execute(select(CustomerProperty).where(CustomerProperty.customer_id == customer_id, CustomerProperty.property_id == pid))).scalar_one_or_none()
    if not exists and pid:
        db.add(CustomerProperty(customer_id=c.id, property_id=pid))
        await db.commit()
    return await _out(db, c)
