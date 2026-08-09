"""Installation identity (Ed25519) — one keypair per installation.

The PRIVATE key is generated and retained locally and is NEVER sent to the Control Plane; only the
PUBLIC key is registered during activation. Kept completely separate from Control-Plane entitlement
signing keys.

DEV/in-container: keys are stored under a git-ignored directory. On a real Windows install the private
key lives in the persistent data dir with restricted ACLs (optionally DPAPI-wrapped) — HUMAN REQUIRED.
"""
from __future__ import annotations

import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _keys_dir() -> str:
    return os.environ.get("INSTALLATION_KEYS_DIR", os.path.join(os.path.dirname(__file__), "installation_keys"))


def _paths() -> tuple[str, str]:
    d = _keys_dir()
    return os.path.join(d, "installation.private.pem"), os.path.join(d, "installation.public.pem")


def get_or_create_identity() -> tuple[Ed25519PrivateKey, str]:
    """Return (private_key, public_pem), generating and persisting on first use."""
    priv_path, pub_path = _paths()
    if os.path.exists(priv_path) and os.path.exists(pub_path):
        with open(priv_path, "rb") as f:
            priv = serialization.load_pem_private_key(f.read(), password=None)
        with open(pub_path, "r") as f:
            return priv, f.read()

    os.makedirs(_keys_dir(), exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    with open(priv_path, "wb") as f:
        f.write(priv_pem)
    os.chmod(priv_path, 0o600)
    with open(pub_path, "w") as f:
        f.write(pub_pem)
    return priv, pub_pem


def load_private_key() -> Ed25519PrivateKey | None:
    priv_path, _ = _paths()
    if not os.path.exists(priv_path):
        return None
    with open(priv_path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def has_identity() -> bool:
    priv_path, _ = _paths()
    return os.path.exists(priv_path)
