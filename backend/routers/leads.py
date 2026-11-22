import uuid
from services.assignees import resolve_assignee
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Lead, Property, PropertyContact, Visit, Customer, User
from core import get_current_user, require_roles, FIELD_ROLES, MANAGE_ROLES, log_action
from schemas_phase2 import LeadOut, LeadPatch
from schemas_phase3 import LeadDetailOut

router = APIRouter(prefix="/api/leads", tags=["leads"])


class AssignIn(BaseModel):
    user_id: str | None = None


async def _user_name_map(db: AsyncSession, ids) -> dict:
    ids = [i for i in {x for x in ids} if i]
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: (u.full_name or u.email) for u in rows}


def _out(lead: Lead, address: str | None = None, user_name: str | None = None) -> LeadOut:
    return LeadOut(
        id=str(lead.id), property_id=str(lead.property_id) if lead.property_id else None,
        name=lead.name, phone=lead.phone, email=lead.email, address=lead.address,
        status=lead.status, notes=lead.notes, created_by=lead.created_by,
        created_at=lead.created_at, property_address=address or lead.address,
        assigned_user_id=str(lead.assigned_user_id) if lead.assigned_user_id else None,
        assigned_user_name=user_name,
    )


@router.get("", response_model=list[LeadOut])
async def list_leads(status: str | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Lead).order_by(Lead.created_at.desc())
    if status:
        stmt = stmt.where(Lead.status == status)
    if user.role == "sales":  # strict: sales see only leads assigned to them
        stmt = stmt.where(Lead.assigned_user_id == user.id)
    rows = (await db.execute(stmt)).scalars().all()
    umap = await _user_name_map(db, [l.assigned_user_id for l in rows])
    return [_out(l, user_name=umap.get(l.assigned_user_id)) for l in rows]


@router.get("/{lead_id}/workflow")
async def get_lead_workflow(lead_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from services.lead_workflow import lead_workflow
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if user.role == "sales" and lead.assigned_user_id != user.id:
        raise HTTPException(status_code=403, detail="This lead is not assigned to you")
    return await lead_workflow(db, lead)


@router.get("/{lead_id}", response_model=LeadDetailOut)
async def get_lead(lead_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if user.role == "sales" and lead.assigned_user_id != user.id:  # strict visibility
        raise HTTPException(status_code=403, detail="This lead is not assigned to you")
    address = lead.address
    owner_name = None
    visits = []
    if lead.property_id:
        p = await db.get(Property, lead.property_id)
        if p:
            address = p.formatted_address
            owner = (await db.execute(select(PropertyContact).where(PropertyContact.property_id == p.id, PropertyContact.kind == "owner"))).scalars().first()
            owner_name = owner.name if owner else None
            vrows = (await db.execute(select(Visit).where(Visit.property_id == p.id).order_by(Visit.visited_at.desc()))).scalars().all()
            visits = [{"id": str(v.id), "outcome": v.outcome, "notes": v.notes, "visited_at": v.visited_at.isoformat(), "user_email": v.user_email} for v in vrows]
    customer_name = None
    if lead.customer_id:
        c = await db.get(Customer, lead.customer_id)
        customer_name = c.name if c else None
    assigned_user_name = None
    if lead.assigned_user_id:
        au = await db.get(User, lead.assigned_user_id)
        assigned_user_name = (au.full_name or au.email) if au else None
    return LeadDetailOut(
        id=str(lead.id), property_id=str(lead.property_id) if lead.property_id else None, name=lead.name,
        phone=lead.phone, email=lead.email, address=lead.address, status=lead.status, notes=lead.notes,
        customer_id=str(lead.customer_id) if lead.customer_id else None, assigned_to=lead.assigned_to,
        assigned_user_id=str(lead.assigned_user_id) if lead.assigned_user_id else None,
        assigned_user_name=assigned_user_name,
        created_by=lead.created_by, created_at=lead.created_at, property_address=address,
        owner_name=owner_name, customer_name=customer_name, visits=visits,
    )


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(lead_id: str, payload: LeadPatch, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if user.role == "sales" and lead.assigned_user_id != user.id:  # strict: sales may only edit their own
        raise HTTPException(status_code=403, detail="This lead is not assigned to you")
    fields = payload.model_dump(exclude_unset=True)
    for k, v in fields.items():
        setattr(lead, k, v)
    await db.commit()
    await db.refresh(lead)
    await log_action(db, user=user, action="lead.update", entity_type="lead", entity_id=lead.id, request=request)
    return _out(lead)


@router.put("/{lead_id}/assign", response_model=LeadDetailOut)
async def assign_lead(lead_id: str, payload: AssignIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    try:
        lead = await db.get(Lead, uuid.UUID(lead_id))
    except ValueError:
        lead = None
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    target = await resolve_assignee(db, payload.user_id)
    lead.assigned_user_id = target.id if target else None
    await db.commit()
    await db.refresh(lead)
    await log_action(db, user=user, action="lead.assign", entity_type="lead", entity_id=lead.id,
                     detail={"assigned_user_id": str(lead.assigned_user_id) if lead.assigned_user_id else None}, request=request)
    return await get_lead(lead_id, user, db)
