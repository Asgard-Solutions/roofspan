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


class EntitlementError(Exception):
    """Raised when an entitlement cannot be verified (bad signature, expired, unknown key)."""


def sign_entitlement(*, private_key, kid: str, claims: dict) -> str:
    """Sign an entitlement (Control-Plane side; dev signer in Phase C0).

    `claims` must include installation_id, company_id, subscription_state, seats_licensed,
    product, issued_at, refresh_at, grace_until (datetimes). `exp` is set to `grace_until` so a
    stale cached entitlement fails verification once the offline grace window has fully elapsed.
    """
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
    return jwt.encode(payload, private_key, algorithm=ALG, headers={"kid": kid})


def verify_entitlement(token: str, trusted_keys: dict) -> Entitlement:
    """Cryptographically verify an entitlement and return the parsed model.

    Raises EntitlementError on unknown key id, bad signature, expiry, or malformed claims.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise EntitlementError(f"Malformed entitlement header: {e}") from e
    kid = header.get("kid")
    key = trusted_keys.get(kid)
    if key is None:
        raise EntitlementError(f"Unknown signing key id: {kid!r}")
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[ALG],
            issuer=ISSUER,
            options={"require": ["exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise EntitlementError("Entitlement expired (offline grace exhausted)") from e
    except jwt.PyJWTError as e:
        raise EntitlementError(f"Invalid entitlement signature/claims: {e}") from e

    state = payload.get("subscription_state")
    if state not in VALID_STATES:
        raise EntitlementError(f"Invalid subscription_state: {state!r}")
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
    )
