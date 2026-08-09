"""Key management.

DEV (Phase C0): a locally-generated Ed25519 keypair used to sign/verify entitlements.
  - Private key: dev-only, on-disk under DEV_KEYS_DIR (git-ignored), used by the in-process
    dev Control Plane. It simulates the future Control Plane signer.
  - Public verify key(s): registered in a trusted-keys map keyed by `kid`. In production the
    trusted verify key(s) are baked into the RoofSpan release; the local server only ever needs
    the PUBLIC key to validate entitlements.

PRODUCTION: the entitlement signing PRIVATE key lives ONLY on the Control Plane and is NEVER
shipped to a customer installation or committed to this repository. This module only ever loads
private material in dev mode.
"""
import os
import logging

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from licensing import config

logger = logging.getLogger("roofspan")

_priv_path = os.path.join(config.DEV_KEYS_DIR, f"{config.DEV_KID}.private.pem")
_pub_path = os.path.join(config.DEV_KEYS_DIR, f"{config.DEV_KID}.public.pem")


def _ensure_dev_keypair() -> None:
    """Generate the dev signing keypair on first use (dev mode only)."""
    if os.path.exists(_priv_path) and os.path.exists(_pub_path):
        return
    os.makedirs(config.DEV_KEYS_DIR, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with open(_priv_path, "wb") as f:
        f.write(priv_pem)
    os.chmod(_priv_path, 0o600)
    with open(_pub_path, "wb") as f:
        f.write(pub_pem)
    logger.warning("Generated DEV licensing signing keypair (%s). DEV ONLY — not for production.", config.DEV_KID)


def get_dev_signing_key() -> tuple[str, Ed25519PrivateKey]:
    """Return (kid, private key) for the dev Control Plane signer. Dev mode only."""
    _ensure_dev_keypair()
    with open(_priv_path, "rb") as f:
        priv = serialization.load_pem_private_key(f.read(), password=None)
    return config.DEV_KID, priv


def get_trusted_verify_keys() -> dict[str, Ed25519PublicKey]:
    """Map of kid -> public verify key trusted by the local installation.

    In production this is populated from keys baked into the release (+ refreshable signed
    version policy). In dev it is the locally-generated dev public key.
    """
    keys: dict[str, Ed25519PublicKey] = {}
    if os.path.exists(_pub_path):
        with open(_pub_path, "rb") as f:
            keys[config.DEV_KID] = serialization.load_pem_public_key(f.read())
    else:
        # Ensure a dev key exists so verification works out of the box in dev.
        _ensure_dev_keypair()
        with open(_pub_path, "rb") as f:
            keys[config.DEV_KID] = serialization.load_pem_public_key(f.read())
    return keys
