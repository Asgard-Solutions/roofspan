import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import decrypt_secret, require_tile_access
from db import get_db
from models import IntegrationSetting

router = APIRouter(prefix="/api/map/tiles", tags=["map"])


async def _maptiler_key(db: AsyncSession) -> str | None:
    row = (
        await db.execute(
            select(IntegrationSetting).where(IntegrationSetting.provider == "maptiler")
        )
    ).scalar_one_or_none()
    if not (row and row.enabled and row.secret_ciphertext):
        return None
    try:
        return decrypt_secret(row.secret_ciphertext)
    except Exception:
        return None


@router.get("/buildings/{z}/{x}/{y}")
async def buildings_tile(
    z: int,
    x: int,
    y: int,
    _: bool = Depends(require_tile_access),
    db: AsyncSession = Depends(get_db),
):
    """Proxy MapTiler Buildings vector tiles so the provider key never reaches the browser."""
    key = await _maptiler_key(db)
    if not key:
        raise HTTPException(status_code=404, detail="MapTiler Buildings is not configured")

    url = f"https://api.maptiler.com/tiles/buildings/{z}/{x}/{y}"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, params={"key": key})

    if response.status_code == 204:
        return Response(status_code=204)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Building tile provider error")

    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", "application/vnd.mapbox-vector-tile"),
        headers={"Cache-Control": "private, max-age=3600"},
    )
