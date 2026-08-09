"""Control Plane entitlement signing-key management (Ed25519, kid, lifecycle).

Lifecycle: ACTIVE (one at a time for new issuance) -> RETIRED (still trusted for verification of
previously-issued entitlements) -> REVOKED (no longer trusted). Rotation creates a new ACTIVE key
and retires the previous ACTIVE.

DEV/in-container: keys are generated and their private PEM stored in the (isolated) Control Plane DB
and mirrored to a git-ignored dir. PRODUCTION: the private key must live in AWS KMS/Secrets Manager
(HUMAN REQUIRED); it is never committed or placed in a customer installation.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane import config
from control_plane.models import SigningKey


def _new_kid() -> str:
    return f"cp-{datetime.now(timezone.utc).strftime('%Y%m')}-{uuid.uuid4().hex[:8]}"


def _generate() -> tuple[str, str]:
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return priv_pem, pub_pem


def _mirror_to_disk(kid: str, priv_pem: str, pub_pem: str) -> None:
    os.makedirs(config.DEV_SIGNING_KEYS_DIR, exist_ok=True)
    with open(os.path.join(config.DEV_SIGNING_KEYS_DIR, f"{kid}.private.pem"), "w") as f:
        f.write(priv_pem)
    os.chmod(os.path.join(config.DEV_SIGNING_KEYS_DIR, f"{kid}.private.pem"), 0o600)
    with open(os.path.join(config.DEV_SIGNING_KEYS_DIR, f"{kid}.public.pem"), "w") as f:
        f.write(pub_pem)


async def ensure_active_key(db: AsyncSession) -> SigningKey:
    """Return the current ACTIVE signing key, generating one if none exists."""
    row = (await db.execute(select(SigningKey).where(SigningKey.status == "ACTIVE"))).scalars().first()
    if row:
        return row
    kid = _new_kid()
    priv_pem, pub_pem = _generate()
    _mirror_to_disk(kid, priv_pem, pub_pem)
    row = SigningKey(kid=kid, public_pem=pub_pem, private_pem=priv_pem, status="ACTIVE")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def rotate_key(db: AsyncSession) -> SigningKey:
    """Create a new ACTIVE key and RETIRE the previous ACTIVE (still trusted for verification)."""
    current = (await db.execute(select(SigningKey).where(SigningKey.status == "ACTIVE"))).scalars().all()
    for k in current:
        k.status = "RETIRED"
        k.retired_at = datetime.now(timezone.utc)
    kid = _new_kid()
    priv_pem, pub_pem = _generate()
    _mirror_to_disk(kid, priv_pem, pub_pem)
    row = SigningKey(kid=kid, public_pem=pub_pem, private_pem=priv_pem, status="ACTIVE")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def load_private(signing_key: SigningKey) -> Ed25519PrivateKey:
    return serialization.load_pem_private_key(signing_key.private_pem.encode("utf-8"), password=None)


async def public_keys(db: AsyncSession) -> dict[str, str]:
    """Return kid -> public PEM for all ACTIVE and RETIRED keys (trusted for verification)."""
    rows = (await db.execute(select(SigningKey).where(SigningKey.status.in_(["ACTIVE", "RETIRED"])))).scalars().all()
    return {r.kid: r.public_pem for r in rows}
