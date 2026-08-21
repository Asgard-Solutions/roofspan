import math

import httpx
from fastapi import APIRouter, Depends, Request, HTTPException, Response, Query
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


def _xyz_tile(lng: float, lat: float, zoom: int) -> tuple[int, int, int]:
    """Convert WGS84 lon/lat to a Web Mercator XYZ tile."""
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2 ** zoom
    x = int((lng + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))
    return zoom, x, y


def _valid_center(value) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
        and math.isfinite(value[0])
        and math.isfinite(value[1])
        and -180 <= value[0] <= 180
        and -90 <= value[1] <= 90
    )


def _valid_bbox(value) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(isinstance(v, (int, float)) and math.isfinite(v) for v in value)
        and -180 <= value[0] <= 180
        and -90 <= value[1] <= 90
        and -180 <= value[2] <= 180
        and -90 <= value[3] <= 90
        and value[0] < value[2]
        and value[1] < value[3]
    )


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


def _integration_secret_usable(row: IntegrationSetting | None) -> bool:
    """Return True only when an enabled stored integration secret can actually be decrypted.

    Old RoofSpan installs may retain ciphertext after the installation encryption key changes. Treat
    that as unconfigured instead of advertising a provider that will only fail at runtime.
    """
    if not (row and row.enabled and row.secret_ciphertext):
        return False
    try:
        from core import decrypt_secret
        decrypt_secret(row.secret_ciphertext)
        return True
    except Exception:
        return False


async def _maptiler_key(db: AsyncSession) -> str | None:
    """Return the one configured MapTiler API key for all MapTiler services."""
    from core import decrypt_secret

    row = (await db.execute(select(IntegrationSetting).where(IntegrationSetting.provider == "maptiler"))).scalar_one_or_none()
    if not (row and row.enabled and row.secret_ciphertext):
        return None
    try:
        return decrypt_secret(row.secret_ciphertext)
    except Exception:
        return None


