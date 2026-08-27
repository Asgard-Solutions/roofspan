"""Regression tests for Railway-native Secure Relay node identity."""

from relay import config as C


def test_relay_node_id_override_wins_over_railway(monkeypatch):
    monkeypatch.setenv("RELAY_NODE_ID", "manual-node")
    monkeypatch.setenv("RAILWAY_REPLICA_ID", "replica-123")
    node_id, source = C._resolve_node_id()
    assert node_id == "manual-node"
    assert source == "env"


def test_railway_replica_id_is_valid_production_identity(monkeypatch):
    monkeypatch.delenv("RELAY_NODE_ID", raising=False)
    monkeypatch.setenv("RAILWAY_REPLICA_ID", "replica-123")
    monkeypatch.delenv("ECS_CONTAINER_METADATA_URI_V4", raising=False)
    node_id, source = C._resolve_node_id()
    assert node_id == "railway-replica-123"
    assert source == "railway"


def test_production_accepts_railway_node_source(monkeypatch):
    monkeypatch.setattr(C, "RELAY_ENV", "production")
    monkeypatch.setattr(C, "RELAY_REGISTRY", "valkey")
    monkeypatch.setattr(C, "RELAY_VALKEY_URL", "redis://redis.railway.internal:6379")
    monkeypatch.setattr(C, "NODE_ID_SOURCE", "railway")
    C.require_production_config()
