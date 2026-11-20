from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Crew, Job, User
from core import require_roles, MANAGE_ROLES, log_action

router = APIRouter(prefix="/api/crews", tags=["crews"])

ACTIVE_JOB = ("created", "pending", "scheduled", "in_progress")


class CrewIn(BaseModel):
    name: str
    notes: str | None = None


class CrewPatch(BaseModel):
    name: str | None = None
    notes: str | None = None
    active: bool | None = None


def _clean(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise HTTPException(status_code=422, detail="Crew name is required")
    return n[:120]


async def _name_taken(db, name: str, exclude=None) -> bool:
    stmt = select(Crew.id).where(func.lower(Crew.name) == name.lower())
    if exclude:
        stmt = stmt.where(Crew.id != exclude)
    return (await db.execute(stmt)).first() is not None


def _out(c: Crew, counts: dict) -> dict:
    total, active = counts.get(c.id, (0, 0))
    return {"id": str(c.id), "name": c.name, "notes": c.notes, "active": c.active, "job_count": total, "active_job_count": active}


async def _counts(db) -> dict:
    rows = (await db.execute(select(Job.crew_id, func.count(), func.count().filter(Job.status.in_(ACTIVE_JOB)))
                             .where(Job.crew_id.is_not(None)).group_by(Job.crew_id))).all()
    return {r[0]: (r[1], r[2]) for r in rows}


@router.get("")
async def list_crews(active: bool | None = Query(None), user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    stmt = select(Crew).order_by(func.lower(Crew.name))
    if active is not None:
        stmt = stmt.where(Crew.active == active)
    counts = await _counts(db)
    return [_out(c, counts) for c in (await db.execute(stmt)).scalars().all()]


@router.post("", status_code=201)
async def create_crew(payload: CrewIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    name = _clean(payload.name)
    if await _name_taken(db, name):
        raise HTTPException(status_code=409, detail="A crew with this name already exists")
    c = Crew(name=name, notes=payload.notes)
    db.add(c)
    await db.commit()
    await log_action(db, user=user, action="crew.create", entity_type="crew", entity_id=c.id, detail={"name": name}, request=request)
    return _out(c, {})


@router.put("/{crew_id}")
async def update_crew(crew_id: str, payload: CrewPatch, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    c = await db.get(Crew, crew_id)
    if not c:
        raise HTTPException(status_code=404, detail="Crew not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        name = _clean(data["name"])
        if await _name_taken(db, name, exclude=c.id):
            raise HTTPException(status_code=409, detail="A crew with this name already exists")
        c.name = name
        # keep the legacy text column in sync for older clients
        await db.execute(update(Job).where(Job.crew_id == c.id).values(assigned_to=name))
    if "notes" in data:
        c.notes = data["notes"]
    if data.get("active") is not None:
        c.active = data["active"]
    await db.commit()
    await log_action(db, user=user, action="crew.update", entity_type="crew", entity_id=c.id, detail=data, request=request)
    return _out(c, await _counts(db))


@router.delete("/{crew_id}")
async def delete_crew(crew_id: str, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    c = await db.get(Crew, crew_id)
    if not c:
        raise HTTPException(status_code=404, detail="Crew not found")
    used = (await db.execute(select(func.count()).select_from(Job).where(Job.crew_id == c.id))).scalar()
    if used:
        raise HTTPException(status_code=409, detail="This crew is on jobs. Deactivate it instead so job history keeps the crew.")
    await db.delete(c)
    await db.commit()
    await log_action(db, user=user, action="crew.delete", entity_type="crew", entity_id=crew_id, detail={"name": c.name}, request=request)
    return {"ok": True}
