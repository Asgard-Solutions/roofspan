"""Relay wire protocol (versioned). JSON text frames over WebSocket.

Version 1 message types and the connect/auth/route/heartbeat/disconnect flow:

  Installation (outbound tunnel) -> Relay:  hello, auth, response, pong, bye
  Relay -> Installation:                    challenge, ready, request, ping, error
  Mobile -> Relay:                          hello, request, pong, bye
  Relay -> Mobile:                          ready, response, ping, error

Protocol compatibility is negotiated by PROTOCOL_VERSION (NOT the RoofSpan app version) so an app
upgrade does not force a relay-protocol change and vice versa.
"""
import base64
import json

PROTOCOL_VERSION = "1"

T_HELLO = "hello"
T_CHALLENGE = "challenge"
T_AUTH = "auth"
T_READY = "ready"
T_REQUEST = "request"
T_RESPONSE = "response"
T_PING = "ping"
T_PONG = "pong"
T_ERROR = "error"
T_BYE = "bye"
T_MEASUREMENT_CHANGED = "measurement_changed"
T_BROADCAST_ACK = "broadcast_ack"


def broadcast_ack(*, event_id=None, delivered=0) -> dict:
    """Relay -> Installation acknowledgement that a `measurement_changed` invalidation was ACCEPTED and
    fanned out. The connector waits for this BEFORE acking the durable Office outbox event (so an event
    is retried until the Relay has taken responsibility for it)."""
    return {"type": T_BROADCAST_ACK, "event_id": event_id, "delivered": int(delivered or 0)}


def measurement_changed(*, lead_id=None, measurement_set_id=None, revision_id=None, updated_at=None) -> dict:
    """Lightweight Office->Field invalidation. Carries NO business document — it only tells Field WHICH
    lead/revision changed (+ a watermark) so it retrieves the canonical copy from Office."""
    return {
        "type": T_MEASUREMENT_CHANGED,
        "lead_id": str(lead_id) if lead_id is not None else None,
        "measurement_set_id": str(measurement_set_id) if measurement_set_id is not None else None,
        "revision_id": str(revision_id) if revision_id is not None else None,
        "updated_at": updated_at if isinstance(updated_at, str) or updated_at is None else updated_at.isoformat(),
    }


def b64e(b: bytes | None) -> str:
    return base64.b64encode(b or b"").decode()


def b64d(s: str | None) -> bytes:
    return base64.b64decode(s.encode()) if s else b""


def dumps(frame: dict) -> str:
    return json.dumps(frame)


def loads(s) -> dict:
    return json.loads(s)


def path_category(path: str) -> str:
    """Coarse, id-free route category for safe operational logging (never the full path/ids)."""
    parts = [p for p in (path or "/").split("?")[0].split("/") if p]
    return "/" + "/".join(parts[:3])
