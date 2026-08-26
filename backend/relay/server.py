"""Relay WebSocket endpoints (mounted at /api/relay).

/installation : the customer installation opens an OUTBOUND tunnel, authenticates with its hosted
                Control Plane Ed25519 installation identity, and serves routed Mobile requests.
/tunnel       : compatibility alias for pre-release Office builds.
/mobile       : a paired Mobile device connects and sends business requests; the relay routes them
                down the correct installation tunnel and correlates the response by request_id.

Authorization chain: installation exists + not revoked + entitled (ACTIVE/GRACE); device paired + not
revoked; local user JWT + RBAC are enforced by the LOCAL FastAPI when the tunnel forwards the request.
The relay is not the RBAC authority and never persists roofing-business payloads.
"""
import logging
import uuid as uuidlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from control_plane import readiness as cp_readiness
from control_plane import service as cp_service
from control_plane.db import SessionLocal
from control_plane.models import Installation, MobileDevice, Subscription
from licensing import reqsig
from relay import config as RC
from relay import protocol as P
from relay.hub import InstallationConn, RelayPayloadTooLarge, RelayUnavailable, hub

log = logging.getLogger("roofspan.relay")

router = APIRouter(prefix="/api/relay", tags=["relay"])

REQUEST_TIMEOUT = RC.REQUEST_TIMEOUT
MAX_JSON_BYTES = RC.MAX_JSON_BYTES
MAX_UPLOAD_BYTES = RC.MAX_UPLOAD_BYTES


def _b64_len(value: str) -> int:
    length = len(value or "")
    return (length * 3) // 4


def _too_large(frame: dict):
    if _b64_len(frame.get("body", "")) > MAX_JSON_BYTES:
        return "payload_too_large"
    multipart = frame.get("multipart")
    if multipart and isinstance(multipart, dict):
        file_part = multipart.get("file") or {}
        if _b64_len(file_part.get("b64", "")) > MAX_UPLOAD_BYTES:
            return "payload_too_large"
    return None


async def _load_installation(db, installation_id: str):
    try:
        iid = uuidlib.UUID(installation_id)
    except (ValueError, TypeError):
        return None
    return (
        await db.execute(select(Installation).where(Installation.id == iid))
    ).scalar_one_or_none()


async def _entitlement_state(db, company_id) -> str | None:
    subscription = (
        await db.execute(select(Subscription).where(Subscription.company_id == company_id))
    ).scalar_one_or_none()
    if subscription is None:
        return None
    cp_service.apply_billing_transitions(subscription)
    await db.commit()
    return subscription.state


async def _send(ws: WebSocket, frame: dict):
    await ws.send_text(P.dumps(frame))


async def _require_control_plane_ready(ws: WebSocket) -> bool:
    """Reject Relay authentication cleanly until the central CP schema/key bootstrap is ready."""
    status = cp_readiness.snapshot()
    if status["ready"]:
        return True
    await _send(
        ws,
        {
            "type": P.T_ERROR,
            "code": "control_plane_unavailable",
            "message": "RoofSpan Relay is initializing. Please retry shortly.",
        },
    )
    await ws.close(code=1013)
    return False


@router.websocket("/tunnel")
@router.websocket("/installation")
async def installation_ws(ws: WebSocket):
    await ws.accept()
    if not await _require_control_plane_ready(ws):
        return

    installation_id = None
    conn = None
    try:
        hello = P.loads(await ws.receive_text())
        if hello.get("type") != P.T_HELLO or hello.get("protocol") != P.PROTOCOL_VERSION:
            await _send(
                ws,
                {
                    "type": P.T_ERROR,
                    "code": "protocol_mismatch",
                    "message": f"relay protocol {P.PROTOCOL_VERSION} required",
                },
            )
            await ws.close()
            return
        installation_id = hello.get("installation_id")
        nonce = uuidlib.uuid4().hex
        await _send(ws, {"type": P.T_CHALLENGE, "nonce": nonce, "protocol": P.PROTOCOL_VERSION})

        auth = P.loads(await ws.receive_text())
        if auth.get("type") != P.T_AUTH:
            await ws.close()
            return
        timestamp = auth.get("timestamp", "")
        signature = auth.get("signature", "")
        async with SessionLocal() as db:
            installation = await _load_installation(db, installation_id)
            if installation is None:
                await _send(ws, {"type": P.T_ERROR, "code": "unknown_installation"})
                await ws.close()
                return
            if installation.status != "ACTIVE":
                await _send(ws, {"type": P.T_ERROR, "code": "installation_revoked"})
                await ws.close()
                return
            if not reqsig.verify_request(
                installation.public_key_pem,
                installation_id=installation_id,
                timestamp=timestamp,
                nonce=nonce,
                body=nonce.encode(),
                signature_b64=signature,
            ):
                await _send(ws, {"type": P.T_ERROR, "code": "bad_signature"})
                await ws.close()
                return
            state = await _entitlement_state(db, installation.company_id)
            if state not in ("ACTIVE", "GRACE"):
                await _send(ws, {"type": P.T_ERROR, "code": "not_entitled", "message": state})
                await ws.close()
                return

        conn = InstallationConn(installation_id, ws)
        await hub.register(conn)
        await _send(ws, {"type": P.T_READY, "protocol": P.PROTOCOL_VERSION})

        while True:
            frame = P.loads(await ws.receive_text())
            frame_type = frame.get("type")
            if frame_type == P.T_RESPONSE:
                hub.resolve(installation_id, frame.get("request_id"), frame)
            elif frame_type == P.T_PING:
                await _send(ws, {"type": P.T_PONG, "ts": frame.get("ts")})
            elif frame_type == P.T_BYE:
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("relay installation ws error: %s", str(exc)[:200])
    finally:
        if conn is not None:
            await hub.unregister(installation_id, conn)


