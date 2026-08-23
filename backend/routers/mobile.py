"""Mobile field-app sync surface. Reuses existing business records; adds idempotent create,
simple conflict detection, and backend-authorized photo upload (no object-storage creds on device)."""
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Header, Query, UploadFile, File, Form
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from fastapi.responses import Response

from db import get_db
from models import Property, Visit, Inspection, Photo, Lead, Job, IdempotencyKey, User, CanvassSection, CanvassSectionProperty
from core import get_current_user, require_roles, FIELD_ROLES, MANAGE_ROLES, log_action
from offsite_backup import put_object, get_object

router = APIRouter(prefix="/api/mobile", tags=["mobile"])


def _vtuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except (ValueError, AttributeError):
        return (0,)


async def require_min_mobile_version(x_roofspan_app_version: str | None = Header(default=None)):
    """Version negotiation: reject Mobile clients below the minimum supported app version.

    An absent header is allowed (older clients / non-mobile callers); a present-but-too-old version
    is rejected with 426 so an outdated client cannot make incompatible API assumptions.
    """
    from licensing import config as lic_config
    if x_roofspan_app_version and _vtuple(x_roofspan_app_version) < _vtuple(lic_config.MIN_MOBILE_VERSION):
        raise HTTPException(
            status_code=426,
            detail={"code": "must_update", "message": "A newer version of RoofSpan Mobile is required to connect to your company's RoofSpan system.",
                    "min_supported": lic_config.MIN_MOBILE_VERSION},
        )


router.dependencies.append(Depends(require_min_mobile_version))


async def _reserve_idem(db: AsyncSession, key: str | None, entity_type: str):
    """Atomically reserve an Idempotency-Key. Returns existing entity_id on replay, else None."""
    if not key:
        return None, False
    existing = await db.get(IdempotencyKey, key)
    if existing:
        if existing.entity_type != entity_type:
            raise HTTPException(status_code=409, detail="Idempotency-Key already used for a different operation")
        return existing.entity_id, True
    db.add(IdempotencyKey(key=key, entity_type=entity_type, entity_id="pending"))
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await db.get(IdempotencyKey, key)
        return (existing.entity_id if existing else None), True
    return None, False


class MobileVisitIn(BaseModel):
    property_id: str
    outcome: str = "no_answer"
    notes: str | None = None
    visited_at: datetime | None = None


