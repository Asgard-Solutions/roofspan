"""Loopback-only bootstrap endpoint for the Windows Relay Connector service.

The connector is a separate Windows service, so it cannot safely guess the hosted Control Plane
installation id from the Ed25519 public key. It asks the local Office backend, which owns the business
DB/AppConfig row and can verify or migrate the registration on the hosted Control Plane. Only the
non-secret installation id and public Relay WebSocket URL are returned; the private key never leaves
``INSTALLATION_KEYS_DIR``.
"""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import os
import secrets
import time
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from licensing import pairing_client
from models import AppConfig
from services import office_outbox

router = APIRouter(prefix="/api/relay/connector", tags=["relay-connector"])

_CONNECTOR_TOKEN_KEY = "relay_connector_token"


async def _get_or_create_connector_token(db: AsyncSession) -> str:
    """Durable loopback shared secret the connector presents on the outbox endpoints. Generated once
    and stored in AppConfig (survives restarts, unlike a per-process value)."""
    row = await db.get(AppConfig, _CONNECTOR_TOKEN_KEY)
    if row and isinstance(row.value, dict) and row.value.get("token"):
        return row.value["token"]
    token = secrets.token_urlsafe(32)
    if row:
        row.value = {"token": token}
    else:
        db.add(AppConfig(key=_CONNECTOR_TOKEN_KEY, value={"token": token}))
    await db.commit()
    return token


async def _require_loopback_connector(request: Request, db: AsyncSession, presented: str | None) -> None:
    """Outbox endpoints are loopback-ONLY (the connector runs on the same box) AND token-authenticated."""
    if request.client is None or not _is_loopback(request.client.host):
        raise HTTPException(status_code=404, detail="Not found")
    expected = await _get_or_create_connector_token(db)
    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=403, detail="bad_connector_token")


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _installation_relay_ws_url() -> str:
    """Normalize the configured Relay endpoint to the installation-tunnel WebSocket route."""
    raw = (
        os.environ.get("ROOFSPAN_RELAY_WS_URL")
        or os.environ.get("RELAY_WSS_URL")
        or "wss://relay.roofspan.io"
    ).strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
        raise RuntimeError("RoofSpan Relay WebSocket URL is invalid")
    if parsed.scheme == "ws" and not _is_loopback(parsed.hostname):
        raise RuntimeError("RoofSpan Relay requires WSS")

    path = parsed.path.rstrip("/")
    if path in {"", "/"}:
        path = "/api/relay/installation"
    elif path.endswith("/api/relay/tunnel"):
        # Compatibility with the pre-release template; use the canonical route going forward.
        path = path[: -len("/api/relay/tunnel")] + "/api/relay/installation"
    elif not path.endswith("/api/relay/installation"):
        raise RuntimeError(
            "RoofSpan Relay URL must be an origin or end with /api/relay/installation"
        )
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


@router.get("/identity")
async def connector_identity(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return the hosted installation id used by both Relay tunnel and Mobile pairing."""
    if request.client is None or not _is_loopback(request.client.host):
        # The Office backend is bound to loopback, but retain an explicit defense if hosting changes.
        raise HTTPException(status_code=404, detail="Not found")
    try:
        installation_id, _private_key, control_plane_base = await pairing_client.ensure_registered(db)
        relay_ws_url = _installation_relay_ws_url()
        connector_token = await _get_or_create_connector_token(db)
    except pairing_client.ControlPlaneError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "installation_id": installation_id,
        "relay_ws_url": relay_ws_url,
        "control_plane_origin": urlparse(control_plane_base).netloc,
        "protocol_version": "1",
        "connector_token": connector_token,
    }


# ============================================================================
# Durable outbox drain (Office -> Field measurement invalidations)
# ----------------------------------------------------------------------------
# The connector LONG-POLLS /outbox/lease, forwards each leased `measurement_changed` event up the
# Relay tunnel, waits for the Relay's acceptance, then POSTs /outbox/ack. Un-acked events are
# redelivered after the lease expires (at-least-once). Both endpoints are loopback-only + token-auth.
# ============================================================================
class OutboxLeaseIn(BaseModel):
    max_events: int = 64
    lease_seconds: int = 30
    wait_ms: int = 20000


class OutboxAckIn(BaseModel):
    event_ids: list[str] = []


@router.post("/outbox/lease")
async def outbox_lease(
    payload: OutboxLeaseIn,
    request: Request,
    x_connector_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    await _require_loopback_connector(request, db, x_connector_token)
    max_events = max(1, min(payload.max_events, 256))
    lease_seconds = max(5, min(payload.lease_seconds, 300))
    deadline = time.monotonic() + (max(0, min(payload.wait_ms, 25000)) / 1000.0)
    while True:
        events = await office_outbox.lease(db, limit=max_events, lease_seconds=lease_seconds)
        if events or time.monotonic() >= deadline:
            return {"events": events, "lease_seconds": lease_seconds}
        await asyncio.sleep(1.0)


@router.post("/outbox/ack")
async def outbox_ack(
    payload: OutboxAckIn,
    request: Request,
    x_connector_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    await _require_loopback_connector(request, db, x_connector_token)
    acked = await office_outbox.ack(db, payload.event_ids)
    return {"acked": acked}
