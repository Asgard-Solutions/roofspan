"""Relay WebSocket endpoints (mounted at /api/relay).

/installation : the customer installation opens an OUTBOUND tunnel, authenticates with its C1
                Ed25519 installation identity (challenge-response — no new permanent password),
                and then serves routed Mobile requests.
/mobile       : a paired Mobile device connects and sends business requests; the relay routes them
                down the correct installation tunnel and correlates the response by request_id.

Authorization chain (defense in depth): installation exists + not revoked + entitled (ACTIVE/GRACE);
device paired + not revoked; local user JWT + RBAC are enforced by the LOCAL FastAPI when the tunnel
forwards the request. The relay is NOT the RBAC authority and never stores business payloads.
"""
import logging
import os
import uuid as uuidlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from control_plane import service as cp_service
from control_plane.db import SessionLocal
from control_plane.models import Installation, Subscription, MobileDevice
from licensing import reqsig
from relay import protocol as P
from relay.hub import hub, InstallationConn, RelayUnavailable

log = logging.getLogger("roofspan.relay")

router = APIRouter(prefix="/api/relay", tags=["relay"])

REQUEST_TIMEOUT = float(os.environ.get("RELAY_REQUEST_TIMEOUT", "30"))


async def _load_installation(db, installation_id: str):
    try:
        iid = uuidlib.UUID(installation_id)
    except (ValueError, TypeError):
        return None
    return (await db.execute(select(Installation).where(Installation.id == iid))).scalar_one_or_none()


async def _entitlement_state(db, company_id) -> str | None:
    sub = (await db.execute(select(Subscription).where(Subscription.company_id == company_id))).scalar_one_or_none()
    if sub is None:
        return None
    cp_service.apply_billing_transitions(sub)  # reflect due grace-expiry / scheduled changes
    await db.commit()
    return sub.state


async def _send(ws: WebSocket, frame: dict):
    await ws.send_text(P.dumps(frame))


@router.websocket("/installation")
async def installation_ws(ws: WebSocket):
    await ws.accept()
    installation_id = None
    conn = None
    try:
        hello = P.loads(await ws.receive_text())
        if hello.get("type") != P.T_HELLO or hello.get("protocol") != P.PROTOCOL_VERSION:
            await _send(ws, {"type": P.T_ERROR, "code": "protocol_mismatch",
                             "message": f"relay protocol {P.PROTOCOL_VERSION} required"})
            await ws.close()
            return
        installation_id = hello.get("installation_id")
        nonce = uuidlib.uuid4().hex
        await _send(ws, {"type": P.T_CHALLENGE, "nonce": nonce, "protocol": P.PROTOCOL_VERSION})

        auth = P.loads(await ws.receive_text())
        if auth.get("type") != P.T_AUTH:
            await ws.close()
            return
        ts = auth.get("timestamp", "")
        sig = auth.get("signature", "")
        async with SessionLocal() as db:
            inst = await _load_installation(db, installation_id)
            if inst is None:
                await _send(ws, {"type": P.T_ERROR, "code": "unknown_installation"})
                await ws.close()
                return
            if inst.status != "ACTIVE":
                await _send(ws, {"type": P.T_ERROR, "code": "installation_revoked"})
                await ws.close()
                return
            if not reqsig.verify_request(inst.public_key_pem, installation_id=installation_id,
                                         timestamp=ts, nonce=nonce, body=nonce.encode(), signature_b64=sig):
                await _send(ws, {"type": P.T_ERROR, "code": "bad_signature"})
                await ws.close()
                return
            state = await _entitlement_state(db, inst.company_id)
            if state not in ("ACTIVE", "GRACE"):
                await _send(ws, {"type": P.T_ERROR, "code": "not_entitled", "message": state})
                await ws.close()
                return

        conn = InstallationConn(installation_id, ws)
        hub.register(conn)
        await _send(ws, {"type": P.T_READY, "protocol": P.PROTOCOL_VERSION})

        while True:
            frame = P.loads(await ws.receive_text())
            t = frame.get("type")
            if t == P.T_RESPONSE:
                hub.resolve(installation_id, frame.get("request_id"), frame)
            elif t == P.T_PING:
                await _send(ws, {"type": P.T_PONG, "ts": frame.get("ts")})
            elif t == P.T_BYE:
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("relay installation ws error: %s", str(e)[:200])
    finally:
        if conn is not None:
            hub.unregister(installation_id, conn)


