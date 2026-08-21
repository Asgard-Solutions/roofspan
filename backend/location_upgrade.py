"""Second-phase permanent property locator for stored RentCast properties.

RentCast remains authoritative for property/address attributes. Geocodio is the address-to-coordinate
provider because its forward-geocoding results may be stored for reuse. RoofSpan caches each completed
lookup in the property's local PostgreSQL raw diagnostics and will not call the provider again for that
resolver version unless the user explicitly forces a fresh lookup or the address is re-imported/changed.
MapTiler remains only a map/satellite/building visualization provider.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from core import decrypt_secret
from db import SessionLocal
from geo import point_in_polygon
from geocodio import GEOCODIO_BATCH_SIZE, geocode_batch
from models import IntegrationSetting, Property, Territory

logger = logging.getLogger("roofspan.location_upgrade")

RESOLUTION_VERSION = "geocodio_property_location_v1"
CHUNK_SIZE = GEOCODIO_BATCH_SIZE

_running_lock = asyncio.Lock()
_property_locks: dict[str, asyncio.Lock] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _location(prop: Property) -> dict:
    raw = prop.raw if isinstance(prop.raw, dict) else {}
    loc = raw.get("roofspan_location")
    return loc if isinstance(loc, dict) else {}


def _needs_upgrade(prop: Property) -> bool:
    """Only unresolved resolver versions are sent to the provider automatically."""
    return _location(prop).get("auto_resolution_version") != RESOLUTION_VERSION


def _rentcast_source_coords(prop: Property) -> tuple[float | None, float | None]:
    loc = _location(prop)
    lat = loc.get("rentcast_latitude")
    lng = loc.get("rentcast_longitude")
    if lat is None or lng is None:
        return prop.latitude, prop.longitude
    return lat, lng


def _record(prop: Property) -> dict:
    return {
        "id": str(prop.id),
        "address_line1": prop.address_line1 or "",
        "city": prop.city or "",
        "state": prop.state or "",
        "zip_code": prop.zip_code or "",
    }


def _coordinate_source(result: dict) -> str:
    accuracy_type = result.get("accuracy_type")
    if accuracy_type == "rooftop":
        return "geocodio_rooftop"
    if accuracy_type == "point":
        return "geocodio_point"
    if accuracy_type == "range_interpolation":
        return "geocodio_interpolated"
    return "geocodio"


def _store_result(prop: Property, result: dict, territory: Territory) -> None:
    raw = dict(prop.raw or {})
    previous = raw.get("roofspan_location") if isinstance(raw.get("roofspan_location"), dict) else {}
    rentcast_lat, rentcast_lng = _rentcast_source_coords(prop)

    status = result.get("status")
    candidate_lat = result.get("latitude")
    candidate_lng = result.get("longitude")
    resolved = bool(status == "located" and candidate_lat is not None and candidate_lng is not None)
    inside_territory = None
    if candidate_lat is not None and candidate_lng is not None:
        inside_territory = point_in_polygon(candidate_lng, candidate_lat, territory.geometry)

    loc = dict(previous)
    loc.update({
        "query_address": prop.formatted_address,
        "rentcast_latitude": rentcast_lat,
        "rentcast_longitude": rentcast_lng,
        "location_provider": "geocodio",
        "geocoder_status": status,
        "geocoder_reason": result.get("reason"),
        "geocoder_http_status": result.get("http_status"),
        "geocodio_formatted_address": result.get("formatted_address"),
        "geocodio_latitude": candidate_lat if resolved else None,
        "geocodio_longitude": candidate_lng if resolved else None,
        "geocodio_candidate_latitude": candidate_lat if not resolved else None,
        "geocodio_candidate_longitude": candidate_lng if not resolved else None,
        "geocodio_accuracy": result.get("accuracy"),
        "geocodio_accuracy_type": result.get("accuracy_type"),
        "geocodio_match_type": result.get("match_type"),
        "geocodio_source": result.get("source"),
        "geocodio_stable_address_key": result.get("stable_address_key"),
        "geocodio_address_components": result.get("address_components"),
        "identity_checks": result.get("identity_checks"),
        "location_quality": result.get("location_quality"),
        "location_resolved": resolved,
        "location_method": "geocodio_forward_geocode" if resolved else None,
        "inside_territory": inside_territory,
        "address_verified": False,
        "auto_resolution_checked_at": _now_iso(),
    })

    if resolved:
        # The RentCast address is authoritative. A precise Geocodio result that matches all stored
        # address components remains valid even if the corrected coordinate falls just outside the
        # acquisition polygon that was originally populated using RentCast coordinates.
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

    # Successful and rejected responses are permanent cached outcomes for this resolver version.
    # Transport/provider errors are not cached as complete, so a future startup may retry them.
    if status == "error":
        loc["auto_resolution_version"] = None
    else:
        loc["auto_resolution_version"] = RESOLUTION_VERSION
        loc["cached_permanently"] = True
        loc["cached_at"] = _now_iso()

    raw["roofspan_location"] = loc
    prop.raw = raw


async def _geocodio_key(db) -> str:
    row = (
        await db.execute(
            select(IntegrationSetting).where(IntegrationSetting.provider == "geocodio")
        )
    ).scalar_one_or_none()
    if not (row and row.enabled and row.secret_ciphertext):
        raise RuntimeError("Geocodio is not configured")
    try:
        return decrypt_secret(row.secret_ciphertext)
    except Exception as exc:
        raise RuntimeError("Geocodio API key cannot be decrypted") from exc


async def locate_property_now(property_id: str) -> dict:
    """Force one fresh Geocodio lookup, replacing that property's cached location result."""
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

            key = await _geocodio_key(db)
            results = await geocode_batch(key, [_record(prop)])
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
                "accuracy": loc.get("geocodio_accuracy"),
                "accuracy_type": loc.get("geocodio_accuracy_type"),
                "location_quality": loc.get("location_quality"),
                "cached_permanently": bool(loc.get("cached_permanently")),
                "checked_at": loc.get("auto_resolution_checked_at"),
            }


# Backward-compatible function name used by older routes/tests/builds.
verify_property_location_now = locate_property_now


async def refresh_existing_property_locations(territory_id: str | None = None) -> None:
    """Locate only uncached RentCast properties in a separate, resumable Geocodio phase."""
    if _running_lock.locked():
        logger.info("Property location resolver already running; duplicate request skipped")
        return

    async with _running_lock:
        async with SessionLocal() as db:
            try:
                key = await _geocodio_key(db)
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

            logger.info("Starting Geocodio permanent location pass for %d properties", len(pending))
            processed = 0
            resolved_count = 0
            retry_pending = 0

            for tid in {str(p.territory_id) for p in pending}:
                territory = territories[tid]
                group = [p for p in pending if str(p.territory_id) == tid]
                for start in range(0, len(group), CHUNK_SIZE):
                    chunk = group[start:start + CHUNK_SIZE]
                    results = await geocode_batch(key, [_record(p) for p in chunk])
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
                    # Commit every provider batch. If RoofSpan closes, completed batches stay cached
                    # and the next startup resumes only the rows that do not carry this version.
                    await db.commit()
                    await asyncio.sleep(0)

            logger.info(
                "Geocodio permanent location pass finished: processed=%d resolved=%d retry_pending=%d version=%s",
                processed,
                resolved_count,
                retry_pending,
                RESOLUTION_VERSION,
            )
