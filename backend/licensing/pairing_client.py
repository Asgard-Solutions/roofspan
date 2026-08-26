"""Office-side Mobile pairing proxy (Phase C3).

The Office backend calls the Control Plane (installation-authenticated) to issue/list/revoke Mobile
pairings. In-container it reaches the co-hosted Control Plane over an internal URL; in production the
installation reaches the hosted Control Plane over HTTPS. Error details surfaced to Office are always
safe and intentionally omit SQL, credentials, connection strings, and tracebacks.
"""
from __future__ import annotations

import os
import time
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AppConfig
from licensing import identity, reqsig, config as lic_config
from control_plane import config as cp_config

INTERNAL_CP_BASE = os.environ.get("INTERNAL_CONTROL_PLANE_URL", "http://localhost:8001/api/control-plane")


class ControlPlaneError(RuntimeError):
    """Carries a SAFE, human-readable Control Plane failure reason."""


_SECRET_HINT = (
    "password",
    "secret",
    "postgresql://",
    "postgres://",
    "@",
    "jwt",
    "token=",
    "key=",
    "-----begin",
    "sqlalchemy",
    "asyncpg",
    "psycopg",
    "traceback",
)


def _safe_detail(resp) -> str:
    detail = None
    try:
        body = resp.json()
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, dict):
            # Readiness/activation responses use a safe structured contract. Prefer the human message;
            # do not stringify the full object or internal diagnostic fields into a toast.
            detail = detail.get("message") or detail.get("code")
        elif isinstance(detail, list):
            detail = "Request validation failed."
    except Exception:
        detail = None
    if not detail:
        detail = f"HTTP {resp.status_code}"
    detail = str(detail)
    low = detail.lower()
    if any(hint in low for hint in _SECRET_HINT):
        return f"Control Plane returned HTTP {resp.status_code} (details withheld for security)."
    return detail[:300]


def _raise_for_cp(resp, action: str) -> None:
    if resp.status_code >= 400:
        raise ControlPlaneError(f"{action} failed: {_safe_detail(resp)}")


async def _get_installation_row(db: AsyncSession):
    return (await db.execute(select(AppConfig).where(AppConfig.key == "installation"))).scalar_one_or_none()


async def ensure_registered(db: AsyncSession) -> tuple[str, object]:
    """Ensure this installation is registered on the Control Plane; return (cp_installation_id, priv_key)."""
    priv, pub_pem = identity.get_or_create_identity()
    row = await _get_installation_row(db)
    value = dict(row.value) if (row and isinstance(row.value, dict)) else {}
    if value.get("cp_installation_id"):
        return value["cp_installation_id"], priv
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{INTERNAL_CP_BASE}/activate",
            json={
                "company_name": lic_config.ACTIVATION_COMPANY_NAME,
                "requested_seats": lic_config.ACTIVATION_REQUESTED_SEATS,
                "installation_public_key": pub_pem,
                "software_version": lic_config.SOFTWARE_VERSION,
                "bootstrap_credential": lic_config.ACTIVATION_BOOTSTRAP_CREDENTIAL,
            },
        )
    _raise_for_cp(resp, "Device activation")
    data = resp.json()
    value["cp_installation_id"] = data["installation_id"]
    value["cp_company_id"] = data["company_id"]
    if row is None:
        db.add(AppConfig(key="installation", value=value))
    else:
        row.value = value
    await db.commit()
    return data["installation_id"], priv


async def _post_signed(path: str, installation_id: str, priv, body: bytes = b""):
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    sig = reqsig.sign_request(
        priv, installation_id=installation_id, timestamp=ts, nonce=nonce, body=body
    )
    headers = {
        reqsig.H_INSTALLATION: installation_id,
        reqsig.H_TIMESTAMP: ts,
        reqsig.H_NONCE: nonce,
        reqsig.H_SIGNATURE: sig,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        return await client.post(f"{INTERNAL_CP_BASE}{path}", content=body, headers=headers)


async def create_pairing(
    db: AsyncSession,
    expected_user_id: str | None = None,
    expected_user_label: str | None = None,
) -> dict:
    iid, priv = await ensure_registered(db)
    body = b""
    if expected_user_id or expected_user_label:
        import json as _json

        body = _json.dumps(
            {"expected_user_id": expected_user_id, "expected_user_label": expected_user_label}
        ).encode()
    response = await _post_signed("/pairing/create", iid, priv, body=body)
    _raise_for_cp(response, "Create pairing")
    return response.json()


async def list_devices(db: AsyncSession) -> dict:
    iid, priv = await ensure_registered(db)
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    sig = reqsig.sign_request(priv, installation_id=iid, timestamp=ts, nonce=nonce, body=b"")
    headers = {
        reqsig.H_INSTALLATION: iid,
        reqsig.H_TIMESTAMP: ts,
        reqsig.H_NONCE: nonce,
        reqsig.H_SIGNATURE: sig,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{INTERNAL_CP_BASE}/pairing/devices", headers=headers)
    _raise_for_cp(response, "List devices")
    return response.json()


async def revoke_device(db: AsyncSession, device_id: str) -> dict:
    await ensure_registered(db)
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{INTERNAL_CP_BASE}/pairing/devices/{device_id}/revoke",
            headers={"X-RoofSpan-Admin": cp_config.DEV_ADMIN_SECRET},
        )
    _raise_for_cp(response, "Revoke device")
    return response.json()
