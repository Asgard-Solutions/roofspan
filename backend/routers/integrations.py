import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import IntegrationSetting, User
from core import require_roles, SENSITIVE_ROLES, encrypt_secret, decrypt_secret, log_action
from schemas import IntegrationOut, IntegrationUpdate, SecretUpdate, TestConnectionResult

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

KNOWN_PROVIDERS = {
    "rentcast": {"label": "RentCast", "config_defaults": {}},
    "maptiler": {"label": "MapTiler", "config_defaults": {}},
    "geocodio": {"label": "Geocodio", "config_defaults": {}},
}


async def _get_or_create(db: AsyncSession, provider: str) -> IntegrationSetting:
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    row = (await db.execute(select(IntegrationSetting).where(IntegrationSetting.provider == provider))).scalar_one_or_none()
    if not row:
        row = IntegrationSetting(provider=provider, enabled=False, config={})
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def _to_out(row: IntegrationSetting) -> IntegrationOut:
    return IntegrationOut(
        provider=row.provider,
        enabled=row.enabled,
        has_secret=bool(row.secret_ciphertext),
        secret_masked=(f"••••••••{row.secret_last4}" if row.secret_ciphertext and row.secret_last4 else None),
        config=row.config or {},
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def _start_geocodio_backfill_if_ready(row: IntegrationSetting) -> None:
    if row.provider != "geocodio" or not row.enabled or not row.secret_ciphertext:
        return
    from location_upgrade import refresh_existing_property_locations
    asyncio.create_task(refresh_existing_property_locations())


@router.get("", response_model=list[IntegrationOut])
async def list_integrations(user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    return [_to_out(await _get_or_create(db, p)) for p in KNOWN_PROVIDERS]


@router.get("/{provider}", response_model=IntegrationOut)
async def get_integration(provider: str, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    return _to_out(await _get_or_create(db, provider))


@router.put("/{provider}", response_model=IntegrationOut)
async def update_integration(provider: str, payload: IntegrationUpdate, request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db, provider)
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.config is not None:
        row.config = payload.config
    row.updated_by = user.email
    await db.commit()
    await db.refresh(row)
    await log_action(db, user=user, action="integration.update", entity_type="integration", entity_id=provider, detail={"enabled": row.enabled}, request=request)
    _start_geocodio_backfill_if_ready(row)
    return _to_out(row)


@router.put("/{provider}/secret", response_model=IntegrationOut)
async def set_secret(provider: str, payload: SecretUpdate, request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db, provider)
    secret = payload.secret.strip()
    row.secret_ciphertext = encrypt_secret(secret)
    row.secret_last4 = secret[-4:]
    row.updated_by = user.email
    await db.commit()
    await db.refresh(row)
    await log_action(db, user=user, action="integration.set_secret", entity_type="integration", entity_id=provider, request=request)
    _start_geocodio_backfill_if_ready(row)
    return _to_out(row)


@router.delete("/{provider}/secret", response_model=IntegrationOut)
async def clear_secret(provider: str, request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db, provider)
    row.secret_ciphertext = None
    row.secret_last4 = None
    row.updated_by = user.email
    await db.commit()
    await db.refresh(row)
    await log_action(db, user=user, action="integration.clear_secret", entity_type="integration", entity_id=provider, request=request)
    return _to_out(row)


@router.post("/{provider}/test", response_model=TestConnectionResult)
async def test_connection(provider: str, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db, provider)
    if not row.secret_ciphertext:
        return TestConnectionResult(ok=False, message="No API key configured. Save a key first.")
    if not row.enabled:
        return TestConnectionResult(ok=False, message="Integration is disabled. Enable it to test.")
    try:
        secret = decrypt_secret(row.secret_ciphertext)
    except Exception:
        return TestConnectionResult(ok=False, message="Stored key could not be decrypted.")

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            if provider == "rentcast":
                resp = await client.get(
                    "https://api.rentcast.io/v1/properties",
                    params={"city": "Austin", "state": "TX", "limit": 1},
                    headers={"X-Api-Key": secret, "Accept": "application/json"},
                )
                if resp.status_code == 200:
                    return TestConnectionResult(ok=True, message="RentCast connection successful.")
                if resp.status_code in (401, 403):
                    return TestConnectionResult(ok=False, message="RentCast rejected the API key (unauthorized).")
                return TestConnectionResult(ok=False, message=f"RentCast responded with status {resp.status_code}.")
            if provider == "maptiler":
                resp = await client.get("https://api.maptiler.com/tiles/satellite-v2/tiles.json", params={"key": secret})
                if resp.status_code == 200:
                    return TestConnectionResult(ok=True, message="MapTiler connection successful.")
                if resp.status_code in (401, 403):
                    return TestConnectionResult(ok=False, message="MapTiler rejected the API key (unauthorized).")
                return TestConnectionResult(ok=False, message=f"MapTiler responded with status {resp.status_code}.")
            if provider == "geocodio":
                resp = await client.get(
                    "https://api.geocod.io/v2/geocode",
                    params={"q": "1109 N Highland St, Arlington, VA 22201", "api_key": secret, "limit": 1},
                )
                if resp.status_code == 200:
                    return TestConnectionResult(ok=True, message="Geocodio connection successful. Property locations can be cached locally.")
                if resp.status_code in (401, 403):
                    return TestConnectionResult(ok=False, message="Geocodio rejected the API key (unauthorized).")
                return TestConnectionResult(ok=False, message=f"Geocodio responded with status {resp.status_code}.")
    except httpx.RequestError as e:
        return TestConnectionResult(ok=False, message=f"Could not reach provider: {e.__class__.__name__}")
    return TestConnectionResult(ok=False, message="Unsupported provider test.")
