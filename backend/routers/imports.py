import asyncio
import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db, SessionLocal
from models import Territory, Property, PropertyContact, ImportJob, IntegrationSetting, User
from core import require_roles, MANAGE_ROLES, decrypt_secret, log_action
from schemas_phase2 import ImportPreviewIn, ImportPreviewOut, ImportStartIn, ImportJobOut
from geo import centroid, enclosing_radius_miles, point_in_polygon
from rentcast import fetch_rentcast_properties, normalize_rentcast, generate_sample_properties

router = APIRouter(prefix="/api", tags=["imports"])


def _now():
    return datetime.now(timezone.utc)


def _job_out(j: ImportJob) -> ImportJobOut:
    return ImportJobOut(
        id=str(j.id), territory_id=str(j.territory_id) if j.territory_id else None, mode=j.mode,
        status=j.status, estimated_requests=j.estimated_requests, estimated_properties=j.estimated_properties,
        total=j.total, processed=j.processed, created_count=j.created_count, updated_count=j.updated_count,
        skipped_count=j.skipped_count, error=j.error, created_by=j.created_by,
        created_at=j.created_at, finished_at=j.finished_at,
    )


async def _integration_setting(db: AsyncSession, provider: str) -> IntegrationSetting | None:
    return (await db.execute(select(IntegrationSetting).where(IntegrationSetting.provider == provider))).scalar_one_or_none()


async def _rentcast_setting(db: AsyncSession) -> IntegrationSetting | None:
    return await _integration_setting(db, "rentcast")


def _usable_secret(row: IntegrationSetting | None) -> str | None:
    if not (row and row.enabled and row.secret_ciphertext):
        return None
    try:
        return decrypt_secret(row.secret_ciphertext)
    except Exception:
        return None


def _resolve_mode(requested: str | None, configured: bool) -> str:
    if requested in ("rentcast", "sample"):
        return requested
    return "rentcast" if configured else "sample"


def _mark_location_pending(nd: dict) -> None:
    """Persist RentCast coordinates immediately and queue Geocodio as a separate pin-location phase."""
    raw = dict(nd.get("raw") or {})
    raw["roofspan_location"] = {
        "query_address": nd.get("formatted_address") or "",
        "rentcast_latitude": nd.get("latitude"),
        "rentcast_longitude": nd.get("longitude"),
        "coordinate_source": "rentcast",
        "location_provider": "geocodio",
        "geocoder_status": "pending",
        "geocoder_reason": "queued_after_rentcast_import",
        "geocoder_http_status": None,
        "geocodio_formatted_address": None,
        "geocodio_latitude": None,
        "geocodio_longitude": None,
        "geocodio_accuracy": None,
        "geocodio_accuracy_type": None,
        "geocodio_match_type": None,
        "geocodio_source": None,
        "geocodio_stable_address_key": None,
        "location_resolved": False,
        "location_quality": None,
        "cached_permanently": False,
        "cached_at": None,
        "auto_resolution_version": None,
        "auto_resolution_checked_at": None,
        "queued_at": _now().isoformat(),
    }
    nd["raw"] = raw


def _preserve_permanent_location_cache(existing: Property, nd: dict) -> dict:
    """A RentCast refresh must not spend another geocode lookup when the address did not change."""
    new_raw = dict(nd.get("raw") or {})
    old_raw = existing.raw if isinstance(existing.raw, dict) else {}
    old_loc = old_raw.get("roofspan_location") if isinstance(old_raw.get("roofspan_location"), dict) else {}
    if (
        old_loc.get("cached_permanently") is True
        and old_loc.get("location_provider") == "geocodio"
        and str(old_loc.get("query_address") or "").strip().lower() == str(nd.get("formatted_address") or "").strip().lower()
    ):
        new_raw["roofspan_location"] = dict(old_loc)
    return new_raw


