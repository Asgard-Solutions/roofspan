"""Roof Measurement Increment B/C API: versioned takeoff templates, estimate generation and guards."""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User, MeasurementRevision
from takeoff_models import TakeoffTemplate, TakeoffTemplateRevision
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_takeoff import TakeoffTemplateIn, TakeoffTemplateRevisionIn, TakeoffApplyIn
from services import takeoff as svc
from services import measurements as measurement_svc
from services.measurement_validation import build_warnings

router = APIRouter(prefix="/api/takeoff", tags=["takeoff"])


@router.get("/settings")
async def get_settings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return {"default_waste_percent": await svc.company_default_waste(db)}


@router.put("/settings")
async def put_settings(default_waste_percent: float = Query(...), request: Request = None,
                       user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    value = await svc.set_company_default_waste(db, default_waste_percent)
    await log_action(db, user=user, action="takeoff.settings.update", entity_type="takeoff_settings",
                     entity_id="default", detail={"default_waste_percent": value}, request=request)
    await db.commit()
    return {"default_waste_percent": value}


@router.get("/templates")
async def list_templates(active: bool | None = Query(None), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(TakeoffTemplate).order_by(TakeoffTemplate.name)
    if active is not None:
        stmt = stmt.where(TakeoffTemplate.active.is_(active))
    templates = (await db.execute(stmt)).scalars().all()
    out = []
    for template in templates:
        latest = (await db.execute(select(TakeoffTemplateRevision).where(
            TakeoffTemplateRevision.template_id == template.id
        ).order_by(TakeoffTemplateRevision.revision_number.desc()))).scalars().first()
        out.append({
            "id": str(template.id), "name": template.name, "description": template.description,
            "active": template.active, "created_at": template.created_at,
            "latest_revision": await svc.template_revision_out(db, latest) if latest else None,
        })
    return out


@router.post("/templates", status_code=201)
async def create_template(payload: TakeoffTemplateIn, request: Request,
                          user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    template = TakeoffTemplate(name=payload.name, description=payload.description, active=payload.active, created_by=user.email)
    db.add(template)
    await db.flush()
    rev_payload = TakeoffTemplateRevisionIn(default_waste_percent=payload.default_waste_percent,
                                            notes=payload.notes, rules=payload.rules)
    rev = await svc.create_template_revision(db, template, rev_payload, user)
    await log_action(db, user=user, action="takeoff.template.create", entity_type="takeoff_template",
                     entity_id=str(template.id), detail={"revision": rev.revision_number}, request=request)
    await db.commit()
    return {"id": str(template.id), "name": template.name, "description": template.description,
            "active": template.active, "latest_revision": await svc.template_revision_out(db, rev)}


@router.patch("/templates/{template_id}/active")
async def set_template_active(template_id: str, active: bool = Query(...), request: Request = None,
                              user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    template = await db.get(TakeoffTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Takeoff template not found")
    template.active = active
    await log_action(db, user=user, action="takeoff.template.active", entity_type="takeoff_template",
                     entity_id=str(template.id), detail={"active": active}, request=request)
    await db.commit()
    return {"id": str(template.id), "active": template.active}


@router.get("/templates/{template_id}/revisions")
async def list_template_revisions(template_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    template = await db.get(TakeoffTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Takeoff template not found")
    rows = (await db.execute(select(TakeoffTemplateRevision).where(
        TakeoffTemplateRevision.template_id == template.id
    ).order_by(TakeoffTemplateRevision.revision_number.desc()))).scalars().all()
    return [await svc.template_revision_out(db, r) for r in rows]


@router.post("/templates/{template_id}/revisions", status_code=201)
async def create_template_revision(template_id: str, payload: TakeoffTemplateRevisionIn, request: Request,
                                   user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    template = await db.get(TakeoffTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Takeoff template not found")
    rev = await svc.create_template_revision(db, template, payload, user)
    await log_action(db, user=user, action="takeoff.template.revision.create", entity_type="takeoff_template",
                     entity_id=str(template.id), detail={"revision": rev.revision_number}, request=request)
    await db.commit()
    return await svc.template_revision_out(db, rev)


@router.get("/templates/revisions/{revision_id}")
async def get_template_revision(revision_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rev = await db.get(TakeoffTemplateRevision, revision_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Takeoff template revision not found")
    return await svc.template_revision_out(db, rev)


@router.post("/estimates/{estimate_id}/preview")
async def preview_takeoff(estimate_id: str, payload: TakeoffApplyIn,
                          user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    return await svc.preview(db, estimate_id, payload)


@router.post("/estimates/{estimate_id}/apply")
async def apply_takeoff(estimate_id: str, payload: TakeoffApplyIn, request: Request,
                        user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    result = await svc.apply(db, estimate_id, payload, user)
    await log_action(db, user=user, action="takeoff.apply", entity_type="estimate", entity_id=estimate_id,
                     detail={
                         "takeoff_id": result["takeoff_id"],
                         "measurement_revision_id": result["measurement_revision_id"],
                         "measurement_revision_number": result["measurement_revision_number"],
                         "template_revision_id": result["template_revision_id"],
                         "template_revision_number": result["template_revision_number"],
                         "estimate_waste_override": payload.estimate_waste_override,
                         "structure_waste_overrides": payload.structure_waste_overrides,
                         "drip_edge_override_lf": payload.drip_edge_override_lf,
                         "generated_lines": len(result["created_line_ids"]),
                     }, request=request)
    await db.commit()
    return result


@router.get("/estimates/{estimate_id}/status")
async def takeoff_status(estimate_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.status(db, estimate_id)


@router.get("/measurements/{revision_id}/warnings")
async def measurement_warnings(revision_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rev = await db.get(MeasurementRevision, revision_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Measurement revision not found")
    measurement = await measurement_svc.build_out(db, rev)
    return {"revision_id": revision_id, "warnings": build_warnings(measurement)}
