from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Inspection, User
from core import get_current_user, require_roles, FIELD_ROLES, log_action
from services import mobile_authz as mauthz
from schemas_phase3 import InspectionIn, InspectionOut

router = APIRouter(prefix="/api/inspections", tags=["inspections"])


def _out(i: Inspection) -> InspectionOut:
    return InspectionOut(
        id=str(i.id), lead_id=str(i.lead_id) if i.lead_id else None,
        customer_id=str(i.customer_id) if i.customer_id else None,
        property_id=str(i.property_id) if i.property_id else None,
        inspection_date=i.inspection_date, inspector=i.inspector, roof_condition=i.roof_condition,
        findings=i.findings, recommended_work=i.recommended_work, measurements=i.measurements,
        notes=i.notes, created_by=i.created_by, created_at=i.created_at,
    )


@router.get("", response_model=list[InspectionOut])
async def list_inspections(lead_id: str | None = Query(None), customer_id: str | None = Query(None), property_id: str | None = Query(None), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if mauthz.is_sales(user):  # sales must scope to a lead/property they own (no broad enumeration)
        if not lead_id and not property_id:
            raise HTTPException(status_code=403, detail="Sales must query inspections by their own lead or property")
        if lead_id:
            lead = await db.get(__import__("models").Lead, lead_id)
            if not lead:
                raise HTTPException(status_code=404, detail="Lead not found")
            await mauthz.assert_lead_access(db, lead, user)
        if property_id:
            await mauthz.assert_property_access(db, property_id, user)
    stmt = select(Inspection).order_by(Inspection.created_at.desc())
    if lead_id:
        stmt = stmt.where(Inspection.lead_id == lead_id)
    if customer_id:
        stmt = stmt.where(Inspection.customer_id == customer_id)
    if property_id:
        stmt = stmt.where(Inspection.property_id == property_id)
    return [_out(i) for i in (await db.execute(stmt)).scalars().all()]


@router.post("", response_model=InspectionOut, status_code=201)
async def create_inspection(payload: InspectionIn, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    i = Inspection(**payload.model_dump(), created_by=user.email)
    db.add(i)
    await db.commit()
    await db.refresh(i)
    await log_action(db, user=user, action="inspection.create", entity_type="inspection", entity_id=i.id, request=request)
    return _out(i)


@router.get("/{inspection_id}", response_model=InspectionOut)
async def get_inspection(inspection_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    i = await db.get(Inspection, inspection_id)
    if not i:
        raise HTTPException(status_code=404, detail="Inspection not found")
    await mauthz.assert_inspection_access(db, i, user)
    return _out(i)


@router.patch("/{inspection_id}", response_model=InspectionOut)
async def update_inspection(inspection_id: str, payload: InspectionIn, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    i = await db.get(Inspection, inspection_id)
    if not i:
        raise HTTPException(status_code=404, detail="Inspection not found")
    await mauthz.assert_inspection_access(db, i, user)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(i, k, v)
    await db.commit()
    await db.refresh(i)
    await log_action(db, user=user, action="inspection.update", entity_type="inspection", entity_id=i.id, request=request)
    return _out(i)
