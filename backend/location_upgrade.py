"""Second-phase MapTiler resolver for stored RentCast properties.

RentCast acquisition and MapTiler location resolution are deliberately separate jobs. Properties are
saved first with their RentCast coordinates, then this resumable background worker resolves exact
addresses and numbered buildings without risking the completed property import.
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

RESOLUTION_VERSION = "maptiler_numbered_building_v2"
CHUNK_SIZE = 25
CONCURRENCY = 8

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
        loc["coordinate_source"] = (
            "maptiler_numbered_building"
            if result.get("building_status") == "resolved"
            else "maptiler_address"
        )
    else:
        loc["coordinate_source"] = previous.get("coordinate_source") or "rentcast"

    # Transport/provider errors remain retryable. Deterministic accepted/rejected results are marked
    # current for this resolver version so a restart resumes only the unfinished work.
    if result.get("status") == "error":
        loc["auto_resolution_version"] = None
        loc["resolution_state"] = "retry_pending"
    else:
        loc["auto_resolution_version"] = RESOLUTION_VERSION
        loc["resolution_state"] = "complete"

    raw["roofspan_location"] = loc
    prop.raw = raw


async def _resolve_one(key: str, address: str, territory: Territory, semaphore: asyncio.Semaphore) -> dict:
    """Use a single-address MapTiler request so one bad/bulk URL cannot poison neighboring records."""
    async with semaphore:
        try:
            results = await geocode_addresses_batch(
                key,
                [address],
                bbox=bbox(territory.geometry),
                country="us",
                min_relevance=0.80,
            )
            if len(results) == 1:
                return results[0]
            return {
                "status": "error", "reason": "single_result_count_mismatch", "http_status": None,
                "feature": None, "returned_address": None, "returned_label": None,
                "relevance": None, "place_type": None, "latitude": None, "longitude": None,
                "feature_id": None, "building_status": "not_attempted", "building_reason": "not_attempted",
            }
        except Exception as exc:
            logger.warning("Single-address MapTiler resolution failed for %s: %s", address, exc.__class__.__name__)
            return {
                "status": "error", "reason": "single_request_exception", "http_status": None,
                "feature": None, "returned_address": None, "returned_label": None,
                "relevance": None, "place_type": None, "latitude": None, "longitude": None,
                "feature_id": None, "building_status": "not_attempted", "building_reason": "not_attempted",
            }


async def refresh_existing_property_locations(territory_id: str | None = None) -> None:
    """Resolve pending RentCast properties in a separate, resumable MapTiler phase."""
    if _running_lock.locked():
        logger.info("Property location resolver already running; duplicate request skipped")
        return

    async with _running_lock:
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(IntegrationSetting).where(IntegrationSetting.provider == "maptiler")
                )
            ).scalar_one_or_none()
            if not (row and row.enabled and row.secret_ciphertext):
                logger.info("Property location resolution skipped: MapTiler is not configured")
                return
            try:
                key = decrypt_secret(row.secret_ciphertext)
            except Exception:
                logger.warning("Property location resolution skipped: MapTiler key cannot be decrypted")
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

            logger.info("Starting MapTiler second-phase resolution for %d properties", len(pending))
            semaphore = asyncio.Semaphore(CONCURRENCY)
            processed = 0
            resolved = 0
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
                        if result.get("status") == "accepted" and result.get("building_status") == "resolved":
                            resolved += 1
                        if result.get("status") == "error":
                            retry_pending += 1
                    await db.commit()
                    await asyncio.sleep(0)

            logger.info(
                "MapTiler second-phase resolution finished: processed=%d building_resolved=%d retry_pending=%d version=%s",
                processed,
                resolved,
                retry_pending,
                RESOLUTION_VERSION,
            )
