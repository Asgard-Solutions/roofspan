"""Production entitlement signer (AWS KMS Ed25519) tests.

The AWS KMS API is mocked with a fake backed by a REAL Ed25519 key so the full loop is proven:
  * KMS Sign is called with the exact KeyId / SigningAlgorithm=ED25519_SHA_512 / MessageType=RAW /
    canonical message bytes, and returns a standard 64-byte Ed25519 signature (RFC 8032 PureEdDSA).
  * KMS GetPublicKey returns DER SubjectPublicKeyInfo; the signer exports it as PEM.
  * A JWS built via sign_entitlement_via_signer(kms_signer) VERIFIES with that exported public key,
    identically to a locally PyJWT-signed token — RoofSpan Office needs no KMS call to verify.
No real AWS calls are made.
"""
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from control_plane import config, signer as signer_mod
from licensing import entitlement as ent


class FakeKms:
    """Mimics boto3 KMS for an Ed25519 SIGN_VERIFY key, backed by a real Ed25519 key."""

    def __init__(self, priv: Ed25519PrivateKey, expect_key_id: str):
        self._priv = priv
        self._expect = expect_key_id
        self.sign_calls = []

    def sign(self, *, KeyId, Message, MessageType, SigningAlgorithm):
        self.sign_calls.append(dict(KeyId=KeyId, Message=Message, MessageType=MessageType,
                                    SigningAlgorithm=SigningAlgorithm))
        assert KeyId == self._expect
        assert MessageType == "RAW"
        assert SigningAlgorithm == "ED25519_SHA_512"
        return {"Signature": self._priv.sign(Message)}  # RFC 8032 PureEdDSA over the raw message

    def get_public_key(self, *, KeyId):
        assert KeyId == self._expect
        der = self._priv.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        return {"PublicKey": der, "KeyId": KeyId}


def _kms_signer(monkeypatch, key_id="arn:aws:kms:us-east-1:111:key/abc", kid="cp-test"):
    priv = Ed25519PrivateKey.generate()
    fake = FakeKms(priv, key_id)
    s = signer_mod.KmsEd25519Signer.__new__(signer_mod.KmsEd25519Signer)
    s.key_id = key_id
    s.kid = kid
    s._kms = fake
    return s, fake, priv


def _claims():
    now = datetime.now(timezone.utc)
    return {"installation_id": "11111111-1111-1111-1111-111111111111",
            "company_id": "22222222-2222-2222-2222-222222222222",
            "license_id": "33333333-3333-3333-3333-333333333333",
            "subscription_state": "ACTIVE", "seats_licensed": 5, "product": "roofspan-office",
            "min_supported_version": "1.0.0", "issued_at": now,
            "refresh_at": now + timedelta(hours=12), "grace_until": now + timedelta(days=7),
            "nonce": "abc123"}


def test_kms_sign_uses_ed25519_sha512_raw_and_canonical_bytes(monkeypatch):
    s, fake, _priv = _kms_signer(monkeypatch)
    msg = b"header.payload-canonical-bytes"
    sig = s.sign(msg)
    assert isinstance(sig, bytes) and len(sig) == 64            # raw Ed25519 signature
    call = fake.sign_calls[-1]
    assert call["SigningAlgorithm"] == "ED25519_SHA_512"
    assert call["MessageType"] == "RAW"
    assert call["Message"] == msg                                # exact canonical bytes, no prehash
    assert call["KeyId"] == s.key_id


def test_kms_public_key_pem_matches_key(monkeypatch):
    s, _fake, priv = _kms_signer(monkeypatch)
    pem = s.public_key_pem()
    assert pem.startswith("-----BEGIN PUBLIC KEY-----")
    expected = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    assert pem == expected


def test_kms_signed_jws_verifies_with_exported_public_key(monkeypatch):
    """End-to-end: KMS-signed entitlement JWS verifies with the exported public key, and decodes to
    the same claims as a locally PyJWT-signed token (canonical semantics preserved)."""
    s, _fake, priv = _kms_signer(monkeypatch, kid="cp-kms-1")
    claims = _claims()
    token_kms = ent.sign_entitlement_via_signer(signer=s, kid=s.kid, claims=claims)
    trusted = {s.kid: s.public_key_pem()}
    got = ent.verify_entitlement(token_kms, trusted)
    assert got.subscription_state == "ACTIVE" and got.seats_licensed == 5
    assert got.installation_id == claims["installation_id"]

    # Same claims signed locally (PyJWT) with the same key must decode to the same core claims.
    priv_pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode()
    token_local = ent.sign_entitlement(private_key=priv_pem, kid=s.kid, claims=claims)
    got_local = ent.verify_entitlement(token_local, trusted)
    assert (got.installation_id, got.company_id, got.subscription_state, got.seats_licensed) == \
           (got_local.installation_id, got_local.company_id, got_local.subscription_state, got_local.seats_licensed)


def test_kms_sign_missing_signature_raises(monkeypatch):
    s, fake, _ = _kms_signer(monkeypatch)
    monkeypatch.setattr(fake, "sign", lambda **kw: {})  # malformed KMS response
    with pytest.raises(RuntimeError):
        s.sign(b"x")


def test_kms_public_key_missing_raises(monkeypatch):
    s, fake, _ = _kms_signer(monkeypatch)
    monkeypatch.setattr(fake, "get_public_key", lambda **kw: {})  # malformed response
    with pytest.raises(RuntimeError):
        s.public_key_pem()


def test_kms_unavailable_propagates(monkeypatch):
    s, fake, _ = _kms_signer(monkeypatch)
    def _boom(**kw):
        raise RuntimeError("kms endpoint unreachable")
    monkeypatch.setattr(fake, "sign", _boom)
    with pytest.raises(RuntimeError):
        s.sign(b"x")


def test_build_signer_kms_requires_key_id(monkeypatch):
    monkeypatch.setattr(config, "ENTITLEMENT_SIGNER", "kms")
    monkeypatch.setattr(config, "CP_KMS_SIGNING_KEY_ID", "")
    with pytest.raises(RuntimeError):
        signer_mod.build_signer("ignored", "cp-test")


def test_build_signer_production_never_local(monkeypatch):
    monkeypatch.setattr(config, "ENTITLEMENT_SIGNER", "local")
    monkeypatch.setattr(config, "CP_ENV", "production")
    with pytest.raises(RuntimeError):
        signer_mod.build_signer("some-pem", "cp-test")


def test_local_signer_still_functional():
    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
    s = signer_mod.LocalEd25519Signer(pem, "cp-local")
    sig = s.sign(b"hello")
    priv.public_key().verify(sig, b"hello")  # raises if invalid
