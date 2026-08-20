"""Background migration of existing RentCast property pins to the current MapTiler resolver.

This is intentionally data-only and idempotent. Existing property records are upgraded in
place after an application update; users do not need to delete/re-import territories.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from core import decrypt_secret
from db import SessionLocal
from geo import bbox, point_in_polygon
from maptiler import geocode_addresses_batch
from models import IntegrationSetting, Property, Territory

logger = logging.getLogger("roofspan.location_upgrade")

RESOLUTION_VERSION = "maptiler_numbered_building_v1"
BATCH_SIZE = 50

_running_lock = asyncio.Lock()


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


def _store_result(prop: Property, result: dict, territory: Territory) -> None:
    raw = dict(prop.raw or {})
    previous = raw.get("roofspan_location") if isinstance(raw.get("roofspan_location"), dict) else {}
    rentcast_lat, rentcast_lng = _rentcast_source_coords(prop)

    loc = dict(previous)
    loc.update({
        "query_address": prop.formatted_address,
        "rentcast_latitude": rentcast_lat,
        "rentcast_longitude": rentcast_lng,
        "maptiler_status": result.get("status"),
        "maptiler_reason": result.get("reason"),
        "maptiler_http_status": result.get("http_status"),
        "maptiler_returned_address": result.get("returned_address"),
        "maptiler_returned_label": result.get("returned_label"),
        "maptiler_latitude": result.get("latitude"),
        "maptiler_longitude": result.get("longitude"),
        "maptiler_relevance": result.get("relevance"),
        "maptiler_place_type": result.get("place_type"),
        "maptiler_feature_id": result.get("feature_id"),
        "identity_expected": result.get("identity_expected"),
        "identity_returned": result.get("identity_returned"),
        "identity_checks": result.get("identity_checks"),
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
        "auto_resolution_version": RESOLUTION_VERSION,
        "auto_resolution_checked_at": _now_iso(),
    })

    candidate_lat = result.get("latitude")
    candidate_lng = result.get("longitude")
    accepted = result.get("status") == "accepted"
    inside = (
        accepted
        and candidate_lat is not None
        and candidate_lng is not None
        and point_in_polygon(candidate_lng, candidate_lat, territory.geometry)
    )
    if inside:
        prop.latitude = candidate_lat
        prop.longitude = candidate_lng
        if result.get("building_status") == "resolved":
            loc["coordinate_source"] = "maptiler_numbered_building"
        else:
            loc["coordinate_source"] = "maptiler_address"
    else:
        loc["coordinate_source"] = previous.get("coordinate_source") or "rentcast"

    raw["roofspan_location"] = loc
    prop.raw = raw


async def refresh_existing_property_locations() -> None:
    """Upgrade existing RentCast properties once per resolver version in the background."""
    if _running_lock.locked():
        return
    async with _running_lock:
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(IntegrationSetting).where(IntegrationSetting.provider == "maptiler")
                )
            ).scalar_one_or_none()
            if not (row and row.enabled and row.secret_ciphertext):
                logger.info("Property location upgrade skipped: MapTiler is not configured")
                return
            try:
                key = decrypt_secret(row.secret_ciphertext)
            except Exception:
                logger.warning("Property location upgrade skipped: MapTiler key cannot be decrypted")
                return

            territories = {
                str(t.id): t
                for t in (await db.execute(select(Territory))).scalars().all()
            }
            props = (
                await db.execute(
                    select(Property).where(
                        Property.source == "rentcast",
                        Property.territory_id.isnot(None),
                    ).order_by(Property.created_at.asc())
                )
            ).scalars().all()
            pending = [p for p in props if _needs_upgrade(p) and str(p.territory_id) in territories]
            if not pending:
                logger.info("Property location upgrade already current (%s)", RESOLUTION_VERSION)
                return

            logger.info("Starting automatic property location upgrade for %d properties", len(pending))
            processed = 0
            resolved = 0
            for territory_id in {str(p.territory_id) for p in pending}:
                territory = territories[territory_id]
                group = [p for p in pending if str(p.territory_id) == territory_id]
                for start in range(0, len(group), BATCH_SIZE):
                    batch = group[start:start + BATCH_SIZE]
                    addresses = [p.formatted_address or "" for p in batch]
                    try:
                        results = await geocode_addresses_batch(
                            key,
                            addresses,
                            bbox=bbox(territory.geometry),
                            country="us",
                            min_relevance=0.80,
                        )
                    except Exception as exc:
                        logger.warning("Location upgrade batch failed (%s): %s", territory_id, exc.__class__.__name__)
                        # Do not mark this batch current; a later startup can retry it.
                        continue

                    if len(results) != len(batch):
                        logger.warning("Location upgrade batch result count mismatch for territory %s", territory_id)
                        continue

                    for prop, result in zip(batch, results):
                        _store_result(prop, result, territory)
                        processed += 1
                        if result.get("status") == "accepted" and result.get("building_status") == "resolved":
                            resolved += 1
                    await db.commit()
                    # Yield so startup refresh never monopolizes the event loop.
                    await asyncio.sleep(0)

            logger.info(
                "Automatic property location upgrade finished: processed=%d building_resolved=%d version=%s",
                processed,
                resolved,
                RESOLUTION_VERSION,
            )
