"""Signed entitlement: format, signing (dev), and cryptographic verification.

Transport is a compact EdDSA-signed JWS (JWT) so we reuse PyJWT + `cryptography` (established
libraries; no custom cryptographic primitives). The `kid` header selects the trusted public key,
enabling signing-key rotation.

The local installation only ever VERIFIES entitlements (with a public key). Signing happens on the
Control Plane (dev: in-process signer under licensing.keys; production: Control Plane private key).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import jwt
from pydantic import BaseModel

ALG = "EdDSA"
ISSUER = "roofspan-control-plane"

# Subscription states asserted by the Control Plane inside the entitlement.
ACTIVE = "ACTIVE"
GRACE = "GRACE"
SUSPENDED = "SUSPENDED"
CANCELLED = "CANCELLED"
VALID_STATES = {ACTIVE, GRACE, SUSPENDED, CANCELLED}


class Entitlement(BaseModel):
    kid: str
    installation_id: str
    company_id: str
    license_id: Optional[str] = None
    subscription_state: str
    seats_licensed: int
    product: str
    min_supported_version: Optional[str] = None
    issued_at: datetime
    refresh_at: datetime
    grace_until: datetime
    nonce: str
    # Optional billing metadata (Phase C2 refinements) — informational for the installation UI.
    cancel_at_period_end: bool = False
    current_period_end: Optional[datetime] = None
    scheduled_seats: Optional[int] = None
    scheduled_seats_at: Optional[datetime] = None
    grace_started_at: Optional[datetime] = None


class EntitlementError(Exception):
    """Raised when an entitlement cannot be verified (bad signature, expired, unknown key).

    Carries a machine-readable `reason` so callers can distinguish a *recoverable* missing
    trusted key ("unknown_kid") from a genuine failure (tamper/expiry). Never include secret
    material or the raw token in the message.
    """

    def __init__(self, message: str, *, reason: str = "error"):
        super().__init__(message)
        self.reason = reason


# Reason codes (see EntitlementError.reason).
R_UNKNOWN_KID = "unknown_kid"      # signature key id not in the local trusted set -> may be recoverable
R_EXPIRED = "expired"              # offline grace exhausted
R_BAD_SIGNATURE = "bad_signature"  # signature/claims invalid -> possible tampering
R_MALFORMED = "malformed"          # header/token not parseable
R_INVALID_CLAIMS = "invalid_claims"


def _build_payload(claims: dict) -> dict:
    """Build the canonical entitlement JWT payload from claims (shared by local + signer paths)."""
    issued_at: datetime = claims["issued_at"]
    refresh_at: datetime = claims["refresh_at"]
    grace_until: datetime = claims["grace_until"]
    payload = {
        "iss": ISSUER,
        "installation_id": claims["installation_id"],
        "company_id": claims["company_id"],
        "license_id": claims.get("license_id"),
        "subscription_state": claims["subscription_state"],
        "seats_licensed": int(claims["seats_licensed"]),
        "product": claims["product"],
        "min_supported_version": claims.get("min_supported_version"),
        "iat": int(issued_at.timestamp()),
        "refresh_at": int(refresh_at.timestamp()),
        "grace_until": int(grace_until.timestamp()),
        "exp": int(grace_until.timestamp()),
        "nonce": claims.get("nonce") or uuid.uuid4().hex,
    }

    def _ts(dt):
        return int(dt.timestamp()) if dt else None

    if claims.get("cancel_at_period_end"):
        payload["cancel_at_period_end"] = True
    if claims.get("current_period_end"):
        payload["current_period_end"] = _ts(claims["current_period_end"])
    if claims.get("scheduled_seats") is not None:
        payload["scheduled_seats"] = int(claims["scheduled_seats"])
    if claims.get("scheduled_seats_at"):
        payload["scheduled_seats_at"] = _ts(claims["scheduled_seats_at"])
    if claims.get("grace_started_at"):
        payload["grace_started_at"] = _ts(claims["grace_started_at"])
    return payload


def sign_entitlement(*, private_key, kid: str, claims: dict) -> str:
    """Sign an entitlement with a LOCAL Ed25519 private key (dev/in-container path via PyJWT).

    `claims` must include installation_id, company_id, subscription_state, seats_licensed,
    product, issued_at, refresh_at, grace_until (datetimes). `exp` is set to `grace_until` so a
    stale cached entitlement fails verification once the offline grace window has fully elapsed.
    """
    payload = _build_payload(claims)
    return jwt.encode(payload, private_key, algorithm=ALG, headers={"kid": kid})


def sign_entitlement_via_signer(*, signer, kid: str, claims: dict) -> str:
    """Produce an EdDSA JWS whose signature comes from the SIGNER abstraction (local Ed25519 in dev,
    AWS KMS Ed25519 in production). Signs the CANONICAL JWS signing input (base64url(header).base64url
    (payload)) directly — no local prehash — so KMS ED25519_SHA_512 + MessageType=RAW yields a standard
    Ed25519 signature that RoofSpan Office verifies exactly like a locally-signed token.
    """
    import base64
    import json

    payload = _build_payload(claims)
    header = {"alg": ALG, "typ": "JWT", "kid": kid}

    def _b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    signing_input = (
        _b64(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + b"."
        + _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    )
    signature = signer.sign(signing_input)
    return (signing_input + b"." + _b64(signature)).decode("ascii")


def verify_entitlement(token: str, trusted_keys: dict) -> Entitlement:
    """Cryptographically verify an entitlement and return the parsed model.

    Raises EntitlementError on unknown key id, bad signature, expiry, or malformed claims.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise EntitlementError(f"Malformed entitlement header: {e}", reason=R_MALFORMED) from e
    kid = header.get("kid")
    key = trusted_keys.get(kid)
    if key is None:
        raise EntitlementError(f"Unknown signing key id: {kid!r}", reason=R_UNKNOWN_KID)
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[ALG],
            issuer=ISSUER,
            options={"require": ["exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise EntitlementError("Entitlement expired (offline grace exhausted)", reason=R_EXPIRED) from e
    except jwt.PyJWTError as e:
        raise EntitlementError(f"Invalid entitlement signature/claims: {e}", reason=R_BAD_SIGNATURE) from e

    state = payload.get("subscription_state")
    if state not in VALID_STATES:
        raise EntitlementError(f"Invalid subscription_state: {state!r}", reason=R_INVALID_CLAIMS)

    def _dt(key):
        v = payload.get(key)
        return datetime.fromtimestamp(v, tz=timezone.utc) if v else None

    return Entitlement(
        kid=kid,
        installation_id=payload["installation_id"],
        company_id=payload["company_id"],
        license_id=payload.get("license_id"),
        subscription_state=state,
        seats_licensed=int(payload["seats_licensed"]),
        product=payload["product"],
        min_supported_version=payload.get("min_supported_version"),
        issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
        refresh_at=datetime.fromtimestamp(payload["refresh_at"], tz=timezone.utc),
        grace_until=datetime.fromtimestamp(payload["grace_until"], tz=timezone.utc),
        nonce=payload.get("nonce", ""),
        cancel_at_period_end=bool(payload.get("cancel_at_period_end", False)),
        current_period_end=_dt("current_period_end"),
        scheduled_seats=payload.get("scheduled_seats"),
        scheduled_seats_at=_dt("scheduled_seats_at"),
        grace_started_at=_dt("grace_started_at"),
    )
