"""Second-phase MapTiler locator for stored RentCast properties.

RentCast remains authoritative for the property address and ownership data. MapTiler's job here is
location only: first try a direct address point, then (when MapTiler only knows the road) use that road
result as a search anchor for the requested house number in MapTiler's building-number layer. A road
point by itself is never used as the property pin.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from core import decrypt_secret
from db import SessionLocal
from geo import bbox, point_in_polygon
from maptiler import (
    MAPTILER_BUILDING_ZOOM,
    _choose_building_polygon,
    _choose_number_feature,
    _number_point,
    _parse_query_address,
    _tile_layer_features,
    _tile_neighborhood,
    geocode_addresses_batch,
)
from models import IntegrationSetting, Property, Territory

logger = logging.getLogger("roofspan.location_upgrade")

RESOLUTION_VERSION = "maptiler_property_location_v4"
CHUNK_SIZE = 25
CONCURRENCY = 8

_running_lock = asyncio.Lock()
_property_locks: dict[str, asyncio.Lock] = {}

_STREET_NOISE = {
    "n", "s", "e", "w", "ne", "nw", "se", "sw",
    "ave", "st", "rd", "dr", "ln", "ct", "cir", "blvd", "hwy", "pkwy", "pl", "ter", "trl", "way",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _needs_upgrade(prop: Property) -> bool:
    raw = prop.raw if isinstance(prop.raw, dict) else {}
    loc = raw.get("roofspan_location") if isinstance(raw.get("roofspan_location"), dict) else {}
    return loc.get("auto_resolution_version") != RESOLUTION_VERSION


def _rentcast_source_coords(prop: Property) -> tuple[float | None, float | None]:
    raw = prop.raw if isinstance(prop.raw, dict) else {}
    loc = raw.get("roofspan_location") if isinstance(raw.get("roofspan_location"), dict) else {}
    lat = loc.get("rentcast_latitude")
    lng = loc.get("rentcast_longitude")
    if lat is None or lng is None:
        return prop.latitude, prop.longitude
    return lat, lng


def _street_core(value: str | None) -> str:
    tokens = [token for token in str(value or "").split() if token not in _STREET_NOISE]
    return " ".join(tokens)


def _road_anchor_matches_known_property(result: dict) -> bool:
    """Allow a road/street geocode only as an anchor for finding the known RentCast house number."""
    expected = result.get("identity_expected") or {}
    actual = result.get("identity_returned") or {}
    if not expected.get("house_number"):
        return False
    if result.get("latitude") is None or result.get("longitude") is None:
        return False

    try:
        relevance = float(result.get("relevance") or 0)
    except (TypeError, ValueError):
        return False
    if relevance < 0.65:
        return False

    # Reject anchors that explicitly disagree on locality. Missing context is acceptable because the
    # final pin still requires an unambiguous matching building number near the road anchor.
    for key in ("state", "zip_code", "city"):
        if expected.get(key) and actual.get(key) and expected.get(key) != actual.get(key):
            return False

    expected_street = _street_core(expected.get("street"))
    actual_street = _street_core(actual.get("street"))
    return bool(expected_street and actual_street and expected_street == actual_street)


async def _locate_numbered_building_from_anchor(key: str, address: str, result: dict) -> dict:
    """Use a MapTiler road result only to search for the known RentCast house number nearby."""
    if result.get("status") == "error" or not _road_anchor_matches_known_property(result):
        return result

    expected = result.get("identity_expected") or _parse_query_address(address)
    house_number = expected.get("house_number")
    anchor_lng = result.get("longitude")
    anchor_lat = result.get("latitude")
    if not house_number or anchor_lng is None or anchor_lat is None:
        return result

    original_reason = result.get("reason")
    tile_cache: dict = {}
    async with httpx.AsyncClient(timeout=30) as client:
        tiles = _tile_neighborhood(anchor_lng, anchor_lat, MAPTILER_BUILDING_ZOOM)
        number_features = await _tile_layer_features(
            client, key, "v4", "building_number", MAPTILER_BUILDING_ZOOM, tiles, tile_cache
        )
        number_feature, number_distance, number_reason = _choose_number_feature(
            number_features, house_number, anchor_lng, anchor_lat
        )
        result["building_reason"] = number_reason
        result["building_distance_feet"] = round(number_distance, 1) if number_distance is not None else None
        result["anchor_reason"] = original_reason
        result["location_method"] = "road_anchor_building_number"
        if not number_feature:
            result["building_status"] = "unresolved"
            result["location_resolved"] = False
            return result

        number_point = _number_point(number_feature)
        if not number_point:
            result["building_status"] = "unresolved"
            result["building_reason"] = "building_number_point_invalid"
            result["location_resolved"] = False
            return result

        number_lng, number_lat = number_point
        result.update({
            "building_status": "matched_number",
            "building_number": (number_feature.get("properties") or {}).get("number"),
            "building_number_latitude": number_lat,
            "building_number_longitude": number_lng,
        })

        building_tiles = _tile_neighborhood(number_lng, number_lat, MAPTILER_BUILDING_ZOOM)
        building_features = await _tile_layer_features(
            client, key, "buildings", "building", MAPTILER_BUILDING_ZOOM, building_tiles, tile_cache
        )
        building_feature, polygon = _choose_building_polygon(building_features, number_lng, number_lat)
        if not building_feature:
            v4_buildings = await _tile_layer_features(
                client, key, "v4", "building", MAPTILER_BUILDING_ZOOM, building_tiles, tile_cache
            )
            building_feature, polygon = _choose_building_polygon(v4_buildings, number_lng, number_lat)

        if building_feature and polygon is not None:
            pin = polygon.representative_point()
            props = building_feature.get("properties") or {}
            result.update({
                "latitude": float(pin.y),
                "longitude": float(pin.x),
                "building_status": "resolved",
                "building_reason": "numbered_building_from_road_anchor",
                "building_class": props.get("class"),
                "building_subclass": props.get("subclass"),
                "building_feature_id": building_feature.get("id"),
                "building_latitude": float(pin.y),
                "building_longitude": float(pin.x),
            })
        else:
            result.update({
                "latitude": number_lat,
                "longitude": number_lng,
                "building_status": "resolved",
                "building_reason": "building_number_point_from_road_anchor",
                "building_latitude": number_lat,
                "building_longitude": number_lng,
            })

    result["status"] = "located"
    result["reason"] = "known_address_located_by_building_number"
    result["location_resolved"] = True
    return result


def _store_result(prop: Property, result: dict, territory: Territory) -> None:
    raw = dict(prop.raw or {})
    previous = raw.get("roofspan_location") if isinstance(raw.get("roofspan_location"), dict) else {}
    rentcast_lat, rentcast_lng = _rentcast_source_coords(prop)

    result_status = result.get("status")
    candidate_lat = result.get("latitude")
    candidate_lng = result.get("longitude")
    usable_location = result_status in ("accepted", "located")
    inside = (
        usable_location
        and candidate_lat is not None
        and candidate_lng is not None
        and point_in_polygon(candidate_lng, candidate_lat, territory.geometry)
    )
    location_resolved = bool(inside)
    address_verified = bool(result_status == "accepted" and inside)

    loc = dict(previous)
    loc.update({
        "query_address": prop.formatted_address,
        "rentcast_latitude": rentcast_lat,
        "rentcast_longitude": rentcast_lng,
        "maptiler_status": result_status,
        "maptiler_reason": result.get("reason"),
        "maptiler_http_status": result.get("http_status"),
        "maptiler_returned_address": result.get("returned_address"),
        "maptiler_returned_label": result.get("returned_label"),
        "maptiler_latitude": candidate_lat if location_resolved else None,
        "maptiler_longitude": candidate_lng if location_resolved else None,
        "maptiler_candidate_latitude": candidate_lat if not location_resolved else None,
        "maptiler_candidate_longitude": candidate_lng if not location_resolved else None,
        "maptiler_relevance": result.get("relevance"),
        "maptiler_place_type": result.get("place_type"),
        "maptiler_feature_id": result.get("feature_id"),
        "identity_expected": result.get("identity_expected"),
        "identity_returned": result.get("identity_returned"),
        "identity_checks": result.get("identity_checks"),
        "address_verified": address_verified,
        "location_resolved": location_resolved,
        "location_method": result.get("location_method") or ("direct_address" if address_verified else None),
        "anchor_reason": result.get("anchor_reason"),
        "building_status": result.get("building_status"),
        "building_reason": result.get("building_reason"),
        "building_number": result.get("building_number"),
        "building_number_latitude": result.get("building_number_latitude"),
        "building_number_longitude": result.get("building_number_longitude"),
        "building_distance_feet": result.get("building_distance_feet"),
        "building_class": result.get("building_class"),
        "building_subclass": result.get("building_subclass"),
        "building_feature_id": result.get("building_feature_id"),
        "building_latitude": result.get("building_latitude"),
        "building_longitude": result.get("building_longitude"),
        "auto_resolution_checked_at": _now_iso(),
    })

    if location_resolved:
        prop.latitude = candidate_lat
        prop.longitude = candidate_lng
        if result.get("building_status") == "resolved":
            loc["coordinate_source"] = "maptiler_numbered_building"
        elif address_verified:
            loc["coordinate_source"] = "maptiler_address"
        else:
            loc["coordinate_source"] = "maptiler_location"
        loc["resolution_state"] = "resolved"
    else:
        if rentcast_lat is not None and rentcast_lng is not None:
            prop.latitude = rentcast_lat
            prop.longitude = rentcast_lng
        loc["coordinate_source"] = "rentcast"
        if result_status == "error":
            loc["resolution_state"] = "retry_pending"
        else:
            loc["resolution_state"] = "unresolved"

    if result_status == "error":
        loc["auto_resolution_version"] = None
    else:
        loc["auto_resolution_version"] = RESOLUTION_VERSION

    raw["roofspan_location"] = loc
    prop.raw = raw


async def _resolve_one(key: str, address: str, territory: Territory, semaphore: asyncio.Semaphore) -> dict:
    """Locate one known RentCast address with MapTiler without asking MapTiler to validate the address."""
    async with semaphore:
        try:
            results = await geocode_addresses_batch(
                key,
                [address],
                bbox=bbox(territory.geometry),
                country="us",
                min_relevance=0.80,
            )
            if len(results) != 1:
                return {
                    "status": "error", "reason": "single_result_count_mismatch", "http_status": None,
                    "feature": None, "returned_address": None, "returned_label": None,
                    "relevance": None, "place_type": None, "latitude": None, "longitude": None,
                    "feature_id": None, "building_status": "not_attempted", "building_reason": "not_attempted",
                }
            result = results[0]
            if result.get("status") == "accepted":
                result["location_resolved"] = True
                result["location_method"] = (
                    "direct_address_building" if result.get("building_status") == "resolved" else "direct_address"
                )
                return result
            return await _locate_numbered_building_from_anchor(key, address, result)
        except Exception as exc:
            logger.warning("Single-address MapTiler location lookup failed for %s: %s", address, exc.__class__.__name__)
            return {
                "status": "error", "reason": "single_request_exception", "http_status": None,
                "feature": None, "returned_address": None, "returned_label": None,
                "relevance": None, "place_type": None, "latitude": None, "longitude": None,
                "feature_id": None, "building_status": "not_attempted", "building_reason": "not_attempted",
            }


async def _maptiler_key(db) -> str:
    row = (
        await db.execute(
            select(IntegrationSetting).where(IntegrationSetting.provider == "maptiler")
        )
    ).scalar_one_or_none()
    if not (row and row.enabled and row.secret_ciphertext):
        raise RuntimeError("MapTiler is not configured")
    try:
        return decrypt_secret(row.secret_ciphertext)
    except Exception as exc:
        raise RuntimeError("MapTiler key cannot be decrypted") from exc


async def verify_property_location_now(property_id: str) -> dict:
    """Force a fresh MapTiler location lookup for one stored RentCast property."""
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
            if not (prop.formatted_address or "").strip():
                raise ValueError("Property does not have a formatted address")

            key = await _maptiler_key(db)
            result = await _resolve_one(
                key,
                prop.formatted_address,
                territory,
                asyncio.Semaphore(1),
            )
            _store_result(prop, result, territory)
            await db.commit()
            await db.refresh(prop)
            raw = prop.raw if isinstance(prop.raw, dict) else {}
            loc = raw.get("roofspan_location") if isinstance(raw.get("roofspan_location"), dict) else {}
            return {
                "property_id": str(prop.id),
                "address": prop.formatted_address,
                "resolved": bool(loc.get("location_resolved")),
                "verified": bool(loc.get("location_resolved")),
                "address_verified": bool(loc.get("address_verified")),
                "coordinate_source": loc.get("coordinate_source"),
                "latitude": prop.latitude,
                "longitude": prop.longitude,
                "reason": loc.get("maptiler_reason"),
                "building_reason": loc.get("building_reason"),
                "http_status": loc.get("maptiler_http_status"),
                "checked_at": loc.get("auto_resolution_checked_at"),
            }


async def refresh_existing_property_locations(territory_id: str | None = None) -> None:
    """Locate pending RentCast properties in a separate, resumable MapTiler phase."""
    if _running_lock.locked():
        logger.info("Property location resolver already running; duplicate request skipped")
        return

    async with _running_lock:
        async with SessionLocal() as db:
            try:
                key = await _maptiler_key(db)
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
                logger.info("Property location resolution already current (%s)", RESOLUTION_VERSION)
                return

            logger.info("Starting MapTiler property location pass for %d properties", len(pending))
            semaphore = asyncio.Semaphore(CONCURRENCY)
            processed = 0
            resolved_count = 0
            retry_pending = 0

            for tid in {str(p.territory_id) for p in pending}:
                territory = territories[tid]
                group = [p for p in pending if str(p.territory_id) == tid]
                for start in range(0, len(group), CHUNK_SIZE):
                    chunk = group[start:start + CHUNK_SIZE]
                    tasks = [
                        _resolve_one(key, p.formatted_address or "", territory, semaphore)
                        for p in chunk
                    ]
                    results = await asyncio.gather(*tasks)

                    for prop, result in zip(chunk, results):
                        _store_result(prop, result, territory)
                        processed += 1
                        if result.get("status") in ("accepted", "located"):
                            resolved_count += 1
                        if result.get("status") == "error":
                            retry_pending += 1
                    await db.commit()
                    await asyncio.sleep(0)

            logger.info(
                "MapTiler property location pass finished: processed=%d resolved=%d retry_pending=%d version=%s",
                processed,
                resolved_count,
                retry_pending,
                RESOLUTION_VERSION,
            )
