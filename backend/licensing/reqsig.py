"""Shared installation-request signing contract (Ed25519).

Used by BOTH the installation (to sign entitlement-refresh requests with its private key) and the
Control Plane (to verify with the registered public key). Defining the canonicalization once keeps
the trust model identical on both sides. No custom cryptographic primitives — Ed25519 via
`cryptography`.

Canonical message = installation_id \n timestamp \n nonce \n sha256_hex(body)
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

# Header names for the signed request.
H_INSTALLATION = "X-RoofSpan-Installation"
H_TIMESTAMP = "X-RoofSpan-Timestamp"
H_NONCE = "X-RoofSpan-Nonce"
H_SIGNATURE = "X-RoofSpan-Signature"


def body_hash(body: bytes) -> str:
    return hashlib.sha256(body or b"").hexdigest()


def canonical_message(installation_id: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    return "\n".join([installation_id, str(timestamp), nonce, body_hash(body)]).encode("utf-8")


def sign_request(private_key: Ed25519PrivateKey, *, installation_id: str, timestamp: str, nonce: str, body: bytes) -> str:
    msg = canonical_message(installation_id, timestamp, nonce, body)
    return base64.b64encode(private_key.sign(msg)).decode("ascii")


def verify_request(public_key_pem: str, *, installation_id: str, timestamp: str, nonce: str, body: bytes, signature_b64: str) -> bool:
    try:
        pub: Ed25519PublicKey = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        pub.verify(base64.b64decode(signature_b64), canonical_message(installation_id, timestamp, nonce, body))
        return True
    except (InvalidSignature, ValueError, Exception):
        return False
