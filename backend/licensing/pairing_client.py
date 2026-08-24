"""Office-side Mobile pairing proxy (Phase C3).

The Office backend calls the Control Plane (installation-authenticated) to issue/list/revoke Mobile
pairings. In-container it reaches the co-hosted Control Plane over an internal URL; in production the
installation reaches the AWS-hosted Control Plane over HTTPS. The installation registers itself on the
Control Plane on first use (dev bootstrap credential) WITHOUT disturbing the local dev licensing
identity (Control-Plane ids are stored under separate keys).
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


async def _get_installation_row(db: AsyncSession):
    return (await db.execute(select(AppConfig).where(AppConfig.key == "installation"))).scalar_one_or_none()


async def ensure_registered(db: AsyncSession) -> tuple[str, object]:
    """Ensure this installation is registered on the Control Plane; return (cp_installation_id, priv_key)."""
    priv, pub_pem = identity.get_or_create_identity()
    row = await _get_installation_row(db)
    value = dict(row.value) if (row and isinstance(row.value, dict)) else {}
    if value.get("cp_installation_id"):
        return value["cp_installation_id"], priv
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.post(f"{INTERNAL_CP_BASE}/activate", json={
            "company_name": lic_config.ACTIVATION_COMPANY_NAME,
            "requested_seats": lic_config.ACTIVATION_REQUESTED_SEATS,
            "installation_public_key": pub_pem,
            "software_version": lic_config.SOFTWARE_VERSION,
            "bootstrap_credential": lic_config.ACTIVATION_BOOTSTRAP_CREDENTIAL,
        })
    resp.raise_for_status()
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
    sig = reqsig.sign_request(priv, installation_id=installation_id, timestamp=ts, nonce=nonce, body=body)
    headers = {reqsig.H_INSTALLATION: installation_id, reqsig.H_TIMESTAMP: ts,
               reqsig.H_NONCE: nonce, reqsig.H_SIGNATURE: sig}
    async with httpx.AsyncClient(timeout=15) as c:
        return await c.post(f"{INTERNAL_CP_BASE}{path}", content=body, headers=headers)


async def create_pairing(db: AsyncSession, expected_user_id: str | None = None, expected_user_label: str | None = None) -> dict:
    iid, priv = await ensure_registered(db)
    body = b""
    if expected_user_id or expected_user_label:
        import json as _json
        body = _json.dumps({"expected_user_id": expected_user_id, "expected_user_label": expected_user_label}).encode()
    r = await _post_signed("/pairing/create", iid, priv, body=body)
    r.raise_for_status()
    return r.json()


async def list_devices(db: AsyncSession) -> dict:
    iid, priv = await ensure_registered(db)
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    sig = reqsig.sign_request(priv, installation_id=iid, timestamp=ts, nonce=nonce, body=b"")
    headers = {reqsig.H_INSTALLATION: iid, reqsig.H_TIMESTAMP: ts, reqsig.H_NONCE: nonce, reqsig.H_SIGNATURE: sig}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{INTERNAL_CP_BASE}/pairing/devices", headers=headers)
    r.raise_for_status()
    return r.json()


async def revoke_device(db: AsyncSession, device_id: str) -> dict:
    await ensure_registered(db)
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{INTERNAL_CP_BASE}/pairing/devices/{device_id}/revoke",
                         headers={"X-RoofSpan-Admin": cp_config.DEV_ADMIN_SECRET})
    r.raise_for_status()
    return r.json()
