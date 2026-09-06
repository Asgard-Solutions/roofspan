"""Office Roof Measurement API (Increment A).

Full worksheet CRUD over the snapshot-revision model. Estimating/takeoff is intentionally out of
scope here (Increment B consumes these revisions as a stable read API).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import (
    User, MeasurementSet, MeasurementRevision, MeasurementStructure, MeasurementFacet,
    MeasurementEdge, MeasurementPenetration, MeasurementSummary,
)
from core import get_current_user, require_roles, FIELD_ROLES, MANAGE_ROLES, log_action
from schemas_measurements import (
    MeasurementRevisionIn, MeasurementRevisionOut, MeasurementRevisionListItem, StatusChangeIn,
)
from services import measurements as svc
from services import office_outbox

router = APIRouter(prefix="/api/measurements", tags=["measurements"])


async def _get_rev_or_404(db: AsyncSession, revision_id: str) -> MeasurementRevision:
    rev = await db.get(MeasurementRevision, revision_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Measurement revision not found")
    return rev


@router.get("", response_model=list[MeasurementRevisionListItem])
async def list_revisions(
    inspection_id: str | None = Query(None), property_id: str | None = Query(None),
    lead_id: str | None = Query(None), set_id: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    if not set_id:
        s = await svc.find_measurement_set(db, inspection_id=inspection_id, property_id=property_id, lead_id=lead_id)
        if not (inspection_id or property_id or lead_id):
            raise HTTPException(status_code=400, detail="Provide inspection_id, property_id, lead_id or set_id")
        if not s:
            return []
        set_id = str(s.id)
    return await svc.list_revisions_for_set(db, set_id)


@router.get("/{revision_id}", response_model=MeasurementRevisionOut)
async def get_revision(revision_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rev = await _get_rev_or_404(db, revision_id)
    return await svc.build_out(db, rev)


@router.post("", response_model=MeasurementRevisionOut, status_code=201)
async def create_revision(payload: MeasurementRevisionIn, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await svc.create_revision(db, payload, user)
    out = await svc.build_out(db, rev)
    await log_action(db, user=user, action="measurement.create", entity_type="measurement_revision", entity_id=str(rev.id), detail={"revision": rev.revision_number}, request=request)
    await office_outbox.emit_for_revision(db, rev, "measurement.create")
    await db.commit()
    return out


@router.put("/{revision_id}", response_model=MeasurementRevisionOut)
async def replace_revision(revision_id: str, payload: MeasurementRevisionIn, request: Request, if_match: str | None = Header(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await _get_rev_or_404(db, revision_id)
    # Optimistic concurrency: if the caller's base version differs from the current server version, another
    # surface (e.g. a synced Field save) already advanced this revision — refuse to silently overwrite it.
    # Tolerant compare: the response serializes updated_at as '...Z' while isoformat() yields '...+00:00'.
    if svc.token_conflict(rev.updated_at, if_match):
        out = await svc.build_out(db, rev)
        raise HTTPException(status_code=409, detail={"message": "This measurement changed on the server since your copy.", "server": jsonable_encoder(out)})
    await svc.replace_children(db, rev, payload)
    out = await svc.build_out(db, rev)
    await log_action(db, user=user, action="measurement.update", entity_type="measurement_revision", entity_id=str(rev.id), detail={"revision": rev.revision_number}, request=request)
    await office_outbox.emit_for_revision(db, rev, "measurement.update")
    await db.commit()
    return out


@router.post("/{revision_id}/status", response_model=MeasurementRevisionOut)
async def change_status(revision_id: str, payload: StatusChangeIn, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rev = await _get_rev_or_404(db, revision_id)
    await svc.transition_status(db, rev, payload.to, user)
    out = await svc.build_out(db, rev)
    await log_action(db, user=user, action=f"measurement.status.{payload.to}", entity_type="measurement_revision", entity_id=str(rev.id), detail={"revision": rev.revision_number}, request=request)
    await office_outbox.emit_for_revision(db, rev, f"measurement.status.{payload.to}")
    await db.commit()
    return out


@router.post("/{revision_id}/unlock", response_model=MeasurementRevisionOut)
async def unlock_revision(revision_id: str, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await _get_rev_or_404(db, revision_id)
    await svc.unlock_revision(db, rev, user)
    out = await svc.build_out(db, rev)
    await log_action(db, user=user, action="measurement.unlock", entity_type="measurement_revision", entity_id=str(rev.id), detail={"revision": rev.revision_number}, request=request)
    await office_outbox.emit_for_revision(db, rev, "measurement.unlock")
    await db.commit()
    return out


@router.post("/{revision_id}/new-revision", response_model=MeasurementRevisionOut, status_code=201)
async def new_revision(revision_id: str, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await _get_rev_or_404(db, revision_id)
    new = await svc.clone_revision(db, rev, user)
    out = await svc.build_out(db, new)
    await log_action(db, user=user, action="measurement.new_revision", entity_type="measurement_revision", entity_id=str(new.id), detail={"from": rev.revision_number, "to": new.revision_number}, request=request)
    await office_outbox.emit_for_revision(db, new, "measurement.new_revision")
    await db.commit()
    return out


@router.delete("/{revision_id}")
async def delete_revision(revision_id: str, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await _get_rev_or_404(db, revision_id)
    if rev.status != "draft" or rev.is_immutable:
        raise HTTPException(status_code=409, detail="Only a Draft revision can be deleted")
    await db.execute(delete(MeasurementRevision).where(MeasurementRevision.id == rev.id))
    await log_action(db, user=user, action="measurement.delete", entity_type="measurement_revision", entity_id=str(rev.id), detail={"revision": rev.revision_number}, request=request)
    await db.commit()
    return {"ok": True}



@router.put("/{revision_id}/site-plan-assets")
async def save_site_plan_assets(revision_id: str, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """Persist the browser-rendered combined site plan (PNG for embedding + full PDF packet) on the
    revision. Keys are merged into the revision's site_plan JSON so they survive worksheet saves.
    Each save that carries a new image/PDF is kept as a versioned entry in site_plan.history (last
    HISTORY_CAP versions) so a rep can review/download an earlier plan; the top-level keys always
    point at the latest version (consumed by the quote/proposal embed + the saved badge)."""
    import base64
    from datetime import datetime, timezone
    from sqlalchemy.orm.attributes import flag_modified
    from services import object_storage
    HISTORY_CAP = 10
    rev = await _get_rev_or_404(db, revision_id)
    body = await request.json()
    sp = dict(rev.site_plan or {})
    history = list(sp.get("history") or [])
    next_version = max([int(h.get("version", 0)) for h in history], default=0) + 1

    def _store(b64, key, ctype):
        if not b64:
            return None
        raw = base64.b64decode(str(b64).split(",")[-1])
        object_storage.put_object(key, raw, content_type=ctype)
        return key

    img_key = _store(body.get("image_base64"), f"site-plans/{revision_id}-v{next_version}.png", "image/png")
    pdf_key = _store(body.get("pdf_base64"), f"site-plans/{revision_id}-v{next_version}.pdf", "application/pdf")
    fingerprint = body.get("fingerprint")
    now = datetime.now(timezone.utc).isoformat()

    if img_key or pdf_key:
        entry = {"version": next_version, "assets_updated_at": now}
        if img_key:
            entry["image_key"] = img_key
        if pdf_key:
            entry["pdf_key"] = pdf_key
        if fingerprint:
            entry["fingerprint"] = str(fingerprint)
        history.append(entry)
        sp["history"] = history[-HISTORY_CAP:]
        if img_key:
            sp["image_key"] = img_key
        if pdf_key:
            sp["pdf_key"] = pdf_key
        sp["assets_updated_at"] = now
    if fingerprint:
        sp["fingerprint"] = str(fingerprint)

    rev.site_plan = sp
    flag_modified(rev, "site_plan")
    await db.commit()
    return {"ok": True, "version": sp.get("history", [{}])[-1].get("version") if sp.get("history") else None,
            "assets_updated_at": sp.get("assets_updated_at"),
            "image_key": sp.get("image_key"), "pdf_key": sp.get("pdf_key")}


def _history_meta(sp: dict) -> list:
    """Downloadable metadata for each saved version (no raw storage keys leaked)."""
    out = []
    for h in (sp.get("history") or []):
        out.append({"version": int(h.get("version", 0)), "assets_updated_at": h.get("assets_updated_at"),
                    "fingerprint": h.get("fingerprint"), "label": h.get("label"),
                    "has_pdf": bool(h.get("pdf_key")),
                    "has_image": bool(h.get("image_key"))})
    out.sort(key=lambda x: x["version"], reverse=True)
    return out


async def _latest_site_plan_rev(db: AsyncSession, lead_id) -> MeasurementRevision | None:
    """Newest revision for a lead that has a saved site-plan PDF (used by the estimate/quote screens)."""
    if not lead_id:
        return None
    q = (select(MeasurementRevision)
         .join(MeasurementSet, MeasurementSet.id == MeasurementRevision.set_id)
         .where(MeasurementSet.lead_id == lead_id)
         .order_by(MeasurementRevision.created_at.desc()))
    for rev in (await db.execute(q)).scalars().all():
        if (rev.site_plan or {}).get("pdf_key"):
            return rev
    return None


@router.get("/{revision_id}/site-plan.pdf")
async def get_site_plan_pdf(revision_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from fastapi.responses import StreamingResponse
    from services import object_storage
    rev = await _get_rev_or_404(db, revision_id)
    key = (rev.site_plan or {}).get("pdf_key")
    if not key:
        raise HTTPException(status_code=404, detail="No saved site plan for this revision")
    data = object_storage.get_object(key)
    return StreamingResponse(iter([data]), media_type="application/pdf",
                             headers={"Content-Disposition": 'inline; filename="site-plan.pdf"'})


@router.get("/{revision_id}/site-plan-history")
async def get_site_plan_history(revision_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rev = await _get_rev_or_404(db, revision_id)
    return {"versions": _history_meta(rev.site_plan or {})}


@router.get("/{revision_id}/site-plan-v/{version}.pdf")
async def get_site_plan_pdf_version(revision_id: str, version: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from fastapi.responses import StreamingResponse
    from services import object_storage
    rev = await _get_rev_or_404(db, revision_id)
    entry = next((h for h in (rev.site_plan or {}).get("history") or [] if int(h.get("version", -1)) == version), None)
    key = entry.get("pdf_key") if entry else None
    if not key:
        raise HTTPException(status_code=404, detail="No saved site plan for that version")
    data = object_storage.get_object(key)
    return StreamingResponse(iter([data]), media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="site-plan-v{version}.pdf"'})


@router.get("/{revision_id}/site-plan-v/{version}.png")
async def get_site_plan_image_version(revision_id: str, version: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Thumbnail image for one saved version (used by the history 'Version Compare' preview)."""
    from fastapi.responses import StreamingResponse
    from services import object_storage
    rev = await _get_rev_or_404(db, revision_id)
    entry = next((h for h in (rev.site_plan or {}).get("history") or [] if int(h.get("version", -1)) == version), None)
    key = entry.get("image_key") if entry else None
    if not key:
        raise HTTPException(status_code=404, detail="No saved site-plan image for that version")
    data = object_storage.get_object(key)
    return StreamingResponse(iter([data]), media_type="image/jpeg",
                             headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/{revision_id}/site-plan-v/{version}")
async def delete_site_plan_version(revision_id: str, version: int, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """Delete one saved site-plan version from the history. If the deleted version was the latest,
    the top-level pointers (pdf_key/image_key/assets_updated_at/fingerprint) fall back to the newest
    remaining version; if none remain they are cleared."""
    import os
    from sqlalchemy.orm.attributes import flag_modified
    from services import object_storage
    rev = await _get_rev_or_404(db, revision_id)
    sp = dict(rev.site_plan or {})
    history = list(sp.get("history") or [])
    entry = next((h for h in history if int(h.get("version", -1)) == version), None)
    if not entry:
        raise HTTPException(status_code=404, detail="No saved site plan for that version")
    history = [h for h in history if int(h.get("version", -1)) != version]

    # Best-effort remove the underlying objects (local disk only; the managed proxy has no delete API).
    base = object_storage._local_dir()
    if base:
        for k in (entry.get("pdf_key"), entry.get("image_key")):
            if not k:
                continue
            try:
                p = object_storage._local_path(base, k)
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

    sp["history"] = history
    if history:
        latest = max(history, key=lambda h: int(h.get("version", 0)))
        sp["pdf_key"] = latest.get("pdf_key")
        sp["image_key"] = latest.get("image_key")
        sp["assets_updated_at"] = latest.get("assets_updated_at")
        sp["fingerprint"] = latest.get("fingerprint")
    else:
        for k in ("pdf_key", "image_key", "assets_updated_at", "fingerprint"):
            sp.pop(k, None)
    rev.site_plan = sp
    flag_modified(rev, "site_plan")
    await db.commit()
    await log_action(db, user=user, action="measurement.site_plan.delete_version", entity_type="measurement_revision", entity_id=str(rev.id), detail={"version": version}, request=request)
    return {"ok": True, "versions": _history_meta(sp)}


@router.post("/{revision_id}/site-plan-v/{version}/restore")
async def restore_site_plan_version(revision_id: str, version: int, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """Make an older saved version the current one: copy its assets into a fresh version at the top
    and re-point the top-level pointers at it (the stored/attached plan, not the live editor geometry)."""
    from datetime import datetime, timezone
    from sqlalchemy.orm.attributes import flag_modified
    from services import object_storage
    rev = await _get_rev_or_404(db, revision_id)
    sp = dict(rev.site_plan or {})
    history = list(sp.get("history") or [])
    src = next((h for h in history if int(h.get("version", -1)) == version), None)
    if not src:
        raise HTTPException(status_code=404, detail="No saved site plan for that version")
    next_version = max([int(h.get("version", 0)) for h in history], default=0) + 1
    now = datetime.now(timezone.utc).isoformat()
    entry = {"version": next_version, "assets_updated_at": now}

    def _copy(src_key, ext, ctype):
        if not src_key:
            return None
        raw = object_storage.get_object(src_key)
        nk = f"site-plans/{revision_id}-v{next_version}.{ext}"
        object_storage.put_object(nk, raw, content_type=ctype)
        return nk

    if (pk := _copy(src.get("pdf_key"), "pdf", "application/pdf")):
        entry["pdf_key"] = pk
    if (ik := _copy(src.get("image_key"), "png", "image/png")):
        entry["image_key"] = ik
    if src.get("fingerprint"):
        entry["fingerprint"] = src["fingerprint"]
    entry["label"] = (f'{src["label"]} (restored)' if src.get("label") else f"restored from v{version}")[:120]
    history.append(entry)
    sp["history"] = history[-10:]
    sp["pdf_key"] = entry.get("pdf_key")
    sp["image_key"] = entry.get("image_key")
    sp["assets_updated_at"] = now
    sp["fingerprint"] = entry.get("fingerprint")
    rev.site_plan = sp
    flag_modified(rev, "site_plan")
    await db.commit()
    await log_action(db, user=user, action="measurement.site_plan.restore_version", entity_type="measurement_revision", entity_id=str(rev.id), detail={"restored_from": version, "new_version": next_version}, request=request)
    return {"ok": True, "versions": _history_meta(sp)}


@router.patch("/{revision_id}/site-plan-v/{version}")
async def label_site_plan_version(revision_id: str, version: int, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """Set/clear a short note on a saved version so history is easy to scan."""
    from sqlalchemy.orm.attributes import flag_modified
    rev = await _get_rev_or_404(db, revision_id)
    body = await request.json()
    label = (body.get("label") or "").strip()[:120]
    sp = dict(rev.site_plan or {})
    history = list(sp.get("history") or [])
    entry = next((h for h in history if int(h.get("version", -1)) == version), None)
    if not entry:
        raise HTTPException(status_code=404, detail="No saved site plan for that version")
    if label:
        entry["label"] = label
    else:
        entry.pop("label", None)
    sp["history"] = history
    rev.site_plan = sp
    flag_modified(rev, "site_plan")
    await db.commit()
    return {"ok": True, "versions": _history_meta(sp)}


@router.get("/lead/{lead_id}/site-plan")
async def lead_site_plan_meta(lead_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rev = await _latest_site_plan_rev(db, lead_id)
    if not rev:
        return {"available": False}
    sp = rev.site_plan or {}
    return {"available": True, "revision_id": str(rev.id), "assets_updated_at": sp.get("assets_updated_at")}


@router.get("/lead/{lead_id}/site-plan.pdf")
async def lead_site_plan_pdf(lead_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from fastapi.responses import StreamingResponse
    from services import object_storage
    rev = await _latest_site_plan_rev(db, lead_id)
    key = (rev.site_plan or {}).get("pdf_key") if rev else None
    if not key:
        raise HTTPException(status_code=404, detail="No saved site plan for this lead")
    data = object_storage.get_object(key)
    return StreamingResponse(iter([data]), media_type="application/pdf",
                             headers={"Content-Disposition": 'inline; filename="site-plan.pdf"'})
