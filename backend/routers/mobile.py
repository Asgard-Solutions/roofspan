"""Mobile field-app sync surface. Reuses existing business records; adds idempotent create,
simple conflict detection, and backend-authorized photo upload (no object-storage creds on device)."""
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Header, Query, UploadFile, File, Form
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, field_validator
from fastapi.responses import Response

from db import get_db
from models import Property, Visit, Inspection, Photo, Lead, Job, IdempotencyKey, User, CanvassSection, CanvassSectionProperty, Territory
from models import MeasurementSet, MeasurementRevision
from core import get_current_user, require_roles, FIELD_ROLES, MANAGE_ROLES, log_action
from services.object_storage import put_object, get_object
from services import mobile_authz as mauthz
from services import measurements as meas_svc
from services import measurement_sketches as sketch_svc
from services.property_detail import build_property_detail, conflict_if_stale
from visit_outcomes import validate_outcome
from schemas_measurements import MeasurementRevisionIn
from schemas_sketch import SketchWriteIn
from schemas_phase2 import PropertyDetail

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


async def _reserve_idem(db: AsyncSession, key: str | None, entity_type: str, fingerprint: str | None = None):
    """Atomically reserve an Idempotency-Key. Returns existing entity_id on replay, else None. When a
    request fingerprint is supplied, REUSING one key with a DIFFERENT body is rejected (409) rather than
    silently replaying the old result as though the new body were accepted (P0 data-loss guard)."""
    if not key:
        return None, False
    existing = await db.get(IdempotencyKey, key)
    if existing:
        if existing.entity_type != entity_type:
            raise HTTPException(status_code=409, detail="Idempotency-Key already used for a different operation")
        if fingerprint is not None and existing.request_fingerprint and existing.request_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="Idempotency-Key reused with a different request body")
        return existing.entity_id, True
    db.add(IdempotencyKey(key=key, entity_type=entity_type, entity_id="pending", request_fingerprint=fingerprint))
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await db.get(IdempotencyKey, key)
        return (existing.entity_id if existing else None), True
    return None, False