@router.post("/territories/{territory_id}/import/preview", response_model=ImportPreviewOut)
async def import_preview(territory_id: str, payload: ImportPreviewIn, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    t = await db.get(Territory, territory_id)
    if not t:
        raise HTTPException(status_code=404, detail="Territory not found")
    setting = await _rentcast_setting(db)
    configured = bool(_usable_secret(setting))
    mode = _resolve_mode(payload.mode, configured)
    radius = round(enclosing_radius_miles(t.geometry), 2)

    if mode == "rentcast":
        if not configured:
            raise HTTPException(status_code=400, detail="RentCast is not configured. Enable it and add a key in Settings, or use sample data.")
        clng, clat = centroid(t.geometry)
        key = _usable_secret(setting)
        try:
            raws = await fetch_rentcast_properties(key, clat, clng, radius, min(payload.max_records, 50))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"RentCast preview failed: {e.__class__.__name__}")
        inside = [normalize_rentcast(r) for r in raws if r.get("latitude") and r.get("longitude") and point_in_polygon(r["longitude"], r["latitude"], t.geometry)]
        est_requests = math.ceil(payload.max_records / 500)
        return ImportPreviewOut(
            mode="rentcast", rentcast_configured=True, estimated_requests=est_requests,
            estimated_properties=min(payload.max_records, len(inside)) if inside else 0,
            radius_miles=radius, sample=inside[:10],
            note=f"Full import will first save up to {payload.max_records} RentCast properties (~{est_requests} request(s)). Geocodio pin location runs separately afterward when configured, and completed results are reused from the local cache.",
        )

    generated = generate_sample_properties(str(t.id), t.geometry, payload.max_records)
    return ImportPreviewOut(
        mode="sample", rentcast_configured=configured, estimated_requests=0,
        estimated_properties=len(generated), radius_miles=radius, sample=generated[:10],
        note="Sample data (RentCast not used). Generates demo properties inside the territory for workflow testing.",
    )


async def _run_import(job_id: str, territory_id: str, mode: str, max_records: int):
    should_resolve_locations = False
    async with SessionLocal() as db:
        job = await db.get(ImportJob, job_id)
        territory = await db.get(Territory, territory_id)
        if not job or not territory:
            return
        job.status = "running"
        await db.commit()
        try:
            if mode == "rentcast":
                setting = await _rentcast_setting(db)
                key = _usable_secret(setting)
                if not key:
                    raise RuntimeError("RentCast is not configured")
                clng, clat = centroid(territory.geometry)
                radius = enclosing_radius_miles(territory.geometry)
                raws = await fetch_rentcast_properties(key, clat, clng, radius, max_records)
                normalized = [
                    normalize_rentcast(r)
                    for r in raws
                    if r.get("latitude") and r.get("longitude")
                    and point_in_polygon(r["longitude"], r["latitude"], territory.geometry)
                ]
                for nd in normalized:
                    _mark_location_pending(nd)
                should_resolve_locations = True
            else:
                normalized = generate_sample_properties(str(territory.id), territory.geometry, max_records)

            job.total = len(normalized)
            await db.commit()

            for nd in normalized:
                ext = nd.get("external_id")
                if not ext:
                    job.skipped_count += 1
                    job.processed += 1
                    continue
                existing = (await db.execute(select(Property).where(Property.external_id == ext))).scalar_one_or_none()
                owner = nd.get("owner") or {}
                if existing:
                    preserved_raw = _preserve_permanent_location_cache(existing, nd) if mode == "rentcast" else nd["raw"]
                    existing.formatted_address = nd["formatted_address"]
                    existing.address_line1 = nd["address_line1"]
                    existing.city = nd["city"]
                    existing.state = nd["state"]
                    existing.zip_code = nd["zip_code"]
                    existing.latitude = nd["latitude"]
                    existing.longitude = nd["longitude"]
                    existing.property_type = nd["property_type"]
                    existing.bedrooms = nd["bedrooms"]
                    existing.bathrooms = nd["bathrooms"]
                    existing.square_footage = nd["square_footage"]
                    existing.year_built = nd["year_built"]
                    existing.owner_occupied = nd["owner_occupied"]
                    existing.raw = preserved_raw
                    # If a permanent location was preserved, keep that cached pin instead of the
                    # newly refreshed RentCast coordinate.
                    preserved_loc = preserved_raw.get("roofspan_location") if isinstance(preserved_raw, dict) else None
                    if isinstance(preserved_loc, dict) and preserved_loc.get("cached_permanently") and preserved_loc.get("location_resolved"):
                        existing.latitude = preserved_loc.get("geocodio_latitude") or existing.latitude
                        existing.longitude = preserved_loc.get("geocodio_longitude") or existing.longitude
                    if existing.territory_id is None:
                        existing.territory_id = territory.id
                    oc = (await db.execute(select(PropertyContact).where(PropertyContact.property_id == existing.id, PropertyContact.kind == "owner"))).scalars().first()
                    if oc:
                        oc.name = owner.get("name") or oc.name
                        oc.contact_type = owner.get("type") or oc.contact_type
                        oc.mailing_address = owner.get("mailing_address") or oc.mailing_address
                    elif owner.get("name"):
                        db.add(PropertyContact(property_id=existing.id, kind="owner", name=owner["name"], contact_type=owner.get("type"), mailing_address=owner.get("mailing_address")))
                    job.updated_count += 1
                else:
                    p = Property(
                        external_id=ext, source=nd["source"], territory_id=territory.id,
                        formatted_address=nd["formatted_address"], address_line1=nd["address_line1"],
                        address_line2=nd.get("address_line2"), city=nd["city"], state=nd["state"], zip_code=nd["zip_code"],
                        latitude=nd["latitude"], longitude=nd["longitude"], property_type=nd["property_type"],
                        bedrooms=nd["bedrooms"], bathrooms=nd["bathrooms"], square_footage=nd["square_footage"],
                        year_built=nd["year_built"], owner_occupied=nd["owner_occupied"], raw=nd["raw"],
                    )
                    db.add(p)
                    await db.flush()
                    if owner.get("name"):
                        db.add(PropertyContact(property_id=p.id, kind="owner", name=owner["name"], contact_type=owner.get("type"), mailing_address=owner.get("mailing_address")))
                    job.created_count += 1
                job.processed += 1
                if job.processed % 10 == 0:
                    await db.commit()

            job.status = "completed"
            job.finished_at = _now()
            await db.commit()
        except Exception as e:
            await db.rollback()
            job.status = "failed"
            job.error = str(e)[:400]
            job.finished_at = _now()
            await db.commit()
            should_resolve_locations = False

    if should_resolve_locations:
        # Phase 2 is deliberately separate from RentCast acquisition. Provider failures cannot roll
        # back property acquisition, and permanent cached rows are skipped on later runs.
        from location_upgrade import refresh_existing_property_locations
        asyncio.create_task(refresh_existing_property_locations(territory_id=territory_id))