@router.post("/visits", status_code=201)
async def create_visit(payload: MobileVisitIn, request: Request, idempotency_key: str | None = Header(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    prior, replay = await _reserve_idem(db, idempotency_key, "mobile_visit")
    if replay and prior and prior != "pending":
        v = await db.get(Visit, prior)
        if v:
            return _visit_out(v, replayed=True)
    p = await db.get(Property, payload.property_id)
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")
    v = Visit(property_id=p.id, user_id=user.id, user_email=user.email,
              visited_at=payload.visited_at or datetime.now(timezone.utc), outcome=payload.outcome, notes=payload.notes)
    db.add(v)
    if payload.outcome == "do_not_knock" and not p.do_not_knock:
        p.do_not_knock = True
        p.do_not_knock_reason = "Marked during visit"
    await db.flush()
    if idempotency_key:
        k = await db.get(IdempotencyKey, idempotency_key)
        if k:
            k.entity_id = str(v.id)
    await db.commit()
    await db.refresh(v)
    await log_action(db, user=user, action="visit.create", entity_type="property", entity_id=p.id, detail={"outcome": v.outcome, "via": "mobile"}, request=request)
    return _visit_out(v)


def _visit_out(v: Visit, replayed: bool = False) -> dict:
    return {"id": str(v.id), "property_id": str(v.property_id), "outcome": v.outcome, "notes": v.notes,
            "visited_at": v.visited_at.isoformat(), "user_email": v.user_email, "replayed": replayed}


class MobileInspectionIn(BaseModel):
    lead_id: str | None = None
    customer_id: str | None = None
    property_id: str | None = None
    inspection_date: datetime | None = None
    inspector: str | None = None
    roof_condition: str | None = None
    findings: str | None = None
    recommended_work: str | None = None
    measurements: str | None = None
    notes: str | None = None


@router.post("/inspections", status_code=201)
async def create_inspection(payload: MobileInspectionIn, request: Request, idempotency_key: str | None = Header(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    prior, replay = await _reserve_idem(db, idempotency_key, "mobile_inspection")
    if replay and prior and prior != "pending":
        i = await db.get(Inspection, prior)
        if i:
            return _insp_out(i, replayed=True)
    i = Inspection(**payload.model_dump(), created_by=user.email)
    db.add(i)
    await db.flush()
    if idempotency_key:
        k = await db.get(IdempotencyKey, idempotency_key)
        if k:
            k.entity_id = str(i.id)
    await db.commit()
    await db.refresh(i)
    await log_action(db, user=user, action="inspection.create", entity_type="inspection", entity_id=i.id, detail={"via": "mobile"}, request=request)
    return _insp_out(i)


@router.patch("/inspections/{inspection_id}")
async def update_inspection(inspection_id: str, payload: MobileInspectionIn, request: Request, if_match: str | None = Header(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    i = await db.get(Inspection, inspection_id)
    if not i:
        raise HTTPException(status_code=404, detail="Inspection not found")
    # Simple visible conflict detection: client sends the updated_at it last saw via If-Match.
    server_token = _token(i)
    if if_match and server_token and if_match != server_token:
        raise HTTPException(status_code=409, detail={"message": "This inspection changed on the server since your copy.", "server": _insp_out(i)})
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(i, k, v)
    await db.commit()
    await db.refresh(i)
    await log_action(db, user=user, action="inspection.update", entity_type="inspection", entity_id=i.id, detail={"via": "mobile"}, request=request)
    return _insp_out(i)


def _token(i: Inspection) -> str | None:
    ts = getattr(i, "updated_at", None) or getattr(i, "created_at", None)
    return ts.isoformat() if ts else None


def _insp_out(i: Inspection, replayed: bool = False) -> dict:
    return {"id": str(i.id), "lead_id": str(i.lead_id) if i.lead_id else None,
            "property_id": str(i.property_id) if i.property_id else None,
            "customer_id": str(i.customer_id) if i.customer_id else None,
            "inspector": i.inspector, "roof_condition": i.roof_condition, "findings": i.findings,
            "recommended_work": i.recommended_work, "measurements": i.measurements, "notes": i.notes,
            "if_match": _token(i), "created_by": i.created_by, "replayed": replayed}


# ---- Photos (backend-authorized upload; object-storage creds never leave the server) ----
_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic", "image/heif": "heif"}
_CATS = {"Overview", "Roof", "Damage", "Exterior", "Interior", "Measurement", "Before", "After", "Other",
         "packing_slip", "receipt", "delivery_photo", "damage_photo", "other"}


@router.post("/photos", status_code=201)
async def upload_photo(request: Request, file: UploadFile = File(...), record_type: str = Form(...), record_id: str = Form(...),
                       description: str | None = Form(None), category: str | None = Form(None),
                       idempotency_key: str | None = Header(None),
                       user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    if record_type not in ("lead", "property", "visit", "inspection", "job", "purchase_order"):
        raise HTTPException(status_code=422, detail="Invalid record_type")
    if category and category not in _CATS:
        raise HTTPException(status_code=422, detail="Invalid category")
    if (file.content_type or "") not in _EXT:  # server-side file-type validation
        raise HTTPException(status_code=422, detail="Unsupported image type")
    prior, replay = await _reserve_idem(db, idempotency_key, "mobile_photo")
    if replay and prior and prior != "pending":
        ph = await db.get(Photo, prior)
        if ph:
            return _photo_out(ph, replayed=True)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty file")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Photo too large (max 15MB)")
    ext = _EXT.get(file.content_type or "", "bin")
    object_path = f"roofspan/photos/{record_type}/{record_id}/{uuid.uuid4()}.{ext}"
    try:
        put_object(object_path, data, file.content_type or "application/octet-stream")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Photo storage failed: {e.__class__.__name__}")
    ph = Photo(object_path=object_path, content_type=file.content_type or "application/octet-stream",
               record_type=record_type, record_id=record_id, description=description, category=category, uploaded_by=user.email)
    db.add(ph)
    await db.flush()
    if idempotency_key:
        k = await db.get(IdempotencyKey, idempotency_key)
        if k:
            k.entity_id = str(ph.id)
    await db.commit()
    await db.refresh(ph)
    await log_action(db, user=user, action="photo.upload", entity_type=record_type, entity_id=record_id, request=request)
    return _photo_out(ph)


@router.get("/photos")
async def list_photos(record_type: str = Query(...), record_id: str = Query(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Photo).where(Photo.record_type == record_type, Photo.record_id == record_id).order_by(Photo.created_at.desc()))).scalars().all()
    return [_photo_out(p) for p in rows]


@router.get("/photos/{photo_id}/content")
async def photo_content(photo_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ph = await db.get(Photo, photo_id)
    if not ph:
        raise HTTPException(status_code=404, detail="Photo not found")
    try:
        data = get_object(ph.object_path)
    except Exception:
        raise HTTPException(status_code=502, detail="Could not retrieve photo")
    return Response(content=data, media_type=ph.content_type)


def _photo_out(p: Photo, replayed: bool = False) -> dict:
    return {"id": str(p.id), "record_type": p.record_type, "record_id": p.record_id,
            "content_type": p.content_type, "description": p.description, "category": p.category,
            "uploaded_by": p.uploaded_by, "created_at": p.created_at.isoformat(),
            "content_url": f"/api/mobile/photos/{p.id}/content", "replayed": replayed}


# ---- My Assignments (backend is authoritative on what the field user may retrieve) ----
class AssignIn(BaseModel):
    user_id: str | None = None


def _field_only(user: User) -> bool:
    return user.role == "sales"


def _lead_row(l: Lead) -> dict:
    return {"id": str(l.id), "name": l.name, "address": l.address, "status": l.status,
            "property_id": str(l.property_id) if l.property_id else None,
            "assigned_user_id": str(l.assigned_user_id) if l.assigned_user_id else None, "phone": l.phone}


def _job_row(j: Job) -> dict:
    return {"id": str(j.id), "number": j.number, "scope": j.scope, "status": j.status,
            "scheduled_start": j.scheduled_start.isoformat() if j.scheduled_start else None,
            "assigned_to": j.assigned_to, "assigned_user_id": str(j.assigned_user_id) if j.assigned_user_id else None}


@router.get("/leads")
async def my_leads(scope: str = Query("auto"), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    stmt = select(Lead).order_by(Lead.created_at.desc())
    if _field_only(user) or scope == "mine":
        stmt = stmt.where(Lead.assigned_user_id == user.id)
    rows = (await db.execute(stmt)).scalars().all()
    return [_lead_row(l) for l in rows]


@router.get("/jobs")
async def my_jobs(scope: str = Query("auto"), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    stmt = select(Job).order_by(Job.created_at.desc())
    if _field_only(user) or scope == "mine":
        stmt = stmt.where(Job.assigned_user_id == user.id)
    rows = (await db.execute(stmt)).scalars().all()
    return [_job_row(j) for j in rows]


@router.post("/leads/{lead_id}/assign")
async def assign_lead(lead_id: str, payload: AssignIn, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    l = await db.get(Lead, lead_id)
    if not l:
        raise HTTPException(status_code=404, detail="Lead not found")
    l.assigned_user_id = uuid.UUID(payload.user_id) if payload.user_id else None
    await db.commit()
    return {"id": str(l.id), "assigned_user_id": str(l.assigned_user_id) if l.assigned_user_id else None}


@router.post("/jobs/{job_id}/assign")
async def assign_job(job_id: str, payload: AssignIn, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    j.assigned_user_id = uuid.UUID(payload.user_id) if payload.user_id else None
    await db.commit()
    return {"id": str(j.id), "assigned_user_id": str(j.assigned_user_id) if j.assigned_user_id else None}


# ---------- Canvass Sections (mobile field assignment; server-authoritative visibility) ----------
def _sales_only(user: User) -> bool:
    return user.role == "sales"


async def _visible_sections(db: AsyncSession, user: User):
    """Sales see only their own active sections. Management see all active sections."""
    stmt = select(CanvassSection).where(CanvassSection.active.is_(True))
    if _sales_only(user):
        stmt = stmt.where(CanvassSection.assigned_user_id == user.id)
    return (await db.execute(stmt.order_by(CanvassSection.created_at.desc()))).scalars().all()


@router.get("/canvass-sections")
async def mobile_canvass_sections(user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    sections = await _visible_sections(db, user)
    out = []
    for s in sections:
        count = (await db.execute(
            select(func.count(CanvassSectionProperty.id)).where(CanvassSectionProperty.section_id == s.id)
        )).scalar_one()
        out.append({
            "id": str(s.id), "territory_id": str(s.territory_id), "name": s.name,
            "color": s.color, "geometry": s.geometry, "property_count": count,
        })
    return {"sections": out}


async def _authorize_section(db: AsyncSession, section_id: str, user: User) -> CanvassSection:
    s = await db.get(CanvassSection, section_id)
    if not s or not s.active:
        raise HTTPException(status_code=404, detail="Canvass Section not found")
    # Server-authoritative isolation: a sales user may only access their OWN assigned section.
    if _sales_only(user) and s.assigned_user_id != user.id:
        raise HTTPException(status_code=403, detail="You are not assigned to this canvass section")
    return s


@router.get("/canvass-sections/{section_id}/properties")
async def mobile_canvass_section_properties(section_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    s = await _authorize_section(db, section_id, user)
    rows = (await db.execute(
        select(Property).join(CanvassSectionProperty, CanvassSectionProperty.property_id == Property.id)
        .where(CanvassSectionProperty.section_id == s.id,
               Property.latitude.isnot(None), Property.longitude.isnot(None))
    )).scalars().all()
    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [p.longitude, p.latitude]},
        "properties": {
            "id": str(p.id), "address": p.formatted_address, "do_not_knock": p.do_not_knock,
            "property_type": p.property_type, "owner_occupied": p.owner_occupied,
        },
    } for p in rows]
    return {"section_id": str(s.id), "type": "FeatureCollection", "features": features}