def _request_fingerprint(payload) -> str:
    import hashlib, json as _json
    try:
        body = payload.model_dump(mode="json")
    except Exception:
        body = payload.dict() if hasattr(payload, "dict") else {}
    return hashlib.sha256(_json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class MobileVisitIn(BaseModel):
    property_id: str
    outcome: str = "no_answer"
    notes: str | None = None
    visited_at: datetime | None = None
    expected_updated_at: datetime | None = None    # optimistic-concurrency token

    @field_validator("outcome")
    @classmethod
    def _valid_outcome(cls, v: str) -> str:
        return validate_outcome(v)


@router.post("/visits", status_code=201)
async def create_visit(payload: MobileVisitIn, request: Request, idempotency_key: str | None = Header(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    prior, replay = await _reserve_idem(db, idempotency_key, "mobile_visit")
    if replay and prior and prior != "pending":
        v = await db.get(Visit, prior)
        if v:
            return _visit_out(v, replayed=True)
    p = await mauthz.assert_property_access(db, payload.property_id, user)
    await conflict_if_stale(db, p, payload.expected_updated_at)
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
    fp = _request_fingerprint(payload)
    prior, replay = await _reserve_idem(db, idempotency_key, "mobile_measurement", fingerprint=fp)
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
            k.request_fingerprint = fp
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
    if meas_svc.token_conflict(rev.updated_at, if_match):
        out = await meas_svc.build_out(db, rev)
        raise HTTPException(status_code=409, detail={"message": "This measurement changed on the server since your copy.", "server": jsonable_encoder(out)})
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
    s = await meas_svc.find_measurement_set(db, inspection_id=inspection_id, lead_id=lead_id, property_id=property_id)
    if not s:
        return []
    return await meas_svc.list_revisions_for_set(db, s.id)


@router.get("/measurements/watermark")
async def measurements_watermark(lead_id: str | None = Query(None), property_id: str | None = Query(None), inspection_id: str | None = Query(None),
                                 user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """Lightweight change watermark for the LEAD-AWARE Field sync coordinator: per-revision updated_at +
    per-structure sketch document_version, so Field can tell whether its cached copy is current WITHOUT
    downloading the full business documents (or guessing from local-draft presence)."""
    if mauthz.is_sales(user) and not lead_id and not property_id:
        raise HTTPException(status_code=422, detail="lead_id or property_id is required")
    if lead_id:
        lead = await db.get(Lead, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        await mauthz.assert_lead_access(db, lead, user)
    if property_id:
        await mauthz.assert_property_access(db, property_id, user)
    s = await meas_svc.find_measurement_set(db, inspection_id=inspection_id, lead_id=lead_id, property_id=property_id)
    if not s:
        return {"measurement_set_id": None, "revisions": []}
    revs = (await db.execute(select(MeasurementRevision).where(MeasurementRevision.set_id == s.id).order_by(MeasurementRevision.revision_number.desc()))).scalars().all()
    out = []
    for rev in revs:
        sk = await sketch_svc.list_sketches(db, str(rev.id))
        out.append({
            "revision_id": str(rev.id), "revision_number": rev.revision_number, "status": rev.status,
            "updated_at": rev.updated_at,
            "sketches": [{"structure_id": str(x["structure_id"]), "document_version": x["document_version"], "updated_at": x.get("updated_at")} for x in (sk or [])],
        })
    return {"measurement_set_id": str(s.id), "revisions": out}


@router.get("/measurements/{revision_id}")
async def get_measurement(revision_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await db.get(MeasurementRevision, revision_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Measurement revision not found")
    s = await db.get(MeasurementSet, rev.set_id)
    await _assert_measurement_scope(db, s, user)
    return await meas_svc.build_out(db, rev)# ---- Field roof sketches (Plan 1 Task 3): mirror Office, same service, salesperson-scoped ----
@router.get("/measurements/{revision_id}/sketches")
async def mobile_list_sketches(revision_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await db.get(MeasurementRevision, revision_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Measurement revision not found")
    await _assert_measurement_scope(db, await db.get(MeasurementSet, rev.set_id), user)
    return await sketch_svc.list_sketches(db, revision_id)


@router.get("/measurements/{revision_id}/sketches/{structure_id}")
async def mobile_get_sketch(revision_id: str, structure_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await db.get(MeasurementRevision, revision_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Measurement revision not found")
    await _assert_measurement_scope(db, await db.get(MeasurementSet, rev.set_id), user)
    out = await sketch_svc.get_sketch(db, revision_id, structure_id)
    if not out:
        # Machine-readable "no sketch yet" contract: distinct from a missing/stale revision 404 above so
        # the mobile client can safely offer first-sketch creation (see mobile/src/sketchReadThrough.js).
        raise HTTPException(status_code=404, detail={"code": "sketch_not_found", "message": "No sketch for this structure yet"})
    return out


@router.put("/measurements/{revision_id}/sketches/{structure_id}")
async def mobile_put_sketch(revision_id: str, structure_id: str, payload: SketchWriteIn, request: Request,
                            user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await db.get(MeasurementRevision, revision_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Measurement revision not found")
    await _assert_measurement_scope(db, await db.get(MeasurementSet, rev.set_id), user)
    try:
        out = await sketch_svc.save_sketch(db, revision_id, structure_id, edit_mode=payload.edit_mode,
                                           document=payload.document, schema_version=payload.schema_version,
                                           expected_version=payload.expected_version, user=user)
    except sketch_svc.SketchConflict as c:
        server = dict(c.server)
        for k in ("created_at", "updated_at"):
            if server.get(k) is not None and not isinstance(server[k], str):
                server[k] = server[k].isoformat()
        raise HTTPException(status_code=409, detail={"message": "This roof sketch changed on the server since your copy.", "server": server})
    await log_action(db, user=user, action="measurement.sketch.update", entity_type="measurement_sketch", entity_id=structure_id, detail={"via": "mobile", "revision_id": revision_id}, request=request)
    await db.commit()
    return out




# ---- Photos (backend-authorized upload; object-storage creds never leave the server) ----
_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic", "image/heif": "heif"}
_CATS = {"Overview", "Roof", "Damage", "Exterior", "Interior", "Measurement", "Before", "After", "Other",
         "packing_slip", "receipt", "delivery_photo", "damage_photo", "other"}


@router.post("/photos", status_code=201)
async def upload_photo(request: Request, file: UploadFile = File(...), record_type: str = Form(...), record_id: str = Form(...),
                       description: str | None = Form(None), category: str | None = Form(None),
                       idempotency_key: str | None = Header(None),
                       user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    if record_type not in ("lead", "property", "visit", "inspection", "job", "purchase_order",
                           "measurement_revision", "measurement_structure", "measurement_facet", "measurement_penetration"):
        raise HTTPException(status_code=422, detail="Invalid record_type")
    if category and category not in _CATS:
        raise HTTPException(status_code=422, detail="Invalid category")
    if (file.content_type or "") not in _EXT:  # server-side file-type validation
        raise HTTPException(status_code=422, detail="Unsupported image type")
    await mauthz.assert_record_access(db, record_type, record_id, user)  # sales must own the parent record
    if record_type.startswith("measurement_"):  # never attach to a locked/immutable revision
        rev, _ = await meas_svc.resolve_revision_for_photo(db, record_type, record_id)
        if rev and rev.is_immutable:
            raise HTTPException(status_code=409, detail="This measurement revision is locked. Create a new revision to add photos.")
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


@router.delete("/photos/{photo_id}")
async def delete_photo(photo_id: str, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    ph = await db.get(Photo, photo_id)
    if not ph:
        raise HTTPException(status_code=404, detail="Photo not found")
    await mauthz.assert_record_access(db, ph.record_type, ph.record_id, user)
    if ph.record_type.startswith("measurement_"):  # locked revisions keep their photos immutable
        rev, _ = await meas_svc.resolve_revision_for_photo(db, ph.record_type, ph.record_id)
        if rev and rev.is_immutable:
            raise HTTPException(status_code=409, detail="This measurement revision is locked; its photos cannot be deleted.")
    await db.delete(ph)
    await db.commit()
    await log_action(db, user=user, action="photo.delete", entity_type=ph.record_type, entity_id=ph.record_id, request=request)
    return {"ok": True}


@router.get("/photos/measurement/{revision_id}")
async def list_measurement_photos(revision_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """All photos across a measurement revision and its structures/facets/penetrations (the
    'All measurement photos' view). Each row keeps its record_type/record_id for grouping."""
    rev = await db.get(MeasurementRevision, revision_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Measurement revision not found")
    await mauthz.assert_record_access(db, "measurement_revision", revision_id, user)
    ids = await meas_svc.revision_photo_records(db, rev)
    rows = (await db.execute(select(Photo).where(Photo.record_id.in_(ids), Photo.record_type.in_(meas_svc.PHOTO_RECORD_TYPES)).order_by(Photo.created_at.desc()))).scalars().all()
    return [_photo_out(p) for p in rows]


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


# ---------- Full authorized property map (Field "My Area" master dataset; NOT gated by canvass sections) ----------
async def _authorized_territory_ids(db: AsyncSession, user: User):
    """The set of territory ids a Field user may see on the map, or None for 'all' (management).
    Sales visibility = territories where the user has an assigned canvass section. This is independent
    of which section is *selected*, and independent of whether any section is currently assigned."""
    if not _sales_only(user):
        return None  # management: full authorized map
    rows = (await db.execute(
        select(CanvassSection.territory_id).where(
            CanvassSection.assigned_user_id == user.id, CanvassSection.active.is_(True))
    )).scalars().all()
    return {t for t in rows if t is not None}


def _valid_lonlat(lng, lat) -> bool:
    """Reject null / NaN / out-of-range coordinates so a bad row can never place a pin in the wrong
    place or drag the camera to a fabricated location. GeoJSON order is [longitude, latitude]."""
    try:
        lng = float(lng); lat = float(lat)
    except (TypeError, ValueError):
        return False
    if lng != lng or lat != lat:  # NaN
        return False
    return -180.0 <= lng <= 180.0 and -90.0 <= lat <= 90.0


async def _map_territory_scope(db: AsyncSession, user: User):
    """Territory ids a Field user may view on the map, or None = ALL active territories.

    AUTHORIZATION RULE (reported in the completion notes):
      - management (owner/admin/office/manager): None -> all active territories.
      - sales WITH assigned active canvass section(s): ONLY those sections' territories.
      - sales WITHOUT any assigned canvass section: None -> all active territories' MAP-SAFE layer.
        (The product model has no Territory.assigned_user_id; we do NOT fabricate one. Full Property
        DETAIL authorization remains separately enforced when a Property is actually opened.)"""
    if not _sales_only(user):
        return None
    rows = (await db.execute(
        select(CanvassSection.territory_id).where(
            CanvassSection.assigned_user_id == user.id, CanvassSection.active.is_(True))
    )).scalars().all()
    ids = {t for t in rows if t is not None}
    return ids or None


async def _authorized_territories(db: AsyncSession, user: User):
    """Active Territory records the Field user may see, ordered the SAME way Office orders them
    (created_at DESC) so Field/Office agree on territory ordering/selection."""
    scope = await _map_territory_scope(db, user)
    stmt = select(Territory).where(Territory.active.is_(True))
    if scope is not None:
        stmt = stmt.where(Territory.id.in_(scope))
    return (await db.execute(stmt.order_by(Territory.created_at.desc()))).scalars().all()


@router.get("/map/properties")
async def mobile_map_properties(
    territory_id: str | None = Query(None),
    zip: str | None = Query(None),
    user: User = Depends(require_roles(*FIELD_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """MAP-SAFE property GeoJSON for the Field 'My Area' layer, SCOPED to the selected area. Field never
    downloads the whole database: the caller passes `territory_id` (Territory area) or `zip` (ZIP area);
    a canvass section uses its own /canvass-sections/{id}/properties endpoint. Scope is server-authoritative
    — a sales user can never widen past their authorized territories. Only map-safe fields are exposed here;
    full property-detail authorization is enforced separately when a user opens a Property. Properties
    without usable/valid coordinates are excluded. Coordinates use the SAME stored Property lat/lng Office
    uses (no re-geocoding, no ZIP centroids, no lat/lng swap)."""
    scope = await _map_territory_scope(db, user)  # None => all active territories, set => sales scope
    stmt = select(Property).where(Property.latitude.isnot(None), Property.longitude.isnot(None))
    if territory_id:
        if scope is not None and territory_id not in {str(t) for t in scope}:
            raise HTTPException(status_code=403, detail="You are not authorized for this territory")
        stmt = stmt.where(Property.territory_id == territory_id)
    else:
        # No explicit territory: restrict to the caller's authorized territories (NEVER the full DB).
        if scope is not None:
            stmt = stmt.where(Property.territory_id.in_(scope))
        if zip:
            stmt = stmt.where(Property.zip_code == zip)
    rows = (await db.execute(stmt)).scalars().all()
    features = []
    for p in rows:
        if not _valid_lonlat(p.longitude, p.latitude):
            continue
        last_visit = (await db.execute(
            select(Visit).where(Visit.property_id == p.id).order_by(Visit.visited_at.desc()).limit(1)
        )).scalars().first()
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p.longitude, p.latitude]},
            "properties": {
                "id": str(p.id), "address": p.formatted_address, "do_not_knock": p.do_not_knock,
                "property_type": p.property_type, "owner_occupied": p.owner_occupied,
                "occupancy": ("owner" if p.owner_occupied is True else "tenant" if p.owner_occupied is False else "unknown"),
                "zip_code": p.zip_code or None,
                "territory_id": str(p.territory_id) if p.territory_id else None,
                "last_outcome": last_visit.outcome if last_visit else None,
                "last_visited_at": last_visit.visited_at.isoformat() if last_visit else None,
            },
        })
    return {"type": "FeatureCollection", "features": features}


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


# ---------- Unified Field area selector (ZIP datasets + assigned canvass areas) ----------
def _coords_bounds(coords):
    """[[minLng,minLat],[maxLng,maxLat]] (sw, ne) from a list of [lng,lat] pairs, or None if empty."""
    pts = [c for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2
           and isinstance(c[0], (int, float)) and isinstance(c[1], (int, float))]
    if not pts:
        return None
    lngs = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return [[min(lngs), min(lats)], [max(lngs), max(lats)]]


def _geometry_coords(geom):
    """Flatten all [lng,lat] positions out of a GeoJSON Polygon/MultiPolygon/Point geometry."""
    if not isinstance(geom, dict):
        return []
    t = geom.get("type")
    c = geom.get("coordinates")
    out = []
    if t == "Point" and isinstance(c, (list, tuple)):
        out.append(c)
    elif t == "Polygon" and isinstance(c, (list, tuple)):
        for ring in c:
            out.extend(ring or [])
    elif t == "MultiPolygon" and isinstance(c, (list, tuple)):
        for poly in c:
            for ring in (poly or []):
                out.extend(ring or [])
    return out


@router.get("/map/areas")
async def mobile_map_areas(user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """Field-authorized area selector, server-authoritative. Three area kinds, unified in one list and
    returned in DEFAULT-PRIORITY order (canvass_section, then territory, then zip):
      - type "canvass_section": the caller's ASSIGNED active sections (sales) or all active sections
        (management). Real stored GeoJSON geometry + polygon bounds.
      - type "territory": the same Office-managed Territory records (Territory + Property.territory_id).
        Carries territory id/name/color, stored GeoJSON geometry, property_count and polygon bounds.
      - type "zip": ZIP property datasets scoped to the caller's authorized territories. No stored polygon
        — bounds derived from member property coordinates (never a fabricated polygon)."""
    areas = []

    # 1) Assigned/visible canvass sections → real polygon areas (highest default priority).
    sections = await _visible_sections(db, user)
    for s in sections:
        count = (await db.execute(
            select(func.count(CanvassSectionProperty.id)).where(CanvassSectionProperty.section_id == s.id)
        )).scalar_one()
        areas.append({
            "type": "canvass_section", "id": str(s.id), "name": s.name, "color": s.color,
            "territory_id": str(s.territory_id) if s.territory_id else None,
            "geometry": s.geometry, "property_count": int(count),
            "bounds": _coords_bounds(_geometry_coords(s.geometry)),
        })

    # 2) Territories — same records/relationship Office uses; the Priority-2 default fallback.
    territories = await _authorized_territories(db, user)
    for t in territories:
        count = (await db.execute(
            select(func.count(Property.id)).where(
                Property.territory_id == t.id, Property.latitude.isnot(None), Property.longitude.isnot(None))
        )).scalar_one()
        areas.append({
            "type": "territory", "id": f"territory:{t.id}", "name": t.name, "color": t.color,
            "territory_id": str(t.id), "geometry": t.geometry, "property_count": int(count),
            "bounds": _coords_bounds(_geometry_coords(t.geometry)),
        })

    # 3) ZIP areas — strictly scoped to the caller's authorized territories.
    scope = await _map_territory_scope(db, user)  # None => management (all), set => sales scope
    zip_stmt = select(Property.zip_code, Property.city, Property.longitude, Property.latitude).where(
        Property.latitude.isnot(None), Property.longitude.isnot(None))
    if scope is not None:
        zip_stmt = zip_stmt.where(Property.territory_id.in_(scope))
    zip_rows = (await db.execute(zip_stmt)).all()

    groups = {}
    for zip_code, city, lng, lat in zip_rows:
        z = (zip_code or "").strip()
        if not z or not _valid_lonlat(lng, lat):
            continue
        g = groups.setdefault(z, {"coords": [], "cities": {}})
        g["coords"].append([lng, lat])
        if city:
            g["cities"][city] = g["cities"].get(city, 0) + 1
    for z, g in sorted(groups.items()):
        top_city = max(g["cities"].items(), key=lambda kv: kv[1])[0] if g["cities"] else None
        areas.append({
            "type": "zip", "id": f"zip:{z}", "zip_code": z,
            "name": f"{z} - {top_city}" if top_city else z,
            "color": None, "geometry": None, "territory_id": None,
            "property_count": len(g["coords"]), "bounds": _coords_bounds(g["coords"]),
        })

    return {"areas": areas}


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
@router.get("/properties/{property_id}", response_model=PropertyDetail)
async def get_property(property_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    p = await mauthz.assert_property_access(db, property_id, user)
    # SAME canonical builder + SAME Pydantic serialization as Office GET /api/properties/{id}.
    return PropertyDetail(**await build_property_detail(db, p))


class ConflictResolution(BaseModel):
    kept_mine: list[str] = []
    took_office: list[str] = []


# Human-readable labels for the merge audit note (matches the Field conflict-diff labels).
_RESOLUTION_FIELD_LABELS = {
    "do_not_knock": "Do Not Knock",
    "do_not_knock_reason": "DNK reason",
    "notes": "Notes",
    "outcome": "Visit outcome",
}


def _resolution_note(res: ConflictResolution) -> str:
    def _labels(fields):
        return ", ".join(_RESOLUTION_FIELD_LABELS.get(f, f) for f in fields)
    parts = []
    if res.kept_mine:
        parts.append(f"kept {_labels(res.kept_mine)} (yours)")
    if res.took_office:
        parts.append(f"took {_labels(res.took_office)} (Office)")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"— Sync conflict resolved {ts}: " + "; ".join(parts)


class MobilePropertyPatch(BaseModel):
    do_not_knock: bool | None = None
    do_not_knock_reason: str | None = None
    notes: str | None = None
    resolution: ConflictResolution | None = None   # merge audit note (kept-mine vs took-Office)
    expected_updated_at: datetime | None = None    # optimistic-concurrency token


@router.patch("/properties/{property_id}")
async def patch_property(property_id: str, payload: MobilePropertyPatch, request: Request,
                         user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """Authorized Field Property mutation (Do Not Knock on/off + notes). Property-level authorization is
    enforced server-side (canvass/lead/job scope for sales). DNK behavior mirrors Office exactly — it
    simply sets the same do_not_knock/reason columns (no divergent mobile rule)."""
    p = await mauthz.assert_property_access(db, property_id, user)
    await conflict_if_stale(db, p, payload.expected_updated_at)
    fields = payload.model_dump(exclude_unset=True)
    if "do_not_knock" in fields:
        p.do_not_knock = fields["do_not_knock"]
    if "do_not_knock_reason" in fields:
        p.do_not_knock_reason = fields["do_not_knock_reason"]
    if "notes" in fields:
        p.notes = fields["notes"]
    # Merge audit note: how the rep settled a sync conflict (which fields were kept-mine vs took-Office).
    # Appended to the property notes AND recorded in the audit log so Office can see how it was resolved.
    has_resolution = payload.resolution is not None and (payload.resolution.kept_mine or payload.resolution.took_office)
    if has_resolution:
        note = _resolution_note(payload.resolution)
        p.notes = f"{p.notes}\n{note}" if p.notes else note
    await db.commit()
    await db.refresh(p)
    if "do_not_knock" in fields:
        await log_action(db, user=user, action="property.do_not_knock", entity_type="property", entity_id=p.id, detail={"do_not_knock": p.do_not_knock, "via": "mobile"}, request=request)
    if has_resolution:
        await log_action(db, user=user, action="property.conflict_resolved", entity_type="property", entity_id=p.id,
                         detail={"kept_mine": payload.resolution.kept_mine, "took_office": payload.resolution.took_office, "via": "mobile"}, request=request)
    return PropertyDetail(**await build_property_detail(db, p))
