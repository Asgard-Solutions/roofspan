from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Property, PropertyContact, Visit, Lead, Territory, User
from core import get_current_user, require_roles, MANAGE_ROLES, FIELD_ROLES, log_action
from schemas_phase2 import (
    PropertyOut, PropertyDetail, ContactOut, VisitOut, VisitIn,
    PropertyCreate, PropertyPatch, ConvertLeadIn, LeadOut,
)

router = APIRouter(prefix="/api/properties", tags=["properties"])


def _prop_out(p: Property) -> PropertyOut:
    return PropertyOut(
        id=str(p.id), external_id=p.external_id, source=p.source,
        territory_id=str(p.territory_id) if p.territory_id else None,
        formatted_address=p.formatted_address, address_line1=p.address_line1,
        city=p.city, state=p.state, zip_code=p.zip_code,
        latitude=p.latitude, longitude=p.longitude, property_type=p.property_type,
        bedrooms=p.bedrooms, bathrooms=p.bathrooms, square_footage=p.square_footage,
        year_built=p.year_built, owner_occupied=p.owner_occupied,
        do_not_knock=p.do_not_knock, do_not_knock_reason=p.do_not_knock_reason,
        notes=p.notes, created_at=p.created_at,
    )


@router.get("", response_model=list[PropertyOut])
async def list_properties(
    territory_id: str | None = Query(None),
    do_not_knock: bool | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(500, le=2000),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Property)
    if territory_id:
        stmt = stmt.where(Property.territory_id == territory_id)
    if do_not_knock is not None:
        stmt = stmt.where(Property.do_not_knock == do_not_knock)
    if q:
        stmt = stmt.where(Property.formatted_address.ilike(f"%{q}%"))
    stmt = stmt.order_by(Property.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [_prop_out(p) for p in rows]


@router.get("/geojson")
async def properties_geojson(
    territory_id: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Property).where(Property.latitude.isnot(None), Property.longitude.isnot(None))
    if territory_id:
        stmt = stmt.where(Property.territory_id == territory_id)
    rows = (await db.execute(stmt)).scalars().all()
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p.longitude, p.latitude]},
            "properties": {
                "id": str(p.id),
                "address": p.formatted_address,
                "do_not_knock": p.do_not_knock,
                "property_type": p.property_type,
            },
        }
        for p in rows
    ]
    return {"type": "FeatureCollection", "features": features}


@router.post("", response_model=PropertyOut, status_code=201)
async def create_property(payload: PropertyCreate, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    fa = f"{payload.address_line1}, {payload.city}, {payload.state} {payload.zip_code}".strip(", ")
    p = Property(
        source="manual", territory_id=payload.territory_id, address_line1=payload.address_line1,
        city=payload.city, state=payload.state, zip_code=payload.zip_code, formatted_address=fa,
        latitude=payload.latitude, longitude=payload.longitude, property_type=payload.property_type,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    if payload.owner_name:
        db.add(PropertyContact(property_id=p.id, kind="owner", name=payload.owner_name, contact_type="Individual"))
        await db.commit()
    await log_action(db, user=user, action="property.create", entity_type="property", entity_id=p.id, request=request)
    return _prop_out(p)


@router.get("/{property_id}", response_model=PropertyDetail)
async def get_property(property_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Property, property_id)
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")
    contacts = (await db.execute(select(PropertyContact).where(PropertyContact.property_id == p.id))).scalars().all()
    visits = (await db.execute(select(Visit).where(Visit.property_id == p.id).order_by(Visit.visited_at.desc()))).scalars().all()
    lead = (await db.execute(select(Lead).where(Lead.property_id == p.id).order_by(Lead.created_at.desc()))).scalars().first()
    base = _prop_out(p).model_dump()
    return PropertyDetail(
        **base,
        contacts=[ContactOut(id=str(c.id), kind=c.kind, name=c.name, contact_type=c.contact_type, mailing_address=c.mailing_address, phone=c.phone, email=c.email) for c in contacts],
        visits=[VisitOut(id=str(v.id), visited_at=v.visited_at, user_email=v.user_email, outcome=v.outcome, notes=v.notes, created_at=v.created_at) for v in visits],
        lead_id=str(lead.id) if lead else None,
    )


@router.patch("/{property_id}", response_model=PropertyOut)
async def patch_property(property_id: str, payload: PropertyPatch, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    p = await db.get(Property, property_id)
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")
    fields = payload.model_dump(exclude_unset=True)
    if "do_not_knock" in fields:
        p.do_not_knock = fields["do_not_knock"]
    if "do_not_knock_reason" in fields:
        p.do_not_knock_reason = fields["do_not_knock_reason"]
    if "notes" in fields:
        p.notes = fields["notes"]
    if "territory_id" in fields:
        p.territory_id = fields["territory_id"]
    await db.commit()
    await db.refresh(p)
    if "do_not_knock" in fields:
        await log_action(db, user=user, action="property.do_not_knock", entity_type="property", entity_id=p.id, detail={"do_not_knock": p.do_not_knock}, request=request)
    return _prop_out(p)


@router.post("/{property_id}/visits", response_model=VisitOut, status_code=201)
async def create_visit(property_id: str, payload: VisitIn, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    p = await db.get(Property, property_id)
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")
    v = Visit(
        property_id=p.id, user_id=user.id, user_email=user.email,
        visited_at=payload.visited_at or datetime.now(timezone.utc),
        outcome=payload.outcome, notes=payload.notes,
    )
    db.add(v)
    if payload.outcome == "do_not_knock" and not p.do_not_knock:
        p.do_not_knock = True
        p.do_not_knock_reason = "Marked during visit"
    await db.commit()
    await db.refresh(v)
    await log_action(db, user=user, action="visit.create", entity_type="property", entity_id=p.id, detail={"outcome": v.outcome}, request=request)
    return VisitOut(id=str(v.id), visited_at=v.visited_at, user_email=v.user_email, outcome=v.outcome, notes=v.notes, created_at=v.created_at)


@router.post("/{property_id}/convert-to-lead", response_model=LeadOut, status_code=201)
async def convert_to_lead(property_id: str, payload: ConvertLeadIn, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    p = await db.get(Property, property_id)
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")
    name = payload.name.strip()
    if not name:
        owner = (await db.execute(select(PropertyContact).where(PropertyContact.property_id == p.id, PropertyContact.kind == "owner"))).scalars().first()
        name = owner.name if owner else p.formatted_address
    lead = Lead(
        property_id=p.id, source_visit_id=payload.visit_id, name=name,
        phone=payload.phone, email=payload.email, address=p.formatted_address,
        status="new", notes=payload.notes, created_by=user.email,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    await log_action(db, user=user, action="lead.create", entity_type="lead", entity_id=lead.id, detail={"property_id": str(p.id)}, request=request)
    return LeadOut(
        id=str(lead.id), property_id=str(lead.property_id), name=lead.name, phone=lead.phone,
        email=lead.email, address=lead.address, status=lead.status, notes=lead.notes,
        created_by=lead.created_by, created_at=lead.created_at, property_address=p.formatted_address,
    )
