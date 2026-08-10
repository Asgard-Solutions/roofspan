"""Live entitlement issuance through the KMS signer abstraction.

Drives the REAL Control Plane issuance path (service.activate -> _issue_entitlement) with
ENTITLEMENT_SIGNER=kms and boto3 KMS mocked by a real Ed25519 key, proving production issuance uses
KMS (ED25519_SHA_512 / RAW / canonical bytes), never the local signer, and that the returned
entitlement verifies with the KMS-exported public key under the matching kid. No real AWS calls.
"""
import asyncio
import uuid

import boto3
import jwt as _jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from control_plane import config, keys as cp_keys, service, signer as cp_signer
from control_plane.db import SessionLocal
from control_plane.models import SigningKey
from licensing import entitlement as ent

KEY_ID = "arn:aws:kms:us-east-1:111111111111:key/entitlement"


def _spki_pem(priv):
    return priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


class _FakeKms:
    def __init__(self, priv):
        self._priv = priv
        self.signed = []

    def sign(self, *, KeyId, Message, MessageType, SigningAlgorithm):
        assert KeyId == KEY_ID
        assert MessageType == "RAW"
        assert SigningAlgorithm == "ED25519_SHA_512"
        self.signed.append(Message)
        return {"Signature": self._priv.sign(Message)}

    def get_public_key(self, *, KeyId):
        assert KeyId == KEY_ID
        der = self._priv.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        return {"PublicKey": der}


def _use_kms(monkeypatch, priv):
    fake = _FakeKms(priv)
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)
    monkeypatch.setattr(config, "ENTITLEMENT_SIGNER", "kms")
    monkeypatch.setattr(config, "CP_KMS_SIGNING_KEY_ID", KEY_ID)
    monkeypatch.setattr(config, "AWS_REGION", "us-east-1")
    cp_signer._signer_cache.clear()
    return fake


def test_live_issuance_uses_kms_and_verifies(monkeypatch):
    priv = Ed25519PrivateKey.generate()          # stands in for the KMS-resident key
    fake = _use_kms(monkeypatch, priv)

    # Production must never touch the local signer.
    def _no_local(*a, **k):
        raise AssertionError("LocalEd25519Signer must not be used when ENTITLEMENT_SIGNER=kms")
    monkeypatch.setattr(cp_signer, "LocalEd25519Signer", _no_local)

    # Transient KMS-backed ACTIVE key (logical kid + KMS public PEM, no private material) — avoids
    # mutating the shared dev signing keys while still exercising the real issuance function.
    kid = f"cp-kmstest-{uuid.uuid4().hex[:8]}"
    transient = SigningKey(kid=kid, public_pem=_spki_pem(priv), private_pem=None, status="ACTIVE")

    async def _ensure(db):
        return transient
    monkeypatch.setattr(cp_keys, "ensure_active_key", _ensure)

    async def scenario():
        async with SessionLocal() as db:
            ipriv = Ed25519PrivateKey.generate()
            res = await service.activate(
                db, company_name=f"KMS Issue Test {uuid.uuid4().hex[:6]}", requested_seats=5,
                public_key_pem=_spki_pem(ipriv), software_version="1.0.0",
                bootstrap_credential=config.DEV_BOOTSTRAP_SECRET)
            return res

    res = asyncio.run(scenario())
    token = res["entitlement_jws"]

    assert fake.signed, "KMS Sign was not invoked"
    assert _jwt.get_unverified_header(token)["kid"] == kid    # JWS kid matches the (published) record
    got = ent.verify_entitlement(token, {kid: transient.public_pem})  # verifies with KMS-exported key
    assert got.installation_id == res["installation_id"]
    assert got.seats_licensed == 5


def test_validate_active_key_mismatch_fails(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    _use_kms(monkeypatch, priv)
    # ACTIVE row's stored public key belongs to a DIFFERENT key than KMS returns -> must fail clearly.
    other = Ed25519PrivateKey.generate()
    row = SigningKey(kid="cp-mismatch", public_pem=_spki_pem(other), private_pem=None, status="ACTIVE")

    class _DB:
        async def execute(self, *a, **k):
            class _R:
                def scalars(self_inner):
                    class _S:
                        def first(self_s):
                            return row
                    return _S()
            return _R()

    with pytest.raises(RuntimeError):
        asyncio.run(cp_keys.validate_active_key(_DB()))


def test_rotation_old_and_new_kids_coexist(monkeypatch):
    """Old + new signing keys must both verify their respective tokens (rotation keeps old public keys
    trusted). Uses the signer abstraction end-to-end."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    claims = {"installation_id": "aaaa", "company_id": "bbbb", "license_id": "cccc",
              "subscription_state": "ACTIVE", "seats_licensed": 5, "product": "roofspan-office",
              "issued_at": now, "refresh_at": now + timedelta(hours=12),
              "grace_until": now + timedelta(days=7), "nonce": "n"}

    old_priv, new_priv = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    old = cp_signer.LocalEd25519Signer(
        old_priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()).decode(), "cp-old")
    new = cp_signer.LocalEd25519Signer(
        new_priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()).decode(), "cp-new")
    tok_old = ent.sign_entitlement_via_signer(signer=old, kid="cp-old", claims=claims)
    tok_new = ent.sign_entitlement_via_signer(signer=new, kid="cp-new", claims=claims)
    trusted = {"cp-old": _spki_pem(old_priv), "cp-new": _spki_pem(new_priv)}  # both trusted (retired+active)
    assert ent.verify_entitlement(tok_old, trusted).kid == "cp-old"
    assert ent.verify_entitlement(tok_new, trusted).kid == "cp-new"
