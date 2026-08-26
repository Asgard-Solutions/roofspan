"""Loopback-only bootstrap endpoint for the Windows Relay Connector service.

The connector is a separate Windows service, so it cannot safely guess the hosted Control Plane
installation id from the Ed25519 public key. It asks the local Office backend, which owns the business
DB/AppConfig row and can verify or migrate the registration on the hosted Control Plane. Only the
non-secret installation id and public Relay WebSocket URL are returned; the private key never leaves
``INSTALLATION_KEYS_DIR``.
"""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from licensing import pairing_client

router = APIRouter(prefix="/api/relay/connector", tags=["relay-connector"])


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
    except pairing_client.ControlPlaneError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "installation_id": installation_id,
        "relay_ws_url": relay_ws_url,
        "control_plane_origin": urlparse(control_plane_base).netloc,
        "protocol_version": "1",
    }
