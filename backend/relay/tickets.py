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
import time

from cryptography.fernet import Fernet, InvalidToken

from relay import config as RC

TTL_SECONDS = 30 * 60  # 30 minutes

_fernet: Fernet | None = None


def _fernet_instance() -> Fernet:
    global _fernet
    if _fernet is None:
        # Shared key from config (RELAY_TICKET_SECRET) so every relay node reads the same tickets.
        # Dev fallback: a per-process key (tickets are short-lived, so a restart just re-mints).
        key = RC.TICKET_SECRET.encode() if RC.TICKET_SECRET else Fernet.generate_key()
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
    # Org-level imagery: the embedded user token is no longer required (the Office connector authorizes
    # tile fetches with an org-scoped token). Only the installation + device identity must be present.
    if not (claims.get("iid") and claims.get("did")):
        return None
    return claims
