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
    """Production signer backed by AWS KMS.

    KeySpec ECC_NIST_EDWARDS25519, KeyUsage SIGN_VERIFY, SigningAlgorithm ED25519_SHA_512, MessageType
    RAW — i.e. standard RFC 8032 PureEdDSA over the raw message (the "SHA_512" is Ed25519's internal
    hash, NOT a caller prehash). We therefore pass the canonical JWS signing input as-is and never
    locally prehash. The private key NEVER leaves KMS; RoofSpan Office verifies with the exported
    public key. boto3 is imported lazily so dev/in-container never needs it.
    """

    SIGNING_ALGORITHM = "ED25519_SHA_512"

    def __init__(self, key_id: str, region: str, kid: str):
        import boto3  # lazy

        self.key_id = key_id
        self.kid = kid
        self._kms = boto3.client("kms", region_name=region or None)

    def sign(self, message: bytes) -> bytes:
        resp = self._kms.sign(KeyId=self.key_id, Message=message,
                              MessageType="RAW", SigningAlgorithm=self.SIGNING_ALGORITHM)
        sig = resp.get("Signature")
        if not sig:
            raise RuntimeError("KMS Sign returned no Signature")
        return sig  # raw 64-byte Ed25519 signature (EdDSA is not DER-encoded)

    def public_key_pem(self) -> str:
        """Export the KMS public key as PEM SubjectPublicKeyInfo (the representation RoofSpan Office
        already uses to verify). KMS GetPublicKey returns DER SPKI; verification needs NO KMS call."""
        from cryptography.hazmat.primitives import serialization
        resp = self._kms.get_public_key(KeyId=self.key_id)
        der = resp.get("PublicKey")
        if not der:
            raise RuntimeError("KMS GetPublicKey returned no PublicKey")
        pub = serialization.load_der_public_key(der)
        return pub.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("ascii")


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
