"""Ed25519 signing/verification for RoofSpan Windows UPDATE packages.

SEPARATE TRUST DOMAIN from licensing entitlements — a distinct key hierarchy. The installed updater
embeds ONLY the update public key; the production update-signing private key stays outside customer
installations and source control (HUMAN REQUIRED to provision). Established library only (cryptography).
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from updater.manifest import Manifest, canonical_bytes

KEY_DOMAIN = "roofspan-windows-update-v1"  # domain-separation tag; distinct from entitlement signing


def generate_keypair() -> tuple[str, str]:
    """DEV/test only. Returns (private_pem, public_pem). Production keys are provisioned externally."""
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode()
    pub_pem = priv.public_key().public_bytes(serialization.Encoding.PEM,
                                              serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv_pem, pub_pem


def _signing_message(m: Manifest) -> bytes:
    return KEY_DOMAIN.encode() + b"\n" + canonical_bytes(m.payload())


def sign_manifest(m: Manifest, private_pem: str) -> str:
    priv = serialization.load_pem_private_key(private_pem.encode(), password=None)
    return base64.b64encode(priv.sign(_signing_message(m))).decode()


def verify_manifest(m: Manifest, public_pem: str) -> bool:
    if not m.signature:
        return False
    pub = serialization.load_pem_public_key(public_pem.encode())
    if not isinstance(pub, Ed25519PublicKey):
        return False
    try:
        pub.verify(base64.b64decode(m.signature), _signing_message(m))
        return True
    except Exception:
        return False
