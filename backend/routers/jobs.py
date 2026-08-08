from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Job, JobMaterial, Material, Customer, Property, PurchaseOrder, User
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_phase3 import JobOut
from schemas_phase4 import JobPatch, JobMaterialIn, JobMaterialOut, JobDetailOut

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _out(j: Job) -> JobOut:
    return JobOut(id=str(j.id), number=j.number, quote_id=str(j.quote_id) if j.quote_id else None,
                  customer_id=str(j.customer_id) if j.customer_id else None,
                  property_id=str(j.property_id) if j.property_id else None,
                  status=j.status, scope=j.scope, total=j.total, created_at=j.created_at)


async def _job_material_out(db: AsyncSession, jm: JobMaterial) -> JobMaterialOut:
    m = await db.get(Material, jm.material_id)
    return JobMaterialOut(
        id=str(jm.id), material_id=str(jm.material_id), material_name=m.name if m else "?",
        unit=m.unit if m else "", planned_quantity=jm.planned_quantity,
        quantity_on_hand=m.quantity_on_hand if m else 0,
        low_stock=(m.quantity_on_hand <= m.reorder_threshold) if m else False, notes=jm.notes,
    )


@router.get("", response_model=list[JobOut])
async def list_jobs(customer_id: str | None = Query(None), status: str | None = Query(None), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Job).order_by(Job.created_at.desc())
    if customer_id:
        stmt = stmt.where(Job.customer_id == customer_id)
    if status:
        stmt = stmt.where(Job.status == status)
    return [_out(j) for j in (await db.execute(stmt)).scalars().all()]


@router.get("/{job_id}", response_model=JobDetailOut)
async def get_job(job_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    cust = await db.get(Customer, j.customer_id) if j.customer_id else None
    prop = await db.get(Property, j.property_id) if j.property_id else None
    jms = (await db.execute(select(JobMaterial).where(JobMaterial.job_id == j.id))).scalars().all()
    pos = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.job_id == j.id).order_by(PurchaseOrder.created_at.desc()))).scalars().all()
    return JobDetailOut(
        id=str(j.id), number=j.number, quote_id=str(j.quote_id) if j.quote_id else None,
        customer_id=str(j.customer_id) if j.customer_id else None, customer_name=cust.name if cust else None,
        property_id=str(j.property_id) if j.property_id else None, property_address=prop.formatted_address if prop else None,
        status=j.status, scope=j.scope, notes=j.notes, total=j.total, scheduled_start=j.scheduled_start,
        scheduled_end=j.scheduled_end, schedule_notes=j.schedule_notes, assigned_to=j.assigned_to, created_at=j.created_at,
        materials=[await _job_material_out(db, jm) for jm in jms],
        purchase_orders=[{"id": str(p.id), "number": p.number, "status": p.status, "total": p.total} for p in pos],
    )


@router.patch("/{job_id}", response_model=JobDetailOut)
async def update_job(job_id: str, payload: JobPatch, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    valid = ["created", "pending", "scheduled", "in_progress", "completed", "cancelled"]
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in valid:
        raise HTTPException(status_code=422, detail=f"Status must be one of {valid}")
    for k, v in data.items():
        setattr(j, k, v)
    await db.commit()
    await log_action(db, user=user, action="job.update", entity_type="job", entity_id=j.id, detail=payload.model_dump(exclude_unset=True, mode="json"), request=request)
    return await get_job(job_id, user, db)


@router.get("/{job_id}/materials", response_model=list[JobMaterialOut])
async def list_job_materials(job_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    jms = (await db.execute(select(JobMaterial).where(JobMaterial.job_id == job_id))).scalars().all()
    return [await _job_material_out(db, jm) for jm in jms]


@router.post("/{job_id}/materials", response_model=JobMaterialOut, status_code=201)
async def add_job_material(job_id: str, payload: JobMaterialIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    m = await db.get(Material, payload.material_id)
    if not m:
        raise HTTPException(status_code=404, detail="Material not found")
    jm = JobMaterial(job_id=j.id, material_id=payload.material_id, planned_quantity=payload.planned_quantity, notes=payload.notes)
    db.add(jm)
    await db.commit()
    await db.refresh(jm)
    await log_action(db, user=user, action="job.add_material", entity_type="job", entity_id=j.id, request=request)
    return await _job_material_out(db, jm)


@router.delete("/{job_id}/materials/{jm_id}")
async def remove_job_material(job_id: str, jm_id: str, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    jm = await db.get(JobMaterial, jm_id)
    if not jm:
        raise HTTPException(status_code=404, detail="Job material not found")
    await db.delete(jm)
    await db.commit()
    return {"ok": True}
