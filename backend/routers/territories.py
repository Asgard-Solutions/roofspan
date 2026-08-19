from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Territory, Property, User
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_phase2 import TerritoryIn, TerritoryUpdate, TerritoryOut

router = APIRouter(prefix="/api/territories", tags=["territories"])


def _validate_polygon(geometry: dict):
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise HTTPException(status_code=422, detail="geometry must be a GeoJSON Polygon")
    coords = geometry.get("coordinates")
    if not coords or not isinstance(coords, list) or len(coords[0]) < 4:
        raise HTTPException(status_code=422, detail="Polygon must have at least 3 points")


async def _out(db: AsyncSession, t: Territory) -> TerritoryOut:
    count = (await db.execute(select(func.count(Property.id)).where(Property.territory_id == t.id))).scalar_one()
    return TerritoryOut(
        id=str(t.id), name=t.name, description=t.description, color=t.color,
        geometry=t.geometry, active=t.active, zip_code=t.zip_code, property_count=count,
        created_by=t.created_by, created_at=t.created_at,
    )


@router.get("", response_model=list[TerritoryOut])
async def list_territories(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Territory).order_by(Territory.created_at.desc()))).scalars().all()
    return [await _out(db, t) for t in rows]


@router.post("", response_model=TerritoryOut, status_code=201)
async def create_territory(payload: TerritoryIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    _validate_polygon(payload.geometry)
    t = Territory(name=payload.name, description=payload.description, color=payload.color,
                  geometry=payload.geometry, active=payload.active, zip_code=(payload.zip_code or None),
                  created_by=user.email)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    await log_action(db, user=user, action="territory.create", entity_type="territory", entity_id=t.id, detail={"name": t.name}, request=request)
    return await _out(db, t)


@router.get("/{territory_id}", response_model=TerritoryOut)
async def get_territory(territory_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    t = await db.get(Territory, territory_id)
    if not t:
        raise HTTPException(status_code=404, detail="Territory not found")
    return await _out(db, t)


@router.put("/{territory_id}", response_model=TerritoryOut)
async def update_territory(territory_id: str, payload: TerritoryUpdate, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    t = await db.get(Territory, territory_id)
    if not t:
        raise HTTPException(status_code=404, detail="Territory not found")
    if payload.geometry is not None:
        _validate_polygon(payload.geometry)
        t.geometry = payload.geometry
    if payload.name is not None:
        t.name = payload.name
    if payload.description is not None:
        t.description = payload.description
    if payload.color is not None:
        t.color = payload.color
    if payload.active is not None:
        t.active = payload.active
    await db.commit()
    await db.refresh(t)
    await log_action(db, user=user, action="territory.update", entity_type="territory", entity_id=t.id, request=request)
    return await _out(db, t)


@router.delete("/{territory_id}")
async def delete_territory(territory_id: str, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    t = await db.get(Territory, territory_id)
    if not t:
        raise HTTPException(status_code=404, detail="Territory not found")
    # Preserve properties: detach them from the territory instead of deleting business records.
    await db.execute(update(Property).where(Property.territory_id == t.id).values(territory_id=None))
    await db.delete(t)
    await db.commit()
    await log_action(db, user=user, action="territory.delete", entity_type="territory", entity_id=territory_id, request=request)
    return {"ok": True, "properties_preserved": True}
