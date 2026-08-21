"""Second-phase permanent property locator for stored RentCast properties.

RentCast remains authoritative for property/address attributes. Mapbox Geocoding v6 is used only to
turn the known stored address into a better coordinate. RoofSpan requests permanent geocodes and
stores completed outcomes in the property's local PostgreSQL diagnostics, so normal map use does not
call Mapbox again for that resolver version. MapTiler remains the map/satellite/building provider.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from core import decrypt_secret
from db import SessionLocal
from geo import bbox as territory_bbox, point_in_polygon
from mapbox_geocoding import MAPBOX_BATCH_SIZE, geocode_batch
from models import IntegrationSetting, Property, Territory

logger = logging.getLogger("roofspan.location_upgrade")

RESOLUTION_VERSION = "mapbox_permanent_property_location_v2"
CHUNK_SIZE = MAPBOX_BATCH_SIZE

_running_lock = asyncio.Lock()
_property_locks: dict[str, asyncio.Lock] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _location(prop: Property) -> dict:
    raw = prop.raw if isinstance(prop.raw, dict) else {}
    loc = raw.get("roofspan_location")
    return loc if isinstance(loc, dict) else {}


def _needs_upgrade(prop: Property) -> bool:
    return _location(prop).get("auto_resolution_version") != RESOLUTION_VERSION


def _rentcast_source_coords(prop: Property) -> tuple[float | None, float | None]:
    loc = _location(prop)
    lat = loc.get("rentcast_latitude")
    lng = loc.get("rentcast_longitude")
    if lat is None or lng is None:
        return prop.latitude, prop.longitude
    return lat, lng


def _record(prop: Property) -> dict:
    rentcast_lat, rentcast_lng = _rentcast_source_coords(prop)
    return {
        "id": str(prop.id),
        "address_line1": prop.address_line1 or "",
        "city": prop.city or "",
        "state": prop.state or "",
        "zip_code": prop.zip_code or "",
        "rentcast_latitude": rentcast_lat,
        "rentcast_longitude": rentcast_lng,
    }


def _coordinate_source(result: dict) -> str:
    accuracy = result.get("accuracy")
    if accuracy == "rooftop":
        return "mapbox_rooftop"
    if accuracy == "parcel":
        return "mapbox_parcel"
    if accuracy == "point":
        return "mapbox_point"
    if accuracy == "interpolated":
        return "mapbox_interpolated"
    return "mapbox"


def _store_result(prop: Property, result: dict, territory: Territory) -> None:
    raw = dict(prop.raw or {})
    previous = raw.get("roofspan_location") if isinstance(raw.get("roofspan_location"), dict) else {}
    rentcast_lat, rentcast_lng = _rentcast_source_coords(prop)

    status = result.get("status")
    candidate_lat = result.get("latitude")
    candidate_lng = result.get("longitude")
    resolved = bool(status == "located" and candidate_lat is not None and candidate_lng is not None)
    inside = None
    if candidate_lat is not None and candidate_lng is not None:
        inside = point_in_polygon(candidate_lng, candidate_lat, territory.geometry)

    loc = dict(previous)
    loc.update({
        "query_address": prop.formatted_address,
        "rentcast_latitude": rentcast_lat,
        "rentcast_longitude": rentcast_lng,
        "location_provider": "mapbox",
        "geocoder_status": status,
        "geocoder_reason": result.get("reason"),
        "geocoder_http_status": result.get("http_status"),
        "mapbox_formatted_address": result.get("formatted_address"),
        "mapbox_latitude": candidate_lat if resolved else None,
        "mapbox_longitude": candidate_lng if resolved else None,
        "mapbox_candidate_latitude": candidate_lat if not resolved else None,
        "mapbox_candidate_longitude": candidate_lng if not resolved else None,
        "mapbox_accuracy": result.get("accuracy"),
        "mapbox_confidence": result.get("confidence"),
        "mapbox_id": result.get("mapbox_id"),
        "mapbox_match_code": result.get("match_code"),
        "mapbox_routable_points": result.get("routable_points"),
        "identity_expected": result.get("identity_expected"),
        "identity_returned": result.get("identity_returned"),
        "street_alias_detected": bool(result.get("street_alias_detected")),
        "street_alias_expected": result.get("street_alias_expected"),
        "street_alias_returned": result.get("street_alias_returned"),
        "location_quality": result.get("location_quality"),
        "location_resolved": resolved,
        "location_method": "mapbox_permanent_geocode" if resolved else None,
        "inside_territory": inside,
        "address_verified": False,
        "auto_resolution_checked_at": _now_iso(),
    })

    if resolved:
        prop.latitude = candidate_lat
        prop.longitude = candidate_lng
        loc["coordinate_source"] = _coordinate_source(result)
        loc["resolution_state"] = "resolved"
    else:
        if rentcast_lat is not None and rentcast_lng is not None:
            prop.latitude = rentcast_lat
            prop.longitude = rentcast_lng
        loc["coordinate_source"] = "rentcast"
        loc["resolution_state"] = "retry_pending" if status == "error" else "unresolved"

    if status == "error":
        loc["auto_resolution_version"] = None
        loc["cached_permanently"] = False
    else:
        loc["auto_resolution_version"] = RESOLUTION_VERSION
        loc["cached_permanently"] = True
        loc["cached_at"] = _now_iso()

    raw["roofspan_location"] = loc
    prop.raw = raw


async def _mapbox_token(db) -> str:
    row = (
        await db.execute(
            select(IntegrationSetting).where(IntegrationSetting.provider == "mapbox")
        )
    ).scalar_one_or_none()
    if not (row and row.enabled and row.secret_ciphertext):
        raise RuntimeError("Mapbox Permanent Geocoding is not configured")
    try:
        return decrypt_secret(row.secret_ciphertext)
    except Exception as exc:
        raise RuntimeError("Mapbox access token cannot be decrypted") from exc


async def locate_property_now(property_id: str) -> dict:
    """Force one fresh Mapbox permanent geocode, replacing that property's cached location result."""
    lock = _property_locks.setdefault(str(property_id), asyncio.Lock())
    async with lock:
        async with SessionLocal() as db:
            prop = await db.get(Property, property_id)
            if not prop:
                raise LookupError("Property not found")
            if not prop.territory_id:
                raise ValueError("Property is not assigned to a territory")
            territory = await db.get(Territory, prop.territory_id)
            if not territory:
                raise LookupError("Territory not found")
            if not (prop.address_line1 or "").strip():
                raise ValueError("Property does not have a street address")

            token = await _mapbox_token(db)
            results = await geocode_batch(token, [_record(prop)], bbox=territory_bbox(territory.geometry))
            result = results.get(str(prop.id)) or {
                "status": "error",
                "reason": "single_result_missing",
                "http_status": None,
            }
            _store_result(prop, result, territory)
            await db.commit()
            await db.refresh(prop)
            loc = _location(prop)
            return {
                "property_id": str(prop.id),
                "address": prop.formatted_address,
                "resolved": bool(loc.get("location_resolved")),
                "coordinate_source": loc.get("coordinate_source"),
                "latitude": prop.latitude,
                "longitude": prop.longitude,
                "reason": loc.get("geocoder_reason"),
                "accuracy": loc.get("mapbox_accuracy"),
                "confidence": loc.get("mapbox_confidence"),
                "street_alias_detected": bool(loc.get("street_alias_detected")),
                "street_alias_expected": loc.get("street_alias_expected"),
                "street_alias_returned": loc.get("street_alias_returned"),
                "location_quality": loc.get("location_quality"),
                "cached_permanently": bool(loc.get("cached_permanently")),
                "checked_at": loc.get("auto_resolution_checked_at"),
            }


