from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Territory, User, CanvassSection, CanvassSectionProperty, Property
from core import get_current_user, require_roles, MANAGE_ROLES, log_action
from schemas_canvass import (
    CanvassSectionCreate, CanvassSectionUpdate, CanvassSectionOut,
    CanvassSectionPreviewIn, CanvassSectionPreviewOut, CanvassSectionPropertyOut,
)
import geo
from services import canvass as svc

router = APIRouter(prefix="/api/canvass-sections", tags=["canvass-sections"])


async def _validate_geometry(geometry: dict, territory: Territory):
    if not geo.is_valid_polygon(geometry):
        raise HTTPException(status_code=422, detail="geometry must be a valid GeoJSON Polygon with at least 3 unique points")
    if not geo.polygon_fully_contained(geometry, territory.geometry):
        raise HTTPException(status_code=422, detail="Canvass Section must be fully contained within its Territory")


async def _resolve_assignee(db: AsyncSession, assigned_user_id):
    if not assigned_user_id:
        return None
    u = await db.get(User, assigned_user_id)
    if not u:
        raise HTTPException(status_code=422, detail="Assigned user not found")
    if not u.is_active:
        raise HTTPException(status_code=422, detail="Assigned user is inactive")
    return u


async def _out(db: AsyncSession, s: CanvassSection) -> CanvassSectionOut:
    total, dnk = await svc.section_counts(db, s.id)
    name = None
    if s.assigned_user_id:
        u = await db.get(User, s.assigned_user_id)
        name = (u.full_name or u.email) if u else None
    return CanvassSectionOut(
        id=str(s.id), territory_id=str(s.territory_id), name=s.name, description=s.description,
        color=s.color, geometry=s.geometry, assigned_user_id=str(s.assigned_user_id) if s.assigned_user_id else None,
        assigned_user_name=name, active=s.active, property_count=total, do_not_knock_count=dnk,
        created_by=s.created_by, created_at=s.created_at,
    )


