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
        stmt = select(MeasurementSet)
        if inspection_id:
            stmt = stmt.where(MeasurementSet.inspection_id == inspection_id)
        elif property_id:
            stmt = stmt.where(MeasurementSet.property_id == property_id)
        elif lead_id:
            stmt = stmt.where(MeasurementSet.lead_id == lead_id)
        else:
            raise HTTPException(status_code=400, detail="Provide inspection_id, property_id, lead_id or set_id")
        s = (await db.execute(stmt)).scalars().first()
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
    await db.commit()
    return out


@router.post("/{revision_id}/status", response_model=MeasurementRevisionOut)
async def change_status(revision_id: str, payload: StatusChangeIn, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rev = await _get_rev_or_404(db, revision_id)
    await svc.transition_status(db, rev, payload.to, user)
    out = await svc.build_out(db, rev)
    await log_action(db, user=user, action=f"measurement.status.{payload.to}", entity_type="measurement_revision", entity_id=str(rev.id), detail={"revision": rev.revision_number}, request=request)
    await db.commit()
    return out


@router.post("/{revision_id}/unlock", response_model=MeasurementRevisionOut)
async def unlock_revision(revision_id: str, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await _get_rev_or_404(db, revision_id)
    await svc.unlock_revision(db, rev, user)
    out = await svc.build_out(db, rev)
    await log_action(db, user=user, action="measurement.unlock", entity_type="measurement_revision", entity_id=str(rev.id), detail={"revision": rev.revision_number}, request=request)
    await db.commit()
    return out


@router.post("/{revision_id}/new-revision", response_model=MeasurementRevisionOut, status_code=201)
async def new_revision(revision_id: str, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    rev = await _get_rev_or_404(db, revision_id)
    new = await svc.clone_revision(db, rev, user)
    out = await svc.build_out(db, new)
    await log_action(db, user=user, action="measurement.new_revision", entity_type="measurement_revision", entity_id=str(new.id), detail={"from": rev.revision_number, "to": new.revision_number}, request=request)
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
