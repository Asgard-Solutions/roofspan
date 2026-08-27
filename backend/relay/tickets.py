"""Short-lived encrypted tile tickets for the Relay map-tile passthrough.

Keeps long-lived device credentials and user tokens OUT of tile URLs and access logs. The Mobile app
exchanges its credentials ONCE (via a POST body) for an opaque, encrypted, short-TTL ticket that then
authorizes tile GETs through a request header. Because the ticket travels in a header (not the URL),
tile URLs stay stable — which is what lets MapLibre's ambient cache serve recently viewed tiles offline.

The ticket payload (installation id, device id, local user token, expiry) is encrypted with Fernet so
it is unreadable in transit/logs. Revocation still takes effect promptly: the tile endpoint re-checks
that the installation and device are active on every request.
"""
import json
import os
import time

from cryptography.fernet import Fernet, InvalidToken

TTL_SECONDS = 30 * 60  # 30 minutes

_fernet: Fernet | None = None


def _fernet_instance() -> Fernet:
    global _fernet
    if _fernet is None:
        raw = os.environ.get("RELAY_TICKET_SECRET")
        # A configured urlsafe-base64 32-byte Fernet key is required for multi-node relays so every
        # node can read tickets. Without it we generate a stable per-process key: tickets are short
        # lived, so a restart simply makes the Mobile app mint a fresh one.
        key = raw.encode() if raw else Fernet.generate_key()
        _fernet = Fernet(key)
    return _fernet


def mint_ticket(installation_id: str, device_id: str, token: str, ttl: int = TTL_SECONDS) -> tuple[str, int]:
    payload = {
        "iid": installation_id,
        "did": device_id,
        "tok": token,
        "exp": int(time.time()) + int(ttl),
    }
    ticket = _fernet_instance().encrypt(json.dumps(payload).encode()).decode()
    return ticket, int(ttl)


def read_ticket(ticket: str) -> dict | None:
    """Return the ticket claims or None if the ticket is invalid/expired/tampered."""
    if not ticket:
        return None
    try:
        raw = _fernet_instance().decrypt(ticket.encode(), ttl=TTL_SECONDS + 60)
    except (InvalidToken, ValueError, TypeError):
        return None
    try:
        claims = json.loads(raw)
    except ValueError:
        return None
    if int(claims.get("exp", 0)) < int(time.time()):
        return None
    if not (claims.get("iid") and claims.get("did") and claims.get("tok")):
        return None
    return claims
