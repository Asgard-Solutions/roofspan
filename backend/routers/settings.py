import httpx
from fastapi import APIRouter, Depends, Request, HTTPException, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import AppConfig, IntegrationSetting, User, AuditLog
from core import require_roles, get_current_user, SENSITIVE_ROLES, log_action
from schemas import MapConfigOut, MapConfigUpdate, CompanyProfile

router = APIRouter(prefix="/api", tags=["settings"])

OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
DEFAULT_MAP = {
    "satellite_enabled": False,
    "default_center": [-97.7431, 30.2672],  # Austin, TX [lng, lat]
    "default_zoom": 11.0,
}


async def _get_config(db: AsyncSession, key: str, default: dict) -> dict:
    row = (await db.execute(select(AppConfig).where(AppConfig.key == key))).scalar_one_or_none()
    if not row:
        row = AppConfig(key=key, value=default)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row.value


async def _set_config(db: AsyncSession, key: str, value: dict):
    row = (await db.execute(select(AppConfig).where(AppConfig.key == key))).scalar_one_or_none()
    if not row:
        row = AppConfig(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    await db.commit()


# ---- Map configuration ----
@router.get("/map-config", response_model=MapConfigOut)
async def get_map_config(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cfg = await _get_config(db, "map_config", DEFAULT_MAP)
    maptiler = (await db.execute(select(IntegrationSetting).where(IntegrationSetting.provider == "maptiler"))).scalar_one_or_none()
    maptiler_configured = bool(maptiler and maptiler.secret_ciphertext and maptiler.enabled)
    return MapConfigOut(
        base_provider="openstreetmap",
        base_style_url="",
        osm_tile_url=OSM_TILE_URL,
        attribution=OSM_ATTRIBUTION,
        satellite_enabled=bool(cfg.get("satellite_enabled", False)) and maptiler_configured,
        maptiler_configured=maptiler_configured,
        default_center=cfg.get("default_center", DEFAULT_MAP["default_center"]),
        default_zoom=float(cfg.get("default_zoom", DEFAULT_MAP["default_zoom"])),
    )


@router.put("/map-config", response_model=MapConfigOut)
async def update_map_config(payload: MapConfigUpdate, request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    cfg = dict(await _get_config(db, "map_config", DEFAULT_MAP))
    if payload.satellite_enabled is not None:
        cfg["satellite_enabled"] = payload.satellite_enabled
    if payload.default_center is not None:
        cfg["default_center"] = payload.default_center
    if payload.default_zoom is not None:
        cfg["default_zoom"] = payload.default_zoom
    await _set_config(db, "map_config", cfg)
    await log_action(db, user=user, action="map_config.update", entity_type="config", entity_id="map_config", request=request)
    return await get_map_config(user=user, db=db)


# ---- ZIP / postal code geocoding (server-side proxy to OSM Nominatim; only the ZIP leaves the machine) ----
@router.get("/geocode/zip")
async def geocode_zip(zip: str, country: str = "us", user: User = Depends(get_current_user)):
    code = (zip or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Enter a ZIP or postal code")
    params = {
        "postalcode": code,
        "countrycodes": (country or "us").strip().lower(),
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 0,
    }
    headers = {"User-Agent": "RoofSpanOffice/1.0 (territory mapping)"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach the geocoding service. Check your internet connection.")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Geocoding service error. Please try again.")
    results = r.json()
    if not results:
        raise HTTPException(status_code=404, detail=f"No location found for ZIP/postal code '{code}'")
    hit = results[0]
    # Nominatim boundingbox = [south, north, west, east] (strings). Return [lng, lat] geometry.
    bb = [float(x) for x in hit["boundingbox"]]
    south, north, west, east = bb[0], bb[1], bb[2], bb[3]
    return {
        "center": [float(hit["lon"]), float(hit["lat"])],
        "bbox": [[west, south], [east, north]],
        "display_name": hit.get("display_name", code),
    }


# ---- Company profile ----
@router.get("/company", response_model=CompanyProfile)
async def get_company(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cfg = await _get_config(db, "company_profile", CompanyProfile().model_dump())
    return CompanyProfile(**{**CompanyProfile().model_dump(), **cfg})


@router.put("/company", response_model=CompanyProfile)
async def update_company(payload: CompanyProfile, request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    await _set_config(db, "company_profile", payload.model_dump())
    await log_action(db, user=user, action="company.update", entity_type="config", entity_id="company_profile", request=request)
    return payload


# ---- MapTiler satellite tile proxy (keeps provider key server-side) ----
@router.get("/map/tiles/satellite/{z}/{x}/{y}")
async def satellite_tile(z: int, x: int, y: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from core import decrypt_secret
    row = (await db.execute(select(IntegrationSetting).where(IntegrationSetting.provider == "maptiler"))).scalar_one_or_none()
    if not (row and row.enabled and row.secret_ciphertext):
        raise HTTPException(status_code=404, detail="Satellite imagery is not configured")
    try:
        key = decrypt_secret(row.secret_ciphertext)
    except Exception:
        raise HTTPException(status_code=500, detail="Could not read MapTiler key")
    url = f"https://api.maptiler.com/tiles/satellite-v2/{z}/{x}/{y}.jpg?key={key}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail="Tile provider error")
    return Response(content=r.content, media_type=r.headers.get("content-type", "image/jpeg"))


# ---- Dashboard summary ----
@router.get("/dashboard/summary")
async def dashboard_summary(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    active_users = (await db.execute(select(func.count(User.id)).where(User.is_active == True))).scalar_one()  # noqa: E712
    is_sensitive = user.role in SENSITIVE_ROLES
    recent = []
    audit_total = 0
    if is_sensitive:
        audit_total = (await db.execute(select(func.count(AuditLog.id)))).scalar_one()
        rows = (await db.execute(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(5))).scalars().all()
        recent = [
            {"timestamp": r.timestamp.isoformat(), "user_email": r.user_email, "action": r.action}
            for r in rows
        ]
    return {
        "users": {"total": total_users, "active": active_users},
        "audit_total": audit_total,
        "recent_activity": recent,
        "current_user": {"email": user.email, "role": user.role, "full_name": user.full_name},
    }
