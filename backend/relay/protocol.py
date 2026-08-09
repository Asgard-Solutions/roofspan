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
