"""RentCast client + normalization + sample-data generator (used when no key configured)."""
import random

import httpx

from geo import bbox, point_in_polygon, centroid

RENTCAST_BASE = "https://api.rentcast.io/v1"


def normalize_rentcast(raw: dict) -> dict:
    owner = raw.get("owner") or {}
    names = owner.get("names") or []
    mailing = (owner.get("mailingAddress") or {}).get("formattedAddress")
    return {
        "external_id": raw.get("id"),
        "source": "rentcast",
        "formatted_address": raw.get("formattedAddress") or "",
        "address_line1": raw.get("addressLine1") or "",
        "address_line2": raw.get("addressLine2"),
        "city": raw.get("city") or "",
        "state": raw.get("state") or "",
        "zip_code": raw.get("zipCode") or "",
        "latitude": raw.get("latitude"),
        "longitude": raw.get("longitude"),
        "property_type": raw.get("propertyType"),
        "bedrooms": raw.get("bedrooms"),
        "bathrooms": raw.get("bathrooms"),
        "square_footage": raw.get("squareFootage"),
        "year_built": raw.get("yearBuilt"),
        "owner_occupied": raw.get("ownerOccupied"),
        "owner": {
            "name": ", ".join(names) if names else "",
            "type": owner.get("type"),
            "mailing_address": mailing,
        },
        "raw": raw,
    }


async def fetch_rentcast_properties(key: str, lat: float, lng: float, radius: float, max_records: int, page_size: int = 500):
    results = []
    offset = 0
    async with httpx.AsyncClient(base_url=RENTCAST_BASE, timeout=30) as client:
        while len(results) < max_records:
            limit = min(page_size, max_records - len(results))
            r = await client.get(
                "/properties",
                params={"latitude": lat, "longitude": lng, "radius": radius, "limit": limit, "offset": offset},
                headers={"Accept": "application/json", "X-Api-Key": key},
            )
            r.raise_for_status()
            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break
            results.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
    return results


async def fetch_rentcast_by_zip(key: str, zip_code: str, max_records: int, page_size: int = 500):
    """Pull properties for an exact ZIP code (RentCast's native zipCode filter; cheaper + exact vs radius)."""
    results = []
    offset = 0
    async with httpx.AsyncClient(base_url=RENTCAST_BASE, timeout=30) as client:
        while len(results) < max_records:
            limit = min(page_size, max_records - len(results))
            r = await client.get(
                "/properties",
                params={"zipCode": zip_code, "limit": limit, "offset": offset},
                headers={"Accept": "application/json", "X-Api-Key": key},
            )
            r.raise_for_status()
            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break
            results.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
    return results


_STREETS = ["Oak", "Maple", "Cedar", "Pine", "Elm", "Birch", "Willow", "Aspen", "Juniper", "Magnolia"]
_TYPES = ["Single Family", "Single Family", "Single Family", "Townhouse", "Duplex"]
_FIRST = ["James", "Maria", "Robert", "Linda", "David", "Susan", "Carlos", "Angela", "Michael", "Patricia"]
_LAST = ["Smith", "Johnson", "Garcia", "Miller", "Davis", "Rodriguez", "Wilson", "Martinez", "Anderson", "Lee"]


def generate_sample_properties(territory_id: str, geometry: dict, count: int):
    """Deterministic synthetic properties inside the polygon (idempotent external ids)."""
    minlng, minlat, maxlng, maxlat = bbox(geometry)
    rnd = random.Random(f"roofspan-sample-{territory_id}")
    clng, clat = centroid(geometry)
    _, base_state = ("", "TX")
    out = []
    idx = 0
    attempts = 0
    while len(out) < count and attempts < count * 80:
        attempts += 1
        lng = rnd.uniform(minlng, maxlng)
        lat = rnd.uniform(minlat, maxlat)
        if not point_in_polygon(lng, lat, geometry):
            continue
        idx += 1
        num = 100 + idx * 2
        street = _STREETS[idx % len(_STREETS)]
        addr1 = f"{num} {street} St"
        city = "Field City"
        zipc = f"{78700 + (idx % 40):05d}"
        owner_name = f"{_FIRST[idx % len(_FIRST)]} {_LAST[(idx * 3) % len(_LAST)]}"
        occupied = rnd.random() > 0.35
        out.append({
            "external_id": f"sample-{territory_id}-{idx}",
            "source": "sample",
            "formatted_address": f"{addr1}, {city}, {base_state} {zipc}",
            "address_line1": addr1,
            "address_line2": None,
            "city": city,
            "state": base_state,
            "zip_code": zipc,
            "latitude": round(lat, 6),
            "longitude": round(lng, 6),
            "property_type": _TYPES[idx % len(_TYPES)],
            "bedrooms": 2 + (idx % 4),
            "bathrooms": 1 + (idx % 3),
            "square_footage": 1200 + (idx % 20) * 120,
            "year_built": 1960 + (idx % 60),
            "owner_occupied": occupied,
            "owner": {
                "name": owner_name,
                "type": "Individual",
                "mailing_address": f"{addr1}, {city}, {base_state} {zipc}" if occupied else f"PO Box {200 + idx}, {city}, {base_state} {zipc}",
            },
            "raw": {"sample": True},
        })
    return out
