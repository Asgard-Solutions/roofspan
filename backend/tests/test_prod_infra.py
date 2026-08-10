"""Production infra code additions (in-container tests; no AWS calls)."""
import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from control_plane import config, signer, operator_auth
from relay.registry import MemoryRegistry


def _pem():
    p = Ed25519PrivateKey.generate()
    return p.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption()).decode()


def test_local_signer_signs_and_verifies():
    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
    s = signer.LocalEd25519Signer(pem, "cp-test")
    sig = s.sign(b"hello")
    priv.public_key().verify(sig, b"hello")  # raises if invalid


def test_signer_kms_selection_fail_fast(monkeypatch):
    monkeypatch.setattr(config, "ENTITLEMENT_SIGNER", "kms")
    monkeypatch.setattr(config, "CP_KMS_SIGNING_KEY_ID", "")
    with pytest.raises(RuntimeError):
        signer.build_signer(_pem(), "cp-test")


def test_production_never_uses_local_signer(monkeypatch):
    monkeypatch.setattr(config, "ENTITLEMENT_SIGNER", "local")
    monkeypatch.setattr(config, "CP_ENV", "production")
    with pytest.raises(RuntimeError):
        signer.build_signer(_pem(), "cp-test")


def test_require_production_config(monkeypatch):
    monkeypatch.setattr(config, "CP_ENV", "dev")
    config.require_production_config()  # no-op in dev
    monkeypatch.setattr(config, "CP_ENV", "production")
    monkeypatch.setattr(config, "BILLING_MODE", "mock")
    with pytest.raises(RuntimeError):
        config.require_production_config()


def test_operator_auth_requires_config_and_bearer(monkeypatch):
    monkeypatch.setattr(config, "CP_OPERATOR_ISSUER", "")
    monkeypatch.setattr(config, "CP_OPERATOR_AUDIENCE", "")
    with pytest.raises(Exception):
        operator_auth.verify_operator("Bearer x")
    monkeypatch.setattr(config, "CP_OPERATOR_ISSUER", "https://issuer")
    monkeypatch.setattr(config, "CP_OPERATOR_AUDIENCE", "aud")
    with pytest.raises(Exception):
        operator_auth.verify_operator(None)  # missing bearer


def test_relay_registry_routing_and_ttl():
    t = {"now": 1000.0}
    reg = MemoryRegistry(ttl=45, now=lambda: t["now"])
    reg.register("inst-1", "nodeA")
    assert reg.lookup_node("inst-1") == "nodeA"
    # duplicate connection / reconnect on another node: newest wins
    reg.register("inst-1", "nodeB")
    assert reg.lookup_node("inst-1") == "nodeB"
    # stale heartbeat from the old node is rejected
    assert reg.heartbeat("inst-1", "nodeA") is False
    assert reg.heartbeat("inst-1", "nodeB") is True
    # TTL expiry => dead node no longer routable
    t["now"] += 100
    assert reg.lookup_node("inst-1") is None


def test_relay_registry_get_valkey_fail_fast(monkeypatch):
    from relay import registry
    monkeypatch.setenv("RELAY_REGISTRY", "valkey")
    monkeypatch.delenv("RELAY_VALKEY_URL", raising=False)
    with pytest.raises(RuntimeError):
        registry.get_registry("nodeA")