@router.websocket("/mobile")
async def mobile_ws(ws: WebSocket):
    await ws.accept()
    if not await _require_control_plane_ready(ws):
        return

    installation_id = device_id = None
    try:
        hello = P.loads(await ws.receive_text())
        if hello.get("type") != P.T_HELLO or hello.get("protocol") != P.PROTOCOL_VERSION:
            await _send(
                ws,
                {
                    "type": P.T_ERROR,
                    "code": "protocol_mismatch",
                    "message": f"relay protocol {P.PROTOCOL_VERSION} required",
                },
            )
            await ws.close()
            return
        installation_id = hello.get("installation_id")
        device_id = hello.get("device_id")
        async with SessionLocal() as db:
            installation = await _load_installation(db, installation_id)
            if installation is None or installation.status != "ACTIVE":
                await _send(ws, {"type": P.T_ERROR, "code": "unknown_or_revoked_installation"})
                await ws.close()
                return
            device = None
            if device_id:
                try:
                    device = (
                        await db.execute(
                            select(MobileDevice).where(MobileDevice.id == uuidlib.UUID(device_id))
                        )
                    ).scalar_one_or_none()
                except (ValueError, TypeError):
                    device = None
            if (
                device is None
                or str(device.installation_id) != installation_id
                or device.status != "ACTIVE"
            ):
                await _send(ws, {"type": P.T_ERROR, "code": "device_not_paired"})
                await ws.close()
                return

            import hashlib as _hashlib
            import hmac as _hmac

            credential = hello.get("device_credential") or ""
            if (
                not device.credential_hash
                or not credential
                or not _hmac.compare_digest(
                    _hashlib.sha256(credential.encode()).hexdigest(),
                    device.credential_hash,
                )
            ):
                await _send(ws, {"type": P.T_ERROR, "code": "device_auth_failed"})
                await ws.close()
                return
            state = await _entitlement_state(db, installation.company_id)
            if state not in ("ACTIVE", "GRACE"):
                await _send(
                    ws,
                    {"type": P.T_ERROR, "code": "subscription_inactive", "message": state},
                )
                await ws.close()
                return

        await _send(
            ws,
            {
                "type": P.T_READY,
                "installation_id": installation_id,
                "protocol": P.PROTOCOL_VERSION,
            },
        )
        seen: set[str] = set()

        while True:
            frame = P.loads(await ws.receive_text())
            frame_type = frame.get("type")
            if frame_type == P.T_PING:
                await _send(ws, {"type": P.T_PONG, "ts": frame.get("ts")})
                continue
            if frame_type == P.T_BYE:
                break
            if frame_type != P.T_REQUEST:
                continue
            request_id = frame.get("request_id") or uuidlib.uuid4().hex
            if request_id in seen:
                await _send(
                    ws,
                    {"type": P.T_ERROR, "request_id": request_id, "code": "duplicate_request"},
                )
                continue
            seen.add(request_id)
            oversize = _too_large(frame)
            if oversize:
                await _send(
                    ws,
                    {"type": P.T_ERROR, "request_id": request_id, "code": oversize},
                )
                continue
            request_frame = {
                "type": P.T_REQUEST,
                "request_id": request_id,
                "method": frame.get("method", "GET"),
                "path": frame.get("path", "/"),
                "query": frame.get("query", ""),
                "headers": frame.get("headers", {}) or {},
                "body": frame.get("body", ""),
            }
            if frame.get("multipart"):
                request_frame["multipart"] = frame.get("multipart")
            status = "err"
            try:
                response = await hub.route(installation_id, request_frame, REQUEST_TIMEOUT)
                status = response.get("status")
                await _send(
                    ws,
                    {
                        "type": P.T_RESPONSE,
                        "request_id": request_id,
                        "status": status,
                        "headers": response.get("headers", {}),
                        "body": response.get("body", ""),
                    },
                )
            except RelayUnavailable:
                await _send(
                    ws,
                    {"type": P.T_ERROR, "request_id": request_id, "code": "tunnel_unavailable"},
                )
            except RelayPayloadTooLarge:
                await _send(
                    ws,
                    {"type": P.T_ERROR, "request_id": request_id, "code": "payload_too_large"},
                )
            except TimeoutError:
                await _send(
                    ws,
                    {"type": P.T_ERROR, "request_id": request_id, "code": "request_timeout"},
                )
            log.info(
                "relay route inst=%s dev=%s rid=%s %s %s -> %s",
                installation_id,
                device_id,
                request_id,
                request_frame["method"],
                P.path_category(request_frame["path"]),
                status,
            )
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("relay mobile ws error: %s", str(exc)[:200])
