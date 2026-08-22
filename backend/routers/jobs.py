from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Job, JobMaterial, Material, Customer, Property, PurchaseOrder, User, ActualCostEntry, JobCostSnapshot
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_phase3 import JobOut
from schemas_phase4 import JobPatch, JobMaterialIn, JobMaterialOut, JobDetailOut
from services import job_planning as jp
from services import job_costing as jc

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

COST_CATEGORIES = {"labor", "equipment", "subcontract", "permits", "disposal", "other"}


class ReserveIn(BaseModel):
    quantity: float | None = None


class ActualCostIn(BaseModel):
    category: str
    description: str = ""
    amount: float | None = None
    quantity: float | None = None
    unit_rate: float | None = None
    incurred_on: str | None = None
    notes: str | None = None


class SnapshotIn(BaseModel):
    trigger: str = "manual"


async def _plan_row(db, jm):
    from services import inventory_ops as iops
    m = await db.get(Material, jm.material_id)
    roll = await jp.rollup(db, jm)
    cons = await iops.job_material_consumption(db, jm.material_id, jm.job_id)
    return {"id": str(jm.id), "material_id": str(jm.material_id), "material_name": m.name if m else "?",
            "unit": jm.unit or (m.unit if m else "ea"), "notes": jm.notes,
            "assembly_name": jm.assembly_name, "waste": cons["waste"], "net_used": cons["net_used"],
            "preferred_supplier": (await _pref_name(db, jm.material_id)),
            "best_known_cost": await _best_cost(db, jm.material_id), **roll}


async def _pref_name(db, material_id):
    from services import inventory_core as inv
    sm = await inv.preferred_supplier_material(db, material_id)
    if sm and sm.supplier_id:
        s = await db.get(__import__("models").Supplier, sm.supplier_id)
        return s.name if s else None
    return None


async def _best_cost(db, material_id):
    from services import inventory_core as inv
    return await inv.best_known_cost(db, material_id)


class AssignIn(BaseModel):
    user_id: str | None = None


async def _user_name_map(db: AsyncSession, ids) -> dict:
    ids = [i for i in {x for x in ids} if i]
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: (u.full_name or u.email) for u in rows}


def _out(j: Job, user_name: str | None = None) -> JobOut:
    return JobOut(id=str(j.id), number=j.number, quote_id=str(j.quote_id) if j.quote_id else None,
                  customer_id=str(j.customer_id) if j.customer_id else None,
                  property_id=str(j.property_id) if j.property_id else None,
                  status=j.status, scope=j.scope, total=j.total, created_at=j.created_at,
                  assigned_user_id=str(j.assigned_user_id) if j.assigned_user_id else None,
                  assigned_user_name=user_name)


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
    if user.role == "sales":  # strict: sales see only jobs assigned to them
        stmt = stmt.where(Job.assigned_user_id == user.id)
    rows = (await db.execute(stmt)).scalars().all()
    umap = await _user_name_map(db, [j.assigned_user_id for j in rows])
    return [_out(j, user_name=umap.get(j.assigned_user_id)) for j in rows]


