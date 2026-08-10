"""Entitlement signer selection: local Ed25519 PEM (dev) vs AWS KMS Ed25519 (production).

Production selects KMS and NEVER falls back to a local private key — if KMS is misconfigured it fails
clearly. The KMS private key never leaves KMS; RoofSpan Office verifies with the corresponding public key
(published via /signing-keys/public). Separate trust domain from Windows-update / identity / Mobile keys.
"""
from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from control_plane import config


class LocalEd25519Signer:
    """Dev/in-container signer using the ACTIVE key's PEM (existing mechanism)."""

    def __init__(self, private_pem: str, kid: str):
        self._priv: Ed25519PrivateKey = _load(private_pem)
        self.kid = kid

    def sign(self, message: bytes) -> bytes:
        return self._priv.sign(message)


class KmsEd25519Signer:
    """Production signer backed by AWS KMS (KeySpec ECC_NIST_EDWARDS25519, KeyUsage SIGN_VERIFY).

    boto3 is imported lazily so dev/in-container never needs it. NOTE (HUMAN REQUIRED to confirm on AWS):
    the exact SigningAlgorithm/MessageType for Ed25519 must match the current KMS API for this KeySpec.
    """

    def __init__(self, key_id: str, region: str, kid: str):
        import boto3  # lazy

        self.key_id = key_id
        self.kid = kid
        self._kms = boto3.client("kms", region_name=region or None)

    def sign(self, message: bytes) -> bytes:
        resp = self._kms.sign(KeyId=self.key_id, Message=message,
                              MessageType="RAW", SigningAlgorithm="EDDSA")
        return resp["Signature"]


def _load(private_pem: str) -> Ed25519PrivateKey:
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(private_pem.encode("utf-8"), password=None)


def build_signer(active_private_pem: str | None, kid: str):
    """Return the configured signer. Production=kms fails clearly if key id absent (no silent fallback)."""
    if config.ENTITLEMENT_SIGNER == "kms":
        if not config.CP_KMS_SIGNING_KEY_ID:
            raise RuntimeError("ENTITLEMENT_SIGNER=kms but CP_KMS_SIGNING_KEY_ID is not set")
        return KmsEd25519Signer(config.CP_KMS_SIGNING_KEY_ID, config.AWS_REGION, kid)
    if config.CP_ENV == "production":
        raise RuntimeError("Production must not use the local entitlement signer; set ENTITLEMENT_SIGNER=kms")
    if not active_private_pem:
        raise RuntimeError("local signer requires the ACTIVE signing key private PEM")
    return LocalEd25519Signer(active_private_pem, kid)
