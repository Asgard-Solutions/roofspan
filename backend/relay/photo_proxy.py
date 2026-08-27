"""Authenticated HTTPS passthrough for Field photo content stored on a customer's Office PC."""
import asyncio
import uuid as uuidlib

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel

from control_plane.db import SessionLocal
from relay import protocol as P
from relay import tickets as RT
from relay.hub import RelayUnavailable, hub
from relay.server import (
    REQUEST_TIMEOUT,
    _authenticate_relay_device,
    _require_control_plane_ready_http,
    _revalidate_device,
)

router = APIRouter(prefix="/api/relay", tags=["relay"])


class PhotoTicketRequest(BaseModel):
    installation_id: str
    device_id: str
    device_credential: str
    token: str


@router.post("/photo-ticket")
async def relay_photo_ticket(payload: PhotoTicketRequest):
    """Exchange paired-device credentials + local user JWT for a short-lived photo ticket."""
    if not await _require_control_plane_ready_http():
        raise HTTPException(status_code=503, detail="control_plane_unavailable")
    if not payload.token.strip():
        raise HTTPException(status_code=422, detail="user_token_required")

    async with SessionLocal() as db:
        _installation, err = await _authenticate_relay_device(
            db, payload.installation_id, payload.device_id, payload.device_credential
        )
    if err:
        raise HTTPException(status_code=403, detail=err)

    ticket, ttl = RT.mint_ticket(payload.installation_id, payload.device_id, payload.token)
    return {"ticket": ticket, "expires_in": ttl}


@router.get("/photos/{photo_id}")
async def relay_photo(
    photo_id: str,
    x_roofspan_photo_ticket: str | None = Header(default=None),
):
    """Fetch authorized photo bytes from Office through the existing outbound installation tunnel."""
    if not await _require_control_plane_ready_http():
        raise HTTPException(status_code=503, detail="control_plane_unavailable")

    claims = RT.read_ticket(x_roofspan_photo_ticket or "")
    if not claims:
        raise HTTPException(status_code=401, detail="invalid_or_expired_ticket")
    iid, did, token = claims["iid"], claims["did"], claims["tok"]
    if not token or token == "-":
        raise HTTPException(status_code=401, detail="user_token_required")

    # Reject malformed IDs here instead of ever allowing arbitrary Office paths to be constructed.
    try:
        safe_photo_id = str(uuidlib.UUID(photo_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="photo_not_found")

    async with SessionLocal() as db:
        _installation, err = await _revalidate_device(db, iid, did)
    if err:
        raise HTTPException(status_code=403, detail=err)

    request_frame = {
        "type": P.T_REQUEST,
        "request_id": uuidlib.uuid4().hex,
        "method": "GET",
        "path": f"/api/mobile/photos/{safe_photo_id}/content",
        "query": "",
        "headers": {"Authorization": f"Bearer {token}"},
        "body": "",
    }
    try:
        response = await hub.route(iid, request_frame, REQUEST_TIMEOUT)
    except RelayUnavailable:
        raise HTTPException(status_code=503, detail="office_offline")
    except (asyncio.TimeoutError, TimeoutError):
        raise HTTPException(status_code=504, detail="photo_timeout")

    status = response.get("status") or 502
    if status != 200:
        # Preserve Office authorization/not-found semantics without leaking its response body.
        raise HTTPException(status_code=status, detail="photo_unavailable")

    content = P.b64d(response.get("body", ""))
    content_type = (response.get("headers", {}) or {}).get("content-type", "application/octet-stream")
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )
