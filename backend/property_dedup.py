"""Conservative duplicate-property cleanup for RentCast acquisition records.

RentCast can occasionally return more than one record for the same physical property (for example
"1778 S Ruby Dr" and "1778 Ruby Dr") under different external IDs. RoofSpan keeps one canonical
Property row, moves dependent records to it, and deletes only duplicates that pass conservative
address + proximity checks.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Iterable

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db import SessionLocal
from models import (
    CustomerProperty,
    Estimate,
    Inspection,
    Invoice,
    Job,
    Lead,
    Photo,
    Property,
    PropertyContact,
    Quote,
    Visit,
)

# Tight enough to avoid merging ordinary neighboring properties while allowing provider pin drift.
EXACT_STREET_MAX_FEET = 500.0
MISSING_DIRECTIONAL_MAX_FEET = 250.0

_DIRECTIONALS = {
    "north": "n", "n": "n", "south": "s", "s": "s", "east": "e", "e": "e", "west": "w", "w": "w",
    "northeast": "ne", "ne": "ne", "northwest": "nw", "nw": "nw",
    "southeast": "se", "se": "se", "southwest": "sw", "sw": "sw",
}
_SUFFIXES = {
    "avenue": "ave", "ave": "ave", "av": "ave", "street": "st", "st": "st",
    "road": "rd", "rd": "rd", "drive": "dr", "dr": "dr", "lane": "ln", "ln": "ln",
    "court": "ct", "ct": "ct", "circle": "cir", "cir": "cir", "boulevard": "blvd", "blvd": "blvd",
    "highway": "hwy", "hwy": "hwy", "parkway": "pkwy", "pkwy": "pkwy", "place": "pl", "pl": "pl",
    "terrace": "ter", "ter": "ter", "trail": "trl", "trl": "trl", "way": "way",
}


def _clean(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _zip5(value) -> str:
    match = re.search(r"\b(\d{5})(?:-\d{4})?\b", str(value or ""))
    return match.group(1) if match else ""


def address_fingerprint(address_line1: str, city: str, state: str, zip_code: str) -> dict:
    """Return a normalized physical-address fingerprint without blindly discarding directionals."""
    match = re.match(r"^\s*([0-9]+[A-Za-z]?(?:-[0-9A-Za-z]+)?)\s+(.+?)\s*$", str(address_line1 or ""))
    if not match:
        return {"house": "", "street_core": "", "directionals": frozenset(), "city": _clean(city), "state": _clean(state), "zip": _zip5(zip_code)}

    house = _clean(match.group(1))
    directionals: set[str] = set()
    street_tokens: list[str] = []
    for token in _clean(match.group(2)).split():
        directional = _DIRECTIONALS.get(token)
        if directional:
            directionals.add(directional)
            continue
        street_tokens.append(_SUFFIXES.get(token, token))

    return {
        "house": house,
        "street_core": " ".join(street_tokens),
        "directionals": frozenset(directionals),
        "city": _clean(city),
        "state": _clean(state),
        "zip": _zip5(zip_code),
    }


def _distance_feet(a: Property, b: Property) -> float | None:
    if a.latitude is None or a.longitude is None or b.latitude is None or b.longitude is None:
        return None
    r_ft = 20_902_231.0
    lat1 = math.radians(float(a.latitude))
    lat2 = math.radians(float(b.latitude))
    dlat = lat2 - lat1
    dlng = math.radians(float(b.longitude) - float(a.longitude))
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * r_ft * math.asin(min(1.0, math.sqrt(h)))


def _same_unit(a: Property, b: Property) -> bool:
    # Do not automatically collapse two explicitly different apartment/unit designators.
    unit_a = _clean(a.address_line2)
    unit_b = _clean(b.address_line2)
    return not (unit_a and unit_b and unit_a != unit_b)


def likely_duplicate(a: Property, b: Property) -> bool:
    """Conservative duplicate decision used by the one-time/backfill cleanup."""
    if a.id == b.id or a.territory_id != b.territory_id or not _same_unit(a, b):
        return False
    fa = address_fingerprint(a.address_line1, a.city, a.state, a.zip_code)
    fb = address_fingerprint(b.address_line1, b.city, b.state, b.zip_code)
    if not fa["house"] or not fa["street_core"]:
        return False
    for key in ("house", "street_core", "city", "state", "zip"):
        if fa[key] != fb[key]:
            return False

    da, db = fa["directionals"], fb["directionals"]
    # Missing-vs-present directional is allowed; contradictory directionals are not.
    if da and db and da != db:
        return False
    distance = _distance_feet(a, b)
    if distance is None:
        return False
    limit = EXACT_STREET_MAX_FEET if da == db else MISSING_DIRECTIONAL_MAX_FEET
    return distance <= limit


def _loc(prop: Property) -> dict:
    raw = prop.raw if isinstance(prop.raw, dict) else {}
    value = raw.get("roofspan_location")
    return value if isinstance(value, dict) else {}


def _canonical_score(prop: Property, contact_count: int, related_count: int) -> tuple:
    loc = _loc(prop)
    mapbox_resolved = bool(loc.get("location_resolved") and str(loc.get("coordinate_source") or "").startswith("mapbox"))
    richness = sum(
        value not in (None, "")
        for value in (
            prop.property_type, prop.bedrooms, prop.bathrooms, prop.square_footage,
            prop.year_built, prop.owner_occupied, prop.notes,
        )
    )
    # Deterministic final tie-break: older row wins.
    created = prop.created_at.timestamp() if prop.created_at else 0.0
    return (1 if mapbox_resolved else 0, contact_count, related_count, richness, -created)


async def _counts(db: AsyncSession, prop: Property) -> tuple[int, int]:
    contacts = len((await db.execute(select(PropertyContact.id).where(PropertyContact.property_id == prop.id))).all())
    related = 0
    for model in (Visit, Lead, CustomerProperty, Inspection, Estimate, Quote, Job, Invoice):
        related += len((await db.execute(select(model.id).where(model.property_id == prop.id))).all())
    related += len((await db.execute(select(Photo.id).where(Photo.record_type == "property", Photo.record_id == str(prop.id)))).all())
    return contacts, related


async def _merge_contacts(db: AsyncSession, canonical: Property, duplicate: Property) -> None:
    canonical_contacts = (await db.execute(select(PropertyContact).where(PropertyContact.property_id == canonical.id))).scalars().all()
    duplicate_contacts = (await db.execute(select(PropertyContact).where(PropertyContact.property_id == duplicate.id))).scalars().all()
    keys = {(_clean(c.kind), _clean(c.name), _clean(c.mailing_address), _clean(c.phone), _clean(c.email)) for c in canonical_contacts}
    for contact in duplicate_contacts:
        key = (_clean(contact.kind), _clean(contact.name), _clean(contact.mailing_address), _clean(contact.phone), _clean(contact.email))
        if key in keys:
            await db.delete(contact)
        else:
            contact.property_id = canonical.id
            keys.add(key)


async def _merge_customer_properties(db: AsyncSession, canonical: Property, duplicate: Property) -> None:
    canonical_customer_ids = {
        row[0]
        for row in (await db.execute(select(CustomerProperty.customer_id).where(CustomerProperty.property_id == canonical.id))).all()
    }
    rows = (await db.execute(select(CustomerProperty).where(CustomerProperty.property_id == duplicate.id))).scalars().all()
    for row in rows:
        if row.customer_id in canonical_customer_ids:
            await db.delete(row)
        else:
            row.property_id = canonical.id
            canonical_customer_ids.add(row.customer_id)


async def merge_property(db: AsyncSession, canonical: Property, duplicate: Property) -> None:
    """Move known property-dependent records, preserve useful data, then remove the duplicate row."""
    await _merge_contacts(db, canonical, duplicate)
    await _merge_customer_properties(db, canonical, duplicate)

    for model in (Visit, Lead, Inspection, Estimate, Quote, Job, Invoice):
        await db.execute(update(model).where(model.property_id == duplicate.id).values(property_id=canonical.id))
    await db.execute(
        update(Photo)
        .where(Photo.record_type == "property", Photo.record_id == str(duplicate.id))
        .values(record_id=str(canonical.id))
    )

    # Preserve business flags and fill gaps without replacing richer canonical values.
    canonical.do_not_knock = bool(canonical.do_not_knock or duplicate.do_not_knock)
    if not canonical.do_not_knock_reason and duplicate.do_not_knock_reason:
        canonical.do_not_knock_reason = duplicate.do_not_knock_reason
    for field in ("property_type", "bedrooms", "bathrooms", "square_footage", "year_built", "owner_occupied"):
        if getattr(canonical, field) is None and getattr(duplicate, field) is not None:
            setattr(canonical, field, getattr(duplicate, field))
    if not canonical.notes and duplicate.notes:
        canonical.notes = duplicate.notes
    elif canonical.notes and duplicate.notes and duplicate.notes.strip() not in canonical.notes:
        canonical.notes = f"{canonical.notes.rstrip()}\n\nMerged duplicate note:\n{duplicate.notes.strip()}"

    raw = dict(canonical.raw or {})
    merged_ids = list(raw.get("roofspan_merged_external_ids") or [])
    for external_id in (canonical.external_id, duplicate.external_id):
        if external_id and external_id not in merged_ids:
            merged_ids.append(external_id)
    if merged_ids:
        raw["roofspan_merged_external_ids"] = merged_ids
    raw["roofspan_duplicate_cleanup"] = {
        "merged_duplicate_property_id": str(duplicate.id),
        "reason": "normalized_address_and_proximity",
    }
    canonical.raw = raw

    await db.delete(duplicate)


async def cleanup_duplicate_properties(territory_id: str | None = None) -> dict:
    """Merge conservative duplicate clusters. Safe to run repeatedly; returns cleanup statistics."""
    async with SessionLocal() as db:
        stmt = select(Property).where(Property.source == "rentcast").order_by(Property.created_at.asc())
        if territory_id:
            stmt = stmt.where(Property.territory_id == territory_id)
        props = (await db.execute(stmt)).scalars().all()
        if len(props) < 2:
            return {"scanned": len(props), "merged": 0}

        groups: dict[tuple, list[Property]] = defaultdict(list)
        for prop in props:
            fp = address_fingerprint(prop.address_line1, prop.city, prop.state, prop.zip_code)
            if not fp["house"] or not fp["street_core"]:
                continue
            groups[(str(prop.territory_id), fp["house"], fp["street_core"], fp["city"], fp["state"], fp["zip"])].append(prop)

        merged = 0
        for candidates in groups.values():
            if len(candidates) < 2:
                continue

            # Build connected components because three provider variants can describe one property.
            remaining = list(candidates)
            while remaining:
                seed = remaining.pop(0)
                component = [seed]
                changed = True
                while changed:
                    changed = False
                    for candidate in list(remaining):
                        if any(likely_duplicate(candidate, member) for member in component):
                            component.append(candidate)
                            remaining.remove(candidate)
                            changed = True
                if len(component) < 2:
                    continue

                scored = []
                for prop in component:
                    contacts, related = await _counts(db, prop)
                    scored.append((_canonical_score(prop, contacts, related), prop))
                scored.sort(key=lambda item: item[0], reverse=True)
                canonical = scored[0][1]
                for _, duplicate in scored[1:]:
                    await merge_property(db, canonical, duplicate)
                    merged += 1

        if merged:
            await db.commit()
        return {"scanned": len(props), "merged": merged}