@router.get("", response_model=list[CanvassSectionOut])
async def list_sections(
    territory_id: str | None = Query(None),
    assigned_user_id: str | None = Query(None),
    active: bool | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    stmt = select(CanvassSection)
    if territory_id:
        stmt = stmt.where(CanvassSection.territory_id == territory_id)
    if assigned_user_id:
        stmt = stmt.where(CanvassSection.assigned_user_id == assigned_user_id)
    if active is not None:
        stmt = stmt.where(CanvassSection.active.is_(active))
    stmt = stmt.order_by(CanvassSection.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [await _out(db, s) for s in rows]


@router.post("/preview", response_model=CanvassSectionPreviewOut)
async def preview_section(payload: CanvassSectionPreviewIn, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    territory = await db.get(Territory, payload.territory_id)
    if not territory:
        raise HTTPException(status_code=404, detail="Territory not found")
    await _validate_geometry(payload.geometry, territory)
    return CanvassSectionPreviewOut(**await svc.preview(db, territory.id, payload.geometry, payload.exclude_section_id))


@router.post("", response_model=CanvassSectionOut, status_code=201)
async def create_section(payload: CanvassSectionCreate, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    territory = await db.get(Territory, payload.territory_id)
    if not territory:
        raise HTTPException(status_code=404, detail="Territory not found")
    await _validate_geometry(payload.geometry, territory)
    await _resolve_assignee(db, payload.assigned_user_id)
    prev = await svc.preview(db, territory.id, payload.geometry)
    if prev["conflict_count"] > 0:
        raise HTTPException(status_code=409, detail={
            "code": "membership_conflict",
            "message": f"{prev['conflict_count']} property(ies) already belong to another active Canvass Section. Resolve the overlap before saving.",
            "conflicts": prev["conflicts"],
        })
    s = CanvassSection(
        territory_id=territory.id, name=payload.name, description=payload.description,
        color=payload.color, geometry=payload.geometry,
        assigned_user_id=payload.assigned_user_id or None, active=payload.active, created_by=user.email,
    )
    db.add(s)
    await db.flush()
    count = await svc.recompute_membership(db, s)
    await db.commit()
    await db.refresh(s)
    await log_action(db, user=user, action="canvass_section.create", entity_type="canvass_section", entity_id=s.id,
                     detail={"name": s.name, "territory_id": str(s.territory_id), "assigned_user_id": str(s.assigned_user_id) if s.assigned_user_id else None, "property_count": count}, request=request)
    return await _out(db, s)


@router.get("/{section_id}", response_model=CanvassSectionOut)
async def get_section(section_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = await db.get(CanvassSection, section_id)
    if not s:
        raise HTTPException(status_code=404, detail="Canvass Section not found")
    return await _out(db, s)


@router.put("/{section_id}", response_model=CanvassSectionOut)
async def update_section(section_id: str, payload: CanvassSectionUpdate, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    s = await db.get(CanvassSection, section_id)
    if not s:
        raise HTTPException(status_code=404, detail="Canvass Section not found")
    territory = await db.get(Territory, s.territory_id)
    geometry_changed = False
    if payload.geometry is not None:
        await _validate_geometry(payload.geometry, territory)
        prev = await svc.preview(db, s.territory_id, payload.geometry, exclude_section_id=s.id)
        if prev["conflict_count"] > 0:
            raise HTTPException(status_code=409, detail={
                "code": "membership_conflict",
                "message": f"{prev['conflict_count']} property(ies) already belong to another active Canvass Section. Resolve the overlap before saving.",
                "conflicts": prev["conflicts"],
            })
        s.geometry = payload.geometry
        geometry_changed = True
    if payload.name is not None:
        s.name = payload.name
    if payload.description is not None:
        s.description = payload.description
    if payload.color is not None:
        s.color = payload.color
    if payload.active is not None:
        s.active = payload.active
    assign_changed = False
    if "assigned_user_id" in payload.model_fields_set:
        await _resolve_assignee(db, payload.assigned_user_id)
        s.assigned_user_id = payload.assigned_user_id or None
        assign_changed = True
    if geometry_changed:
        await svc.recompute_membership(db, s)
    await db.commit()
    await db.refresh(s)
    action = "canvass_section.assign" if (assign_changed and not geometry_changed) else "canvass_section.update"
    await log_action(db, user=user, action=action, entity_type="canvass_section", entity_id=s.id,
                     detail={"name": s.name, "territory_id": str(s.territory_id), "assigned_user_id": str(s.assigned_user_id) if s.assigned_user_id else None}, request=request)
    return await _out(db, s)


@router.delete("/{section_id}")
async def delete_section(section_id: str, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    s = await db.get(CanvassSection, section_id)
    if not s:
        raise HTTPException(status_code=404, detail="Canvass Section not found")
    name = s.name
    await db.delete(s)  # membership rows cascade; Property/Visits/Leads preserved
    await db.commit()
    await log_action(db, user=user, action="canvass_section.delete", entity_type="canvass_section", entity_id=section_id, detail={"name": name}, request=request)
    return {"ok": True, "properties_preserved": True}


@router.get("/{section_id}/properties", response_model=list[CanvassSectionPropertyOut])
async def section_properties(section_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = await db.get(CanvassSection, section_id)
    if not s:
        raise HTTPException(status_code=404, detail="Canvass Section not found")
    rows = (await db.execute(
        select(Property).join(CanvassSectionProperty, CanvassSectionProperty.property_id == Property.id)
        .where(CanvassSectionProperty.section_id == s.id)
    )).scalars().all()
    return [CanvassSectionPropertyOut(
        id=str(p.id), formatted_address=p.formatted_address, latitude=p.latitude, longitude=p.longitude,
        property_type=p.property_type, owner_occupied=p.owner_occupied, do_not_knock=p.do_not_knock,
    ) for p in rows]
