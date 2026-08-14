from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Route, RouteStop, Property, User
from core import get_current_user, require_roles, FIELD_ROLES, MANAGE_ROLES, log_action

router = APIRouter(prefix="/api/routes", tags=["routes"])

STOP_STATUSES = {"pending", "knocked", "skipped"}


class StopIn(BaseModel):
    property_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    sort: int = 0


class RouteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    territory_id: str | None = None
    assigned_user_id: str | None = None
    est_miles: float = 0
    stops: list[StopIn] = []


class AssignIn(BaseModel):
    user_id: str | None = None


class StopPatch(BaseModel):
    status: str | None = None
    note: str | None = None


async def _assignee_name(db: AsyncSession, uid) -> str | None:
    if not uid:
        return None
    u = await db.get(User, uid)
    return (u.full_name or u.email) if u else None


def _row(r: Route, name: str | None, counts: dict) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "territory_id": str(r.territory_id) if r.territory_id else None,
        "assigned_user_id": str(r.assigned_user_id) if r.assigned_user_id else None,
        "assigned_user_name": name,
        "status": r.status,
        "stop_count": r.stop_count,
        "est_miles": r.est_miles,
        "knocked": counts.get("knocked", 0),
        "skipped": counts.get("skipped", 0),
        "pending": counts.get("pending", 0),
        "created_by": r.created_by,
        "created_at": r.created_at,
    }


def _recompute_status(statuses: list[str]) -> str:
    done = sum(1 for s in statuses if s in ("knocked", "skipped"))
    if done == 0:
        return "assigned"
    if done < len(statuses):
        return "in_progress"
    return "completed"


@router.post("", status_code=201)
async def create_route(payload: RouteCreate, request: Request,
                       user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    if not payload.stops:
        raise HTTPException(status_code=422, detail="A route needs at least one stop")

    assignee_id = None
    if payload.assigned_user_id:
        target = await db.get(User, payload.assigned_user_id)
        if not target or not target.is_active:
            raise HTTPException(status_code=422, detail="Assignee must be an active user")
        assignee_id = target.id

    r = Route(
        name=payload.name.strip(),
        territory_id=payload.territory_id or None,
        assigned_user_id=assignee_id,
        est_miles=payload.est_miles,
        stop_count=len(payload.stops),
        status="assigned",
        created_by=user.email,
    )
    db.add(r)
    await db.flush()

    pids = [s.property_id for s in payload.stops if s.property_id]
    pmap: dict[str, Property] = {}
    if pids:
        props = (await db.execute(select(Property).where(Property.id.in_(pids)))).scalars().all()
        pmap = {str(p.id): p for p in props}

    for i, s in enumerate(sorted(payload.stops, key=lambda x: x.sort)):
        p = pmap.get(s.property_id) if s.property_id else None
        db.add(RouteStop(
            route_id=r.id,
            property_id=(p.id if p else None),
            sort=i,
            address=(p.formatted_address if p else ""),
            latitude=(s.latitude if s.latitude is not None else (p.latitude if p else None)),
            longitude=(s.longitude if s.longitude is not None else (p.longitude if p else None)),
            status="pending",
        ))
    await db.commit()
    await log_action(db, user=user, action="route.create", entity_type="route", entity_id=r.id,
                     detail={"name": r.name, "stops": r.stop_count,
                             "assigned_user_id": str(assignee_id) if assignee_id else None}, request=request)
    return await get_route(str(r.id), user, db)


@router.get("")
async def list_routes(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Route).order_by(Route.created_at.desc())
    if user.role == "sales":
        stmt = stmt.where(Route.assigned_user_id == user.id)
    rows = (await db.execute(stmt)).scalars().all()

    counts: dict = {}
    if rows:
        rids = [r.id for r in rows]
        cres = await db.execute(
            select(RouteStop.route_id, RouteStop.status, func.count())
            .where(RouteStop.route_id.in_(rids))
            .group_by(RouteStop.route_id, RouteStop.status)
        )
        for rid, st, c in cres.all():
            counts.setdefault(rid, {})[st] = c

    out = []
    for r in rows:
        out.append(_row(r, await _assignee_name(db, r.assigned_user_id), counts.get(r.id, {})))
    return out


@router.get("/{route_id}")
async def get_route(route_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.get(Route, route_id)
    if not r:
        raise HTTPException(status_code=404, detail="Route not found")
    if user.role == "sales" and r.assigned_user_id != user.id:
        raise HTTPException(status_code=403, detail="This route is not assigned to you")
    stops = (await db.execute(
        select(RouteStop).where(RouteStop.route_id == r.id).order_by(RouteStop.sort)
    )).scalars().all()
    counts: dict = {}
    for s in stops:
        counts[s.status] = counts.get(s.status, 0) + 1
    row = _row(r, await _assignee_name(db, r.assigned_user_id), counts)
    row["stops"] = [
        {
            "id": str(s.id),
            "property_id": str(s.property_id) if s.property_id else None,
            "sort": s.sort,
            "address": s.address,
            "latitude": s.latitude,
            "longitude": s.longitude,
            "status": s.status,
            "note": s.note,
        }
        for s in stops
    ]
    return row


@router.put("/{route_id}/assign")
async def assign_route(route_id: str, payload: AssignIn, request: Request,
                       user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    r = await db.get(Route, route_id)
    if not r:
        raise HTTPException(status_code=404, detail="Route not found")
    if payload.user_id:
        target = await db.get(User, payload.user_id)
        if not target or not target.is_active:
            raise HTTPException(status_code=422, detail="Assignee must be an active user")
        r.assigned_user_id = target.id
    else:
        r.assigned_user_id = None
    await db.commit()
    await log_action(db, user=user, action="route.assign", entity_type="route", entity_id=r.id,
                     detail={"assigned_user_id": str(r.assigned_user_id) if r.assigned_user_id else None}, request=request)
    return await get_route(route_id, user, db)


@router.put("/{route_id}/stops/{stop_id}")
async def update_stop(route_id: str, stop_id: str, payload: StopPatch, request: Request,
                      user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    r = await db.get(Route, route_id)
    if not r:
        raise HTTPException(status_code=404, detail="Route not found")
    if user.role == "sales" and r.assigned_user_id != user.id:
        raise HTTPException(status_code=403, detail="This route is not assigned to you")
    stop = await db.get(RouteStop, stop_id)
    if not stop or stop.route_id != r.id:
        raise HTTPException(status_code=404, detail="Stop not found")
    if payload.status is not None:
        if payload.status not in STOP_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid stop status")
        stop.status = payload.status
    if payload.note is not None:
        stop.note = payload.note
    await db.flush()

    statuses = (await db.execute(select(RouteStop.status).where(RouteStop.route_id == r.id))).scalars().all()
    r.status = _recompute_status(list(statuses))
    await db.commit()
    await log_action(db, user=user, action="route.stop.update", entity_type="route_stop", entity_id=stop.id,
                     detail={"route_id": str(r.id), "status": stop.status}, request=request)
    return await get_route(route_id, user, db)


@router.delete("/{route_id}", status_code=204)
async def delete_route(route_id: str, request: Request,
                       user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    r = await db.get(Route, route_id)
    if not r:
        raise HTTPException(status_code=404, detail="Route not found")
    await db.delete(r)
    await db.commit()
    await log_action(db, user=user, action="route.delete", entity_type="route", entity_id=route_id, request=request)