verify_property_location_now = locate_property_now


async def refresh_existing_property_locations(territory_id: str | None = None) -> None:
    """Locate only uncached RentCast properties in a separate, resumable Mapbox permanent phase."""
    if _running_lock.locked():
        logger.info("Property location resolver already running; duplicate request skipped")
        return

    async with _running_lock:
        async with SessionLocal() as db:
            try:
                token = await _mapbox_token(db)
            except RuntimeError as exc:
                logger.info("Property location resolution skipped: %s", exc)
                return

            territory_stmt = select(Territory)
            if territory_id:
                territory_stmt = territory_stmt.where(Territory.id == territory_id)
            territory_rows = (await db.execute(territory_stmt)).scalars().all()
            territories = {str(t.id): t for t in territory_rows}
            if not territories:
                return

            prop_stmt = select(Property).where(
                Property.source == "rentcast",
                Property.territory_id.isnot(None),
            ).order_by(Property.created_at.asc())
            if territory_id:
                prop_stmt = prop_stmt.where(Property.territory_id == territory_id)
            props = (await db.execute(prop_stmt)).scalars().all()
            pending = [p for p in props if _needs_upgrade(p) and str(p.territory_id) in territories]
            if not pending:
                logger.info("Property location cache already current (%s)", RESOLUTION_VERSION)
                return

            logger.info("Starting Mapbox permanent location pass for %d properties", len(pending))
            processed = 0
            resolved_count = 0
            retry_pending = 0

            for tid in {str(p.territory_id) for p in pending}:
                territory = territories[tid]
                group = [p for p in pending if str(p.territory_id) == tid]
                for start in range(0, len(group), CHUNK_SIZE):
                    chunk = group[start:start + CHUNK_SIZE]
                    results = await geocode_batch(
                        token,
                        [_record(p) for p in chunk],
                        bbox=territory_bbox(territory.geometry),
                    )
                    for prop in chunk:
                        result = results.get(str(prop.id)) or {
                            "status": "error",
                            "reason": "batch_result_missing",
                            "http_status": None,
                        }
                        _store_result(prop, result, territory)
                        processed += 1
                        if result.get("status") == "located":
                            resolved_count += 1
                        if result.get("status") == "error":
                            retry_pending += 1
                    await db.commit()
                    await asyncio.sleep(0)

            logger.info(
                "Mapbox permanent location pass finished: processed=%d resolved=%d retry_pending=%d version=%s",
                processed,
                resolved_count,
                retry_pending,
                RESOLUTION_VERSION,
            )
