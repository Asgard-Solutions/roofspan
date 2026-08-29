"""Canonical Property-detail builder — the SINGLE source of truth for a home's detail representation.

Both `GET /api/properties/{id}` (Office) and `GET /api/mobile/properties/{id}` (Field) build their
response from `build_property_detail()`, so the two apps can never drift into different interpretations
of the same Property. Routes may differ in AUTHORIZATION, but never in the shape/content they construct.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from models import Property, PropertyContact, Visit, Lead


def occupancy_status(owner_occupied: bool | None) -> str:
    if owner_occupied is True:
        return "owned"
    if owner_occupied is False:
        return "rented"
    return "unknown"


def location_diagnostics(p: Property) -> dict | None:
    raw = p.raw if isinstance(p.raw, dict) else {}
    loc = raw.get("roofspan_location")
    return dict(loc) if isinstance(loc, dict) else None


async def build_property_detail(db: AsyncSession, p: Property) -> dict:
    """Assemble the canonical Property detail. `lead_id` is the most-recent NON-archived lead for the
    property (archived leads never make a property appear to have an active lead)."""
    contacts = (await db.execute(
        select(PropertyContact).where(PropertyContact.property_id == p.id).order_by(PropertyContact.kind)
    )).scalars().all()
    visits = (await db.execute(
        select(Visit).where(Visit.property_id == p.id).order_by(Visit.visited_at.desc())
    )).scalars().all()
    lead = (await db.execute(
        select(Lead).where(Lead.property_id == p.id, Lead.status != "archived").order_by(Lead.created_at.desc())
    )).scalars().first()

    return {
        "id": str(p.id),
        "external_id": p.external_id,
        "source": p.source,
        "territory_id": str(p.territory_id) if p.territory_id else None,
        "formatted_address": p.formatted_address,
        "address_line1": p.address_line1,
        "city": p.city,
        "state": p.state,
        "zip_code": p.zip_code,
        "latitude": p.latitude,
        "longitude": p.longitude,
        "property_type": p.property_type,
        "bedrooms": p.bedrooms,
        "bathrooms": p.bathrooms,
        "square_footage": p.square_footage,
        "year_built": p.year_built,
        "owner_occupied": p.owner_occupied,
        "do_not_knock": p.do_not_knock,
        "do_not_knock_reason": p.do_not_knock_reason,
        "notes": p.notes,
        "contacts": [
            {
                "id": str(c.id), "kind": c.kind, "name": c.name, "contact_type": c.contact_type,
                "mailing_address": c.mailing_address, "phone": c.phone, "email": c.email,
            }
            for c in contacts
        ],
        "visits": [
            {
                "id": str(v.id), "outcome": v.outcome, "notes": v.notes,
                "visited_at": v.visited_at, "user_email": v.user_email, "created_at": v.created_at,
            }
            for v in visits
        ],
        "lead_id": str(lead.id) if lead else None,
        "location_diagnostics": location_diagnostics(p),
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


async def conflict_if_stale(db: AsyncSession, p: Property, expected_updated_at) -> None:
    """Optimistic-concurrency guard. If the caller sent an `expected_updated_at` token that no longer
    matches the property's current `updated_at`, raise 409 with the AUTHORITATIVE server snapshot under
    detail.server — exactly the shape the Field queue captures to drive the conflict banner."""
    if expected_updated_at is None:
        return
    if p.updated_at != expected_updated_at:
        raise HTTPException(status_code=409, detail={"code": "conflict", "server": await build_property_detail(db, p)})
