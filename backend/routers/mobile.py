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
from models import MeasurementSet, MeasurementRevision
from core import get_current_user, require_roles, FIELD_ROLES, MANAGE_ROLES, log_action
from services.object_storage import put_object, get_object
from services import mobile_authz as mauthz
from services import measurements as meas_svc
from schemas_measurements import MeasurementRevisionIn

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
    p = await mauthz.assert_property_access(db, payload.property_id, user)
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
    if mauthz.is_sales(user):  # sales may only attach an inspection to their own lead/property
        if payload.lead_id:
            lead = await db.get(Lead, payload.lead_id)
            if not lead:
                raise HTTPException(status_code=404, detail="Lead not found")
            await mauthz.assert_lead_access(db, lead, user)
        if payload.property_id:
            await mauthz.assert_property_access(db, payload.property_id, user)
        if not payload.lead_id and not payload.property_id:
            raise HTTPException(status_code=403, detail="An inspection must be tied to your lead or property.")
    data = payload.model_dump()
    if not data.get("inspection_date"):
        data["inspection_date"] = datetime.now(timezone.utc)
    i = Inspection(**data, created_by=user.email)
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
    await mauthz.assert_inspection_access(db, i, user)
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
            "inspection_date": i.inspection_date.isoformat() if i.inspection_date else None,
            "inspector": i.inspector, "roof_condition": i.roof_condition, "findings": i.findings,
            "recommended_work": i.recommended_work, "measurements": i.measurements, "notes": i.notes,
            "if_match": _token(i), "created_by": i.created_by, "replayed": replayed}