@router.post("/territories/{territory_id}/import", response_model=ImportJobOut, status_code=202)
async def start_import(territory_id: str, payload: ImportStartIn, request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    t = await db.get(Territory, territory_id)
    if not t:
        raise HTTPException(status_code=404, detail="Territory not found")
    setting = await _rentcast_setting(db)
    configured = bool(_usable_secret(setting))
    mode = _resolve_mode(payload.mode, configured)
    if mode == "rentcast" and not configured:
        raise HTTPException(status_code=400, detail="RentCast is not configured")
    est_requests = math.ceil(payload.max_records / 500) if mode == "rentcast" else 0
    job = ImportJob(
        territory_id=t.id, mode=mode, status="pending", estimated_requests=est_requests,
        estimated_properties=payload.max_records, params={"max_records": payload.max_records}, created_by=user.email,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await log_action(db, user=user, action="import.start", entity_type="territory", entity_id=t.id, detail={"mode": mode, "max_records": payload.max_records}, request=request)
    asyncio.create_task(_run_import(str(job.id), str(t.id), mode, payload.max_records))
    return _job_out(job)


@router.get("/territories/{territory_id}/location-resolution")
async def location_resolution_status(territory_id: str, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    territory = await db.get(Territory, territory_id)
    if not territory:
        raise HTTPException(status_code=404, detail="Territory not found")
    props = (await db.execute(select(Property).where(Property.territory_id == territory.id, Property.source == "rentcast"))).scalars().all()
    counts = {"total": len(props), "pending": 0, "resolved": 0, "address_only": 0, "unresolved": 0, "errors": 0}
    for prop in props:
        raw = prop.raw if isinstance(prop.raw, dict) else {}
        loc = raw.get("roofspan_location") if isinstance(raw.get("roofspan_location"), dict) else {}
        status = loc.get("geocoder_status")
        if status in (None, "pending", "not_attempted"):
            counts["pending"] += 1
        elif status == "error":
            counts["errors"] += 1
        elif loc.get("location_resolved") or status == "located":
            counts["resolved"] += 1
        else:
            counts["unresolved"] += 1
    counts["complete"] = counts["pending"] == 0
    return counts


@router.get("/imports/{job_id}", response_model=ImportJobOut)
async def get_import(job_id: str, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    j = await db.get(ImportJob, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Import job not found")
    return _job_out(j)


@router.get("/imports", response_model=list[ImportJobOut])
async def list_imports(territory_id: str | None = None, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    stmt = select(ImportJob).order_by(ImportJob.created_at.desc()).limit(25)
    if territory_id:
        stmt = stmt.where(ImportJob.territory_id == territory_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [_job_out(j) for j in rows]