# ---- Map configuration ----
@router.get("/map-config", response_model=MapConfigOut)
async def get_map_config(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cfg = await _get_config(db, "map_config", DEFAULT_MAP)
    maptiler = (await db.execute(select(IntegrationSetting).where(IntegrationSetting.provider == "maptiler"))).scalar_one_or_none()
    maptiler_configured = _integration_secret_usable(maptiler)
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


@router.get("/geocode/zip")
async def geocode_zip(
    zip: str = Query(..., min_length=3, max_length=16),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Center the map on a ZIP/postal code using the configured server-side MapTiler key."""
    code = zip.strip()
    if not code:
        raise HTTPException(status_code=422, detail="ZIP / postal code is required")

    key = await _maptiler_key(db)
    if not key:
        raise HTTPException(status_code=503, detail="MapTiler is not configured. Add and enable a MapTiler key in Settings.")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://api.maptiler.com/geocoding/{code}.json",
                params={
                    "key": key,
                    "types": "postal_code",
                    "country": "us",
                    "limit": 5,
                    "autocomplete": "false",
                    "fuzzyMatch": "false",
                    "worldview": "us",
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not reach MapTiler ZIP search.") from exc

    if r.status_code in (401, 403):
        raise HTTPException(status_code=503, detail="MapTiler rejected the configured API key.")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"MapTiler ZIP search failed with HTTP {r.status_code}.")

    try:
        payload = r.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="MapTiler returned an invalid ZIP-search response.") from exc

    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        features = []

    normalized_code = code.split("-", 1)[0].strip().lower()
    feature = None
    for candidate in features:
        if not isinstance(candidate, dict):
            continue
        place_types = candidate.get("place_type") or []
        if isinstance(place_types, str):
            place_types = [place_types]
        if "postal_code" not in place_types:
            continue
        candidate_code = str(candidate.get("text") or candidate.get("matching_text") or "").strip().lower()
        if candidate_code == normalized_code:
            feature = candidate
            break
        if feature is None:
            feature = candidate

    if not feature:
        raise HTTPException(status_code=404, detail=f'ZIP / postal code "{code}" was not found.')

    center = feature.get("center")
    if not _valid_center(center):
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")
        center = coords if geometry.get("type") == "Point" and _valid_center(coords) else None
    if not _valid_center(center):
        raise HTTPException(status_code=502, detail="MapTiler returned a ZIP result without usable coordinates.")

    bbox = feature.get("bbox")
    approximate_bbox = False
    if not _valid_bbox(bbox):
        lng, lat = float(center[0]), float(center[1])
        lat_pad = 0.05
        lng_pad = 0.05 / max(math.cos(math.radians(lat)), 0.25)
        bbox = [
            max(-180.0, lng - lng_pad),
            max(-90.0, lat - lat_pad),
            min(180.0, lng + lng_pad),
            min(90.0, lat + lat_pad),
        ]
        approximate_bbox = True

    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        geometry = None

    return {
        "zip": code,
        "display_name": feature.get("place_name") or feature.get("matching_place_name") or feature.get("text") or code,
        "center": [float(center[0]), float(center[1])],
        "bbox": [[float(bbox[0]), float(bbox[1])], [float(bbox[2]), float(bbox[3])]],
        "geometry": geometry,
        "bbox_approximate": approximate_bbox,
        "provider": "maptiler",
    }


@router.get("/map/cadastre-capability")
async def cadastre_capability(
    lat: float | None = Query(None, ge=-85.05112878, le=85.05112878),
    lng: float | None = Query(None, ge=-180.0, le=180.0),
    zoom: int = Query(16, ge=12, le=18),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check whether the existing MapTiler key can access Cadastre and optionally has tile coverage.

    No API key or provider payload is returned to the client. A coordinate check requests only the
    single Cadastre vector tile covering that point. HTTP 204 means the tileset is accessible but the
    requested tile has no data; 403/404 distinguish key access from an unavailable tileset.
    """
    if (lat is None) != (lng is None):
        raise HTTPException(status_code=422, detail="lat and lng must be supplied together")

    key = await _maptiler_key(db)
    if not key:
        return {
            "configured": False,
            "tileset_accessible": False,
            "tileset_http_status": None,
            "coverage_checked": False,
            "coverage_available": None,
            "coverage_http_status": None,
            "tile": None,
            "reason": "maptiler_not_configured",
        }

    tilejson_url = "https://api.maptiler.com/tiles/cadastre/tiles.json"
    result = {
        "configured": True,
        "tileset_accessible": False,
        "tileset_http_status": None,
        "coverage_checked": lat is not None,
        "coverage_available": None,
        "coverage_http_status": None,
        "tile": None,
        "reason": "unknown",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            meta = await client.get(tilejson_url, params={"key": key})
            result["tileset_http_status"] = meta.status_code
            result["tileset_accessible"] = meta.status_code == 200
            if meta.status_code == 403:
                result["reason"] = "cadastre_not_authorized"
                return result
            if meta.status_code == 404:
                result["reason"] = "cadastre_tileset_unavailable"
                return result
            if meta.status_code != 200:
                result["reason"] = "cadastre_metadata_error"
                return result

            if lat is None:
                result["reason"] = "cadastre_tileset_accessible"
                return result

            z, x, y = _xyz_tile(lng, lat, zoom)
            result["tile"] = {"z": z, "x": x, "y": y}
            tile_url = f"https://api.maptiler.com/tiles/cadastre/{z}/{x}/{y}"
            tile = await client.get(tile_url, params={"key": key})
            result["coverage_http_status"] = tile.status_code

            if tile.status_code == 200:
                result["coverage_available"] = len(tile.content) > 0
                result["reason"] = "cadastre_coverage_available" if result["coverage_available"] else "cadastre_tile_empty"
            elif tile.status_code == 204:
                result["coverage_available"] = False
                result["reason"] = "cadastre_no_coverage"
            elif tile.status_code == 403:
                result["coverage_available"] = False
                result["reason"] = "cadastre_not_authorized"
            elif tile.status_code == 404:
                result["coverage_available"] = False
                result["reason"] = "cadastre_tile_unavailable"
            else:
                result["coverage_available"] = False
                result["reason"] = "cadastre_tile_error"
            return result
    except httpx.HTTPError:
        result["reason"] = "cadastre_request_error"
        return result


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
    key = await _maptiler_key(db)
    if not key:
        raise HTTPException(status_code=404, detail="Satellite imagery is not configured")
    url = f"https://api.maptiler.com/tiles/satellite-v2/{z}/{x}/{y}.jpg"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params={"key": key})
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
        "phase": "Office Phase 1 — Foundation",
        "current_user": {"email": user.email, "role": user.role, "full_name": user.full_name},
    }