# ---- Mobile inspection reads (salesperson-scoped) ----
@router.get("/inspections")
async def list_inspections(lead_id: str | None = Query(None), property_id: str | None = Query(None),
                           user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    if mauthz.is_sales(user) and not lead_id and not property_id:
        raise HTTPException(status_code=422, detail="lead_id or property_id is required")
    if lead_id:
        lead = await db.get(Lead, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        await mauthz.assert_lead_access(db, lead, user)
    if property_id:
        await mauthz.assert_property_access(db, property_id, user)
    stmt = select(Inspection).order_by(Inspection.created_at.desc())
    if lead_id:
        stmt = stmt.where(Inspection.lead_id == lead_id)
    if property_id:
        stmt = stmt.where(Inspection.property_id == property_id)
    return [_insp_out(i) for i in (await db.execute(stmt)).scalars().all()]


@router.get("/inspections/{inspection_id}")
async def get_inspection(inspection_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    i = await db.get(Inspection, inspection_id)
    if not i:
        raise HTTPException(status_code=404, detail="Inspection not found")
    await mauthz.assert_inspection_access(db, i, user)
    return _insp_out(i)

# ==========================================================================================
# Mobile Roof Measurements (Increment A) — offline-first, whole-document sync.
# The field app builds a full revision (structures/facets/edges/penetrations/summary) with client
# refs and POSTs it as one idempotent mutation. Draft/field-complete revisions can be replaced.
# ==========================================================================================
async def _assert_measurement_scope(db: AsyncSession, payload_or_set, user):
    """Sales may only touch measurements tied to their own lead/property."""
    if not mauthz.is_sales(user):
        return
    lead_id = getattr(payload_or_set, "lead_id", None)
    property_id = getattr(payload_or_set, "property_id", None)
    if lead_id:
        lead = await db.get(Lead, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        await mauthz.assert_lead_access(db, lead, user)
    if property_id:
        await mauthz.assert_property_access(db, property_id, user)
    if not lead_id and not property_id:
        raise HTTPException(status_code=403, detail="A measurement must be tied to your lead or property.")


@router.post("/measurements", status_code=201)
async def create_measurement(payload: MeasurementRevisionIn, request: Request, idempotency_key: str | None = Header(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    prior, replay = await _reserve_idem(db, idempotency_key, "mobile_measurement")
    if replay and prior and prior != "pending":
        rev = await db.get(MeasurementRevision, prior)
        if rev:
            out = await meas_svc.build_out(db, rev)
            out["replayed"] = True
            return out
    await _assert_measurement_scope(db, payload, user)
    rev = await meas_svc.create_revision(db, payload, user)
    if idempotency_key:
        k = await db.get(IdempotencyKey, idempotency_key)
        if k:
            k.entity_id = str(rev.id)
    out = await meas_svc.build_out(db, rev)
    await log_action(db, user=user, action="measurement.create", entity_type="measurement_revision", entity_id=rev.id, detail={"via": "mobile", "revision": rev.revision_number}, request=request)
    await db.commit()
    return out


@router.put("/measurements/{revision_id}")
async def update_measurement(revision_id: str, payload: MeasurementRevisionIn, request: Request, if_match: str | None = Header(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await db.get(MeasurementRevision, revision_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Measurement revision not found")
    s = await db.get(MeasurementSet, rev.set_id)
    await _assert_measurement_scope(db, s, user)
    token = rev.updated_at.isoformat() if rev.updated_at else None
    if if_match and token and if_match != token:
        out = await meas_svc.build_out(db, rev)
        raise HTTPException(status_code=409, detail={"message": "This measurement changed on the server since your copy.", "server": out})
    await meas_svc.replace_children(db, rev, payload)
    if payload.mark_field_complete and rev.status == "draft":
        await meas_svc.transition_status(db, rev, "field_complete", user)
    out = await meas_svc.build_out(db, rev)
    await log_action(db, user=user, action="measurement.update", entity_type="measurement_revision", entity_id=rev.id, detail={"via": "mobile"}, request=request)
    await db.commit()
    return out


@router.post("/measurements/{revision_id}/field-complete")
async def field_complete_measurement(revision_id: str, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await db.get(MeasurementRevision, revision_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Measurement revision not found")
    s = await db.get(MeasurementSet, rev.set_id)
    await _assert_measurement_scope(db, s, user)
    await meas_svc.transition_status(db, rev, "field_complete", user)
    out = await meas_svc.build_out(db, rev)
    await log_action(db, user=user, action="measurement.field_complete", entity_type="measurement_revision", entity_id=rev.id, detail={"via": "mobile"}, request=request)
    await db.commit()
    return out


@router.get("/measurements")
async def list_measurements(lead_id: str | None = Query(None), property_id: str | None = Query(None), inspection_id: str | None = Query(None),
                            user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    if mauthz.is_sales(user) and not lead_id and not property_id:
        raise HTTPException(status_code=422, detail="lead_id or property_id is required")
    if lead_id:
        lead = await db.get(Lead, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        await mauthz.assert_lead_access(db, lead, user)
    if property_id:
        await mauthz.assert_property_access(db, property_id, user)
    stmt = select(MeasurementSet)
    if inspection_id:
        stmt = stmt.where(MeasurementSet.inspection_id == inspection_id)
    elif lead_id:
        stmt = stmt.where(MeasurementSet.lead_id == lead_id)
    elif property_id:
        stmt = stmt.where(MeasurementSet.property_id == property_id)
    s = (await db.execute(stmt)).scalars().first()
    if not s:
        return []
    return await meas_svc.list_revisions_for_set(db, s.id)


@router.get("/measurements/{revision_id}")
async def get_measurement(revision_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await db.get(MeasurementRevision, revision_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Measurement revision not found")
    s = await db.get(MeasurementSet, rev.set_id)
    await _assert_measurement_scope(db, s, user)
    return await meas_svc.build_out(db, rev)




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
    await mauthz.assert_record_access(db, record_type, record_id, user)  # sales must own the parent record
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
async def list_photos(record_type: str = Query(...), record_id: str = Query(...), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    await mauthz.assert_record_access(db, record_type, record_id, user)
    rows = (await db.execute(select(Photo).where(Photo.record_type == record_type, Photo.record_id == record_id).order_by(Photo.created_at.desc()))).scalars().all()
    return [_photo_out(p) for p in rows]


@router.get("/photos/{photo_id}/content")
async def photo_content(photo_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    ph = await db.get(Photo, photo_id)
    if not ph:
        raise HTTPException(status_code=404, detail="Photo not found")
    await mauthz.assert_record_access(db, ph.record_type, ph.record_id, user)
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
    stmt = select(Lead).where(Lead.status != "archived").order_by(Lead.created_at.desc())
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
    features = []
    for p in rows:
        last_visit = (await db.execute(
            select(Visit).where(Visit.property_id == p.id).order_by(Visit.visited_at.desc()).limit(1)
        )).scalars().first()
        has_lead = (await db.execute(
            select(Lead.id).where(Lead.property_id == p.id, Lead.assigned_user_id == user.id, Lead.status != "archived").limit(1)
        )).first() is not None
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p.longitude, p.latitude]},
            "properties": {
                "id": str(p.id), "address": p.formatted_address, "do_not_knock": p.do_not_knock,
                "property_type": p.property_type, "owner_occupied": p.owner_occupied,
                "last_outcome": last_visit.outcome if last_visit else None,
                "last_visited_at": last_visit.visited_at.isoformat() if last_visit else None,
                "has_lead": has_lead,
            },
        })
    return {"section_id": str(s.id), "type": "FeatureCollection", "features": features}


# ============================================================================
# Mobile Lead CRUD (salesperson-authorized; server assigns to the caller)
# ============================================================================
class MobileLeadCreate(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    status: str | None = "new"
    notes: str | None = None
    property_id: str | None = None
    # NOTE: no assigned_user_id/assigned_to — assignment is always the caller, never client-chosen.


class MobileLeadPatch(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    status: str | None = None
    notes: str | None = None


def _lead_token(l: Lead) -> str | None:
    ts = getattr(l, "updated_at", None) or getattr(l, "created_at", None)
    return ts.isoformat() if ts else None


async def _lead_detail(db: AsyncSession, l: Lead, replayed: bool = False, existing: bool = False) -> dict:
    address = l.address
    do_not_knock = False
    visits = []
    if l.property_id:
        p = await db.get(Property, l.property_id)
        if p:
            address = p.formatted_address or address
            do_not_knock = p.do_not_knock
            vrows = (await db.execute(select(Visit).where(Visit.property_id == p.id).order_by(Visit.visited_at.desc()))).scalars().all()
            visits = [{"id": str(v.id), "outcome": v.outcome, "notes": v.notes,
                       "visited_at": v.visited_at.isoformat(), "user_email": v.user_email} for v in vrows]
    insp = (await db.execute(select(Inspection).where(Inspection.lead_id == l.id).order_by(Inspection.created_at.desc()))).scalars().first()
    return {
        "id": str(l.id), "name": l.name, "phone": l.phone, "email": l.email,
        "address": address, "status": l.status, "notes": l.notes,
        "property_id": str(l.property_id) if l.property_id else None,
        "assigned_user_id": str(l.assigned_user_id) if l.assigned_user_id else None,
        "created_by": l.created_by, "created_at": l.created_at.isoformat(),
        "do_not_knock": do_not_knock, "visits": visits,
        "inspection_id": str(insp.id) if insp else None,
        "if_match": _lead_token(l), "replayed": replayed, "existing": existing,
    }


@router.post("/leads", status_code=201)
async def create_lead(payload: MobileLeadCreate, request: Request, idempotency_key: str | None = Header(None),
                      user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    prior, replay = await _reserve_idem(db, idempotency_key, "mobile_lead")
    if replay and prior and prior != "pending":
        l = await db.get(Lead, prior)
        if l:
            return await _lead_detail(db, l, replayed=True)
    prop = None
    if payload.property_id:
        prop = await mauthz.assert_property_access(db, payload.property_id, user)  # sales must own the property
        # Dedupe: reuse an existing (non-archived) lead the caller already owns for this property.
        existing = (await db.execute(
            select(Lead).where(Lead.property_id == prop.id, Lead.assigned_user_id == user.id,
                               Lead.status != "archived").order_by(Lead.created_at.desc())
        )).scalars().first()
        if existing:
            if idempotency_key:
                k = await db.get(IdempotencyKey, idempotency_key)
                if k:
                    k.entity_id = str(existing.id)
                await db.commit()
            return await _lead_detail(db, existing, existing=True)
    name = payload.name or (prop.formatted_address if prop else None) or "New Lead"
    address = payload.address or (prop.formatted_address if prop else None)
    l = Lead(name=name, phone=payload.phone, email=payload.email, address=address,
             status=payload.status or "new", notes=payload.notes,
             property_id=prop.id if prop else None,
             assigned_user_id=user.id,  # SERVER-AUTHORITATIVE — never trust client assignment
             assigned_to=user.full_name or user.email, created_by=user.email)
    db.add(l)
    await db.flush()
    if idempotency_key:
        k = await db.get(IdempotencyKey, idempotency_key)
        if k:
            k.entity_id = str(l.id)
    await db.commit()
    await db.refresh(l)
    await log_action(db, user=user, action="lead.create", entity_type="lead", entity_id=l.id,
                     detail={"via": "mobile", "from_property": bool(prop)}, request=request)
    return await _lead_detail(db, l)


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    l = await db.get(Lead, lead_id)
    if not l:
        raise HTTPException(status_code=404, detail="Lead not found")
    await mauthz.assert_lead_access(db, l, user)
    return await _lead_detail(db, l)


@router.patch("/leads/{lead_id}")
async def update_lead(lead_id: str, payload: MobileLeadPatch, request: Request, if_match: str | None = Header(None),
                      user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    l = await db.get(Lead, lead_id)
    if not l:
        raise HTTPException(status_code=404, detail="Lead not found")
    await mauthz.assert_lead_access(db, l, user)
    server_token = _lead_token(l)
    if if_match and server_token and if_match != server_token:
        raise HTTPException(status_code=409, detail={"message": "This lead changed on the server since your copy.",
                                                     "server": await _lead_detail(db, l)})
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(l, k, v)
    await db.commit()
    await db.refresh(l)
    await log_action(db, user=user, action="lead.update", entity_type="lead", entity_id=l.id, detail={"via": "mobile"}, request=request)
    return await _lead_detail(db, l)


@router.delete("/leads/{lead_id}")
async def archive_lead(lead_id: str, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """Soft-archive (status='archived'). Records are never destroyed and stay visible/reversible in Office."""
    l = await db.get(Lead, lead_id)
    if not l:
        raise HTTPException(status_code=404, detail="Lead not found")
    await mauthz.assert_lead_access(db, l, user)
    l.status = "archived"
    await db.commit()
    await log_action(db, user=user, action="lead.archive", entity_type="lead", entity_id=l.id, detail={"via": "mobile"}, request=request)
    return {"id": str(l.id), "status": l.status, "archived": True}


# ============================================================================
# Mobile Job read/update (salesperson-authorized). No blank-create, no delete:
# Jobs originate from an accepted Quote and link to costing/inventory (Office workflow preserved).
# ============================================================================
_JOB_STATUSES = ["created", "pending", "scheduled", "in_progress", "completed", "cancelled"]


class MobileJobPatch(BaseModel):
    status: str | None = None
    scope: str | None = None
    notes: str | None = None
    schedule_notes: str | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None


def _job_token(j: Job) -> str | None:
    ts = getattr(j, "updated_at", None) or getattr(j, "created_at", None)
    return ts.isoformat() if ts else None


async def _job_detail(db: AsyncSession, j: Job) -> dict:
    from models import Customer, JobMaterial, Material
    cust = await db.get(Customer, j.customer_id) if j.customer_id else None
    prop = await db.get(Property, j.property_id) if j.property_id else None
    jms = (await db.execute(select(JobMaterial).where(JobMaterial.job_id == j.id))).scalars().all()
    materials = []
    for jm in jms:
        m = await db.get(Material, jm.material_id)
        materials.append({"id": str(jm.id), "material_name": m.name if m else "?",
                          "unit": jm.unit or (m.unit if m else "ea"), "planned_quantity": jm.planned_quantity})
    return {
        "id": str(j.id), "number": j.number, "status": j.status, "scope": j.scope, "notes": j.notes,
        "scheduled_start": j.scheduled_start.isoformat() if j.scheduled_start else None,
        "scheduled_end": j.scheduled_end.isoformat() if j.scheduled_end else None,
        "schedule_notes": j.schedule_notes, "assigned_to": j.assigned_to,
        "assigned_user_id": str(j.assigned_user_id) if j.assigned_user_id else None,
        "customer_name": cust.name if cust else None,
        "property_id": str(j.property_id) if j.property_id else None,
        "property_address": prop.formatted_address if prop else None,
        "materials": materials, "created_at": j.created_at.isoformat(), "if_match": _job_token(j),
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    await mauthz.assert_job_access(db, j, user)
    return await _job_detail(db, j)


@router.patch("/jobs/{job_id}")
async def update_job(job_id: str, payload: MobileJobPatch, request: Request, if_match: str | None = Header(None),
                     user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    await mauthz.assert_job_access(db, j, user)
    server_token = _job_token(j)
    if if_match and server_token and if_match != server_token:
        raise HTTPException(status_code=409, detail={"message": "This job changed on the server since your copy.",
                                                     "server": await _job_detail(db, j)})
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in _JOB_STATUSES:
        raise HTTPException(status_code=422, detail=f"Status must be one of {_JOB_STATUSES}")
    for k, v in data.items():
        setattr(j, k, v)
    # Preserve Office business rules on status transitions (idempotent).
    if data.get("status") in ("completed", "cancelled"):
        from services import inventory_ops as ops
        await ops.auto_release_reservations(db, j, user.email)
    if data.get("status") == "completed":
        from services import job_costing as jc
        await jc.build_snapshot(db, j, "completion", user.email)
    await db.commit()
    await db.refresh(j)
    await log_action(db, user=user, action="job.update", entity_type="job", entity_id=j.id, detail={"via": "mobile", "fields": list(data.keys())}, request=request)
    return await _job_detail(db, j)


# ============================================================================
# Mobile Property detail (salesperson-authorized; canvass/field context only)
# ============================================================================
@router.get("/properties/{property_id}")
async def get_property(property_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    p = await mauthz.assert_property_access(db, property_id, user)
    from models import PropertyContact
    owner = (await db.execute(select(PropertyContact).where(PropertyContact.property_id == p.id, PropertyContact.kind == "owner"))).scalars().first()
    vrows = (await db.execute(select(Visit).where(Visit.property_id == p.id).order_by(Visit.visited_at.desc()))).scalars().all()
    lead = (await db.execute(select(Lead).where(Lead.property_id == p.id, Lead.status != "archived").order_by(Lead.created_at.desc()))).scalars().first()
    return {
        "id": str(p.id), "formatted_address": p.formatted_address, "latitude": p.latitude, "longitude": p.longitude,
        "property_type": p.property_type, "owner_occupied": p.owner_occupied,
        "do_not_knock": p.do_not_knock, "do_not_knock_reason": p.do_not_knock_reason, "notes": p.notes,
        "owner_name": owner.name if owner else None, "owner_phone": owner.phone if owner else None,
        "existing_lead_id": str(lead.id) if lead else None,
        "visits": [{"id": str(v.id), "outcome": v.outcome, "notes": v.notes,
                    "visited_at": v.visited_at.isoformat(), "user_email": v.user_email} for v in vrows],
    }
