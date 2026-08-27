"""Short-lived encrypted tile tickets for the Relay map-tile passthrough.

Keeps long-lived device credentials and user tokens OUT of tile URLs and access logs. The Mobile app
exchanges its credentials ONCE (via a POST body) for an opaque, encrypted, short-TTL ticket that then
authorizes tile GETs through a request header. Because the ticket travels in a header (not the URL),
tile URLs stay stable — which is what lets MapLibre's ambient cache serve recently viewed tiles offline.

The ticket payload (installation id, device id, local user token, expiry) is encrypted with Fernet so
it is unreadable in transit/logs. Revocation still takes effect promptly: the tile endpoint re-checks
that the installation and device are active on every request.
"""
import base64
import hashlib
import json
import time

from cryptography.fernet import Fernet, InvalidToken

from relay import config as RC

TTL_SECONDS = 30 * 60  # 30 minutes

_fernet: Fernet | None = None


def _ticket_key() -> bytes:
    """Return a stable Fernet key for the configured Relay ticket secret.

    Existing Fernet-formatted secrets are preserved byte-for-byte. A normal shared secret is
    deterministically derived into the 32-byte urlsafe-base64 form Fernet requires, so production
    configuration cannot fail lazily with HTTP 500 during ticket minting and every relay node still
    derives the same encryption key from the same shared secret.
    """
    if not RC.TICKET_SECRET:
        # Dev fallback: process-local tickets; production requires a shared secret at startup.
        return Fernet.generate_key()

    raw = RC.TICKET_SECRET.encode()
    try:
        # Validate backward-compatible Fernet keys without changing them.
        Fernet(raw)
        return raw
    except (ValueError, TypeError):
        return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())


def _fernet_instance() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_ticket_key())
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
