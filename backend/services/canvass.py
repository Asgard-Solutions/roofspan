"""Canvass Section membership + overlap logic. Backend-authoritative (never browser-only).

Operates ONLY on properties already stored locally for the parent Territory — never calls RentCast.
Reuses geo.point_in_polygon (no PostGIS).
"""
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import Property, CanvassSection, CanvassSectionProperty, User
import geo


async def territory_properties(db: AsyncSession, territory_id) -> list[Property]:
    """Properties in the Territory that have valid coordinates (required for spatial comparison)."""
    rows = (await db.execute(
        select(Property).where(
            Property.territory_id == territory_id,
            Property.latitude.isnot(None),
            Property.longitude.isnot(None),
        )
    )).scalars().all()
    return list(rows)


def inside_ids(props: list[Property], geometry: dict) -> list:
    return [p.id for p in props if geo.point_in_polygon(p.longitude, p.latitude, geometry)]


async def _active_membership_index(db: AsyncSession, territory_id, exclude_section_id=None) -> dict:
    """Map property_id -> (section, assigned_user) for ACTIVE sections in this Territory."""
    stmt = (
        select(CanvassSectionProperty.property_id, CanvassSection, User)
        .join(CanvassSection, CanvassSection.id == CanvassSectionProperty.section_id)
        .join(User, User.id == CanvassSection.assigned_user_id, isouter=True)
        .where(CanvassSection.territory_id == territory_id, CanvassSection.active.is_(True))
    )
    if exclude_section_id is not None:
        stmt = stmt.where(CanvassSection.id != exclude_section_id)
    out = {}
    for prop_id, section, assignee in (await db.execute(stmt)).all():
        out[prop_id] = (section, assignee)
    return out


async def preview(db: AsyncSession, territory_id, geometry: dict, exclude_section_id=None) -> dict:
    props = await territory_properties(db, territory_id)
    by_id = {p.id: p for p in props}
    inside = inside_ids(props, geometry)
    membership = await _active_membership_index(db, territory_id, exclude_section_id)
    conflicts = []
    dnk = 0
    for pid in inside:
        p = by_id[pid]
        if p.do_not_knock:
            dnk += 1
        if pid in membership:
            section, assignee = membership[pid]
            conflicts.append({
                "property_id": str(pid),
                "address": p.formatted_address,
                "section_id": str(section.id),
                "section_name": section.name,
                "assigned_user_id": str(section.assigned_user_id) if section.assigned_user_id else None,
                "assigned_user_name": (assignee.full_name or assignee.email) if assignee else None,
            })
    return {
        "property_count": len(inside),
        "available_count": len(inside) - len(conflicts),
        "conflict_count": len(conflicts),
        "do_not_knock_count": dnk,
        "conflicts": conflicts,
    }


async def recompute_membership(db: AsyncSession, section: CanvassSection) -> int:
    """Delete stale membership then persist current in-polygon property ids. Returns count."""
    props = await territory_properties(db, section.territory_id)
    inside = inside_ids(props, section.geometry)
    await db.execute(delete(CanvassSectionProperty).where(CanvassSectionProperty.section_id == section.id))
    for pid in inside:
        db.add(CanvassSectionProperty(section_id=section.id, property_id=pid))
    return len(inside)


async def section_counts(db: AsyncSession, section_id) -> tuple[int, int]:
    total = (await db.execute(
        select(func.count(CanvassSectionProperty.id)).where(CanvassSectionProperty.section_id == section_id)
    )).scalar_one()
    dnk = (await db.execute(
        select(func.count(CanvassSectionProperty.id))
        .join(Property, Property.id == CanvassSectionProperty.property_id)
        .where(CanvassSectionProperty.section_id == section_id, Property.do_not_knock.is_(True))
    )).scalar_one()
    return total, dnk