@router.websocket("/mobile")
async def mobile_ws(ws: WebSocket):
    await ws.accept()
    installation_id = device_id = None
    try:
        hello = P.loads(await ws.receive_text())
        if hello.get("type") != P.T_HELLO or hello.get("protocol") != P.PROTOCOL_VERSION:
            await _send(ws, {"type": P.T_ERROR, "code": "protocol_mismatch",
                             "message": f"relay protocol {P.PROTOCOL_VERSION} required"})
            await ws.close()
            return
        installation_id = hello.get("installation_id")
        device_id = hello.get("device_id")
        async with SessionLocal() as db:
            inst = await _load_installation(db, installation_id)
            if inst is None or inst.status != "ACTIVE":
                await _send(ws, {"type": P.T_ERROR, "code": "unknown_or_revoked_installation"})
                await ws.close()
                return
            dev = None
            if device_id:
                try:
                    dev = (await db.execute(select(MobileDevice).where(MobileDevice.id == uuidlib.UUID(device_id)))).scalar_one_or_none()
                except (ValueError, TypeError):
                    dev = None
            if dev is None or str(dev.installation_id) != installation_id or dev.status != "ACTIVE":
                await _send(ws, {"type": P.T_ERROR, "code": "device_not_paired"})
                await ws.close()
                return
            # Proof-of-possession of the durable per-device credential (device_id alone is insufficient).
            import hashlib as _hashlib
            import hmac as _hmac
            cred = hello.get("device_credential") or ""
            if not dev.credential_hash or not cred or not _hmac.compare_digest(
                    _hashlib.sha256(cred.encode()).hexdigest(), dev.credential_hash):
                await _send(ws, {"type": P.T_ERROR, "code": "device_auth_failed"})
                await ws.close()
                return
            state = await _entitlement_state(db, inst.company_id)
            if state not in ("ACTIVE", "GRACE"):
                # Mobile license-lock: routing is blocked; the app shows the subscription-inactive screen.
                await _send(ws, {"type": P.T_ERROR, "code": "subscription_inactive", "message": state})
                await ws.close()
                return

        await _send(ws, {"type": P.T_READY, "installation_id": installation_id, "protocol": P.PROTOCOL_VERSION})
        seen: set[str] = set()

        while True:
            frame = P.loads(await ws.receive_text())
            t = frame.get("type")
            if t == P.T_PING:
                await _send(ws, {"type": P.T_PONG, "ts": frame.get("ts")})
                continue
            if t == P.T_BYE:
                break
            if t != P.T_REQUEST:
                continue
            rid = frame.get("request_id") or uuidlib.uuid4().hex
            if rid in seen:
                await _send(ws, {"type": P.T_ERROR, "request_id": rid, "code": "duplicate_request"})
                continue
            seen.add(rid)
            req = {"type": P.T_REQUEST, "request_id": rid, "method": frame.get("method", "GET"),
                   "path": frame.get("path", "/"), "query": frame.get("query", ""),
                   "headers": frame.get("headers", {}) or {}, "body": frame.get("body", "")}
            status = "err"
            try:
                resp = await hub.route(installation_id, req, REQUEST_TIMEOUT)
                status = resp.get("status")
                await _send(ws, {"type": P.T_RESPONSE, "request_id": rid, "status": status,
                                 "headers": resp.get("headers", {}), "body": resp.get("body", "")})
            except RelayUnavailable:
                await _send(ws, {"type": P.T_ERROR, "request_id": rid, "code": "tunnel_unavailable"})
            except TimeoutError:
                await _send(ws, {"type": P.T_ERROR, "request_id": rid, "code": "request_timeout"})
            # Sanitized operational log — no bodies, no auth tokens, id-free route category.
            log.info("relay route inst=%s dev=%s rid=%s %s %s -> %s",
                     installation_id, device_id, rid, req["method"], P.path_category(req["path"]), status)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("relay mobile ws error: %s", str(e)[:200])