@router.get("/{job_id}", response_model=JobDetailOut)
async def get_job(job_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    if user.role == "sales" and j.assigned_user_id != user.id:  # strict visibility
        raise HTTPException(status_code=403, detail="This job is not assigned to you")
    cust = await db.get(Customer, j.customer_id) if j.customer_id else None
    prop = await db.get(Property, j.property_id) if j.property_id else None
    jms = (await db.execute(select(JobMaterial).where(JobMaterial.job_id == j.id))).scalars().all()
    pos = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.job_id == j.id).order_by(PurchaseOrder.created_at.desc()))).scalars().all()
    assigned_user_name = None
    if j.assigned_user_id:
        au = await db.get(User, j.assigned_user_id)
        assigned_user_name = (au.full_name or au.email) if au else None
    return JobDetailOut(
        id=str(j.id), number=j.number, quote_id=str(j.quote_id) if j.quote_id else None,
        customer_id=str(j.customer_id) if j.customer_id else None, customer_name=cust.name if cust else None,
        property_id=str(j.property_id) if j.property_id else None, property_address=prop.formatted_address if prop else None,
        status=j.status, scope=j.scope, notes=j.notes, total=j.total, scheduled_start=j.scheduled_start,
        scheduled_end=j.scheduled_end, schedule_notes=j.schedule_notes, assigned_to=j.assigned_to,
        assigned_user_id=str(j.assigned_user_id) if j.assigned_user_id else None, assigned_user_name=assigned_user_name,
        created_at=j.created_at,
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
    # Slice 10: auto-release remaining reservations when a job is completed/cancelled (idempotent, no On Hand change)
    if data.get("status") in ("completed", "cancelled"):
        from services import inventory_ops as ops
        await ops.auto_release_reservations(db, j, user.email)
    # Actual Job Costing: capture an IMMUTABLE cost snapshot when a job is marked completed.
    if data.get("status") == "completed":
        await jc.build_snapshot(db, j, "completion", user.email)
    await db.commit()
    await log_action(db, user=user, action="job.update", entity_type="job", entity_id=j.id, detail=payload.model_dump(exclude_unset=True, mode="json"), request=request)
    return await get_job(job_id, user, db)


@router.put("/{job_id}/assign", response_model=JobDetailOut)
async def assign_job(job_id: str, payload: AssignIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    if payload.user_id:
        target = await db.get(User, payload.user_id)
        if not target or not target.is_active:
            raise HTTPException(status_code=422, detail="Assignee must be an active user")
        j.assigned_user_id = target.id
    else:
        j.assigned_user_id = None
    await db.commit()
    await log_action(db, user=user, action="job.assign", entity_type="job", entity_id=j.id,
                     detail={"assigned_user_id": str(j.assigned_user_id) if j.assigned_user_id else None}, request=request)
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



@router.get("/{job_id}/material-plan")
async def job_material_plan(job_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    jms = (await db.execute(select(JobMaterial).where(JobMaterial.job_id == j.id))).scalars().all()
    rows = [await _plan_row(db, jm) for jm in jms]
    order = {"backordered": 0, "waiting_on_materials": 1, "partially_ready": 2, "ready": 3}
    job_status = min([r["status"] for r in rows], key=lambda s: order.get(s, 1)) if rows else "ready"
    return {"job_id": str(j.id), "job_number": j.number, "job_status": job_status,
            "can_generate": bool(j.quote_id), "materials": rows}


@router.post("/{job_id}/materials/generate")
async def generate_job_materials(job_id: str, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    result = await jp.generate_from_quote(db, j, user.email)
    await db.commit()
    await log_action(db, user=user, action="job.materials.generate", entity_type="job", entity_id=j.id, detail=result, request=request)
    return result


@router.post("/{job_id}/materials/{jm_id}/reserve")
async def reserve_job_material(job_id: str, jm_id: str, payload: ReserveIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    jm = await db.get(JobMaterial, jm_id)
    if not jm or str(jm.job_id) != job_id:
        raise HTTPException(status_code=404, detail="Job material not found")
    result = await jp.reserve(db, jm, payload.quantity, user.email)
    await db.commit()
    await log_action(db, user=user, action="job.material.reserve", entity_type="job", entity_id=jm.job_id, detail={"jm": jm_id, "reserved": result.get("reserved")}, request=request)
    return result


@router.post("/{job_id}/materials/{jm_id}/release")
async def release_job_material(job_id: str, jm_id: str, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    jm = await db.get(JobMaterial, jm_id)
    if not jm or str(jm.job_id) != job_id:
        raise HTTPException(status_code=404, detail="Job material not found")
    result = await jp.release(db, jm, user.email)
    await db.commit()
    await log_action(db, user=user, action="job.material.release", entity_type="job", entity_id=jm.job_id, detail={"jm": jm_id}, request=request)
    return result


@router.get("/{job_id}/purchase-proposal")
async def job_purchase_proposal(job_id: str, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return await jp.shortage_proposal(db, j)


# --- Actual Job Costing (cost/profitability data — Sales role is NEVER granted access) ---
@router.get("/{job_id}/costing")
async def job_costing(job_id: str, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return await jc.costing(db, j)


@router.get("/{job_id}/actual-costs")
async def list_actual_costs(job_id: str, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return await jc.manual_actual_costs(db, j)


@router.post("/{job_id}/actual-costs", status_code=201)
async def add_actual_cost(job_id: str, payload: ActualCostIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    from datetime import datetime as _dt
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    cat = (payload.category or "").strip().lower()
    if cat not in COST_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"category must be one of {sorted(COST_CATEGORIES)}")
    # amount is authoritative; derive from quantity*unit_rate only when amount omitted.
    amount = payload.amount
    if amount is None and payload.quantity is not None and payload.unit_rate is not None:
        amount = float(payload.quantity) * float(payload.unit_rate)
    if amount is None or amount < 0:
        raise HTTPException(status_code=422, detail="amount (>= 0) is required")
    incurred = None
    if payload.incurred_on:
        try:
            incurred = _dt.fromisoformat(payload.incurred_on.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="incurred_on must be ISO date/datetime")
    e = ActualCostEntry(job_id=j.id, category=cat, description=payload.description or "",
                        amount=jc._q4(amount), quantity=jc._q4(payload.quantity) if payload.quantity is not None else None,
                        unit_rate=jc._q4(payload.unit_rate) if payload.unit_rate is not None else None,
                        incurred_on=incurred, notes=payload.notes, created_by=user.email)
    db.add(e)
    await db.commit()
    await db.refresh(e)
    await log_action(db, user=user, action="job.actual_cost.add", entity_type="job", entity_id=j.id,
                     detail={"category": cat, "amount": float(e.amount)}, request=request)
    return {"id": str(e.id), "category": e.category, "amount": float(e.amount)}


@router.delete("/{job_id}/actual-costs/{entry_id}")
async def delete_actual_cost(job_id: str, entry_id: str, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    e = await db.get(ActualCostEntry, entry_id)
    if not e or str(e.job_id) != job_id:
        raise HTTPException(status_code=404, detail="Cost entry not found")
    await db.delete(e)
    await db.commit()
    await log_action(db, user=user, action="job.actual_cost.delete", entity_type="job", entity_id=job_id, request=request)
    return {"ok": True}


@router.get("/{job_id}/cost-snapshots")
async def list_cost_snapshots(job_id: str, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(JobCostSnapshot).where(JobCostSnapshot.job_id == job_id)
                             .order_by(JobCostSnapshot.created_at.desc()))).scalars().all()
    return {"snapshots": [{
        "id": str(s.id), "trigger": s.trigger, "costing_status": s.costing_status, "baseline_status": s.baseline_status,
        "revenue": float(s.revenue) if s.revenue is not None else None,
        "estimated_total_cost": float(s.estimated_total_cost) if s.estimated_total_cost is not None else None,
        "actual_total_cost": float(s.actual_total_cost) if s.actual_total_cost is not None else None,
        "actual_gross_profit": float(s.actual_gross_profit) if s.actual_gross_profit is not None else None,
        "actual_gross_margin_percent": float(s.actual_gross_margin_percent) if s.actual_gross_margin_percent is not None else None,
        "total_variance": float(s.total_variance) if s.total_variance is not None else None,
        "created_by": s.created_by, "created_at": s.created_at.isoformat() if s.created_at else None,
    } for s in rows]}


@router.get("/{job_id}/cost-snapshots/{snap_id}")
async def get_cost_snapshot(job_id: str, snap_id: str, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    s = await db.get(JobCostSnapshot, snap_id)
    if not s or str(s.job_id) != job_id:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {"id": str(s.id), "trigger": s.trigger, "created_at": s.created_at.isoformat() if s.created_at else None,
            "created_by": s.created_by, "costing_status": s.costing_status, "payload": s.payload}


@router.post("/{job_id}/cost-snapshots", status_code=201)
async def create_cost_snapshot(job_id: str, payload: SnapshotIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    snap = await jc.build_snapshot(db, j, payload.trigger or "manual", user.email)
    await db.commit()
    await log_action(db, user=user, action="job.cost_snapshot.create", entity_type="job", entity_id=j.id,
                     detail={"trigger": snap.trigger, "status": snap.costing_status}, request=request)
    return {"id": str(snap.id), "trigger": snap.trigger, "costing_status": snap.costing_status,
            "created_at": snap.created_at.isoformat() if snap.created_at else None}
