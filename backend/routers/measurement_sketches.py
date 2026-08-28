"""Office roof sketch API (Plan 1 Task 3)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User
from core import require_roles, FIELD_ROLES, log_action
from schemas_sketch import SketchWriteIn, SketchOut
from services import measurement_sketches as svc

router = APIRouter(prefix="/api/measurements", tags=["measurement-sketches"])


@router.get("/{revision_id}/sketches", response_model=list[SketchOut])
async def list_sketches(revision_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    return await svc.list_sketches(db, revision_id)


@router.get("/{revision_id}/sketches/{structure_id}", response_model=SketchOut)
async def get_sketch(revision_id: str, structure_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    out = await svc.get_sketch(db, revision_id, structure_id)
    if not out:
        raise HTTPException(status_code=404, detail="No sketch for this structure yet")
    return out


@router.put("/{revision_id}/sketches/{structure_id}", response_model=SketchOut)
async def put_sketch(revision_id: str, structure_id: str, payload: SketchWriteIn, request: Request,
                     user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    existed = await svc.get_sketch(db, revision_id, structure_id)
    try:
        out = await svc.save_sketch(db, revision_id, structure_id, edit_mode=payload.edit_mode,
                                    document=payload.document, schema_version=payload.schema_version,
                                    expected_version=payload.expected_version, user=user)
    except svc.SketchConflict as c:
        await log_action(db, user=user, action="measurement.sketch.conflict", entity_type="measurement_sketch", entity_id=structure_id, detail={"revision_id": revision_id}, request=request)
        raise HTTPException(status_code=409, detail={"message": "This roof sketch changed on the server since your copy.", "server": _jsonable(c.server)})
    await log_action(db, user=user, action="measurement.sketch.update" if existed else "measurement.sketch.create", entity_type="measurement_sketch", entity_id=structure_id, detail={"revision_id": revision_id, "document_version": out["document_version"]}, request=request)
    await db.commit()
    return out


def _jsonable(server: dict) -> dict:
    s = dict(server)
    for k in ("created_at", "updated_at"):
        if s.get(k) is not None and not isinstance(s[k], str):
            s[k] = s[k].isoformat()
    return s
