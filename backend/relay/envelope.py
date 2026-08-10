"""Versioned internal cross-node Pub/Sub envelope for the Secure Relay.

This is the relay's OWN wire format between nodes (distinct from relay.protocol, the client protocol).
It is validated on receive and NEVER persisted. It carries a single routed request or its response.
"""
from __future__ import annotations

RELAY_INTERNAL_VERSION = 1

T_REQUEST = "request"
T_RESPONSE = "response"


class EnvelopeError(ValueError):
    """Malformed / unsupported cross-node envelope."""


def build_request(source_node: str, target_node: str, installation_id: str, correlation_id: str, frame: dict) -> dict:
    return {
        "relay_internal_version": RELAY_INTERNAL_VERSION,
        "type": T_REQUEST,
        "source_node": source_node,
        "target_node": target_node,
        "installation_id": installation_id,
        "correlation_id": correlation_id,
        "frame": frame,
    }


def build_response(source_node: str, target_node: str, installation_id: str, correlation_id: str, frame: dict) -> dict:
    return {
        "relay_internal_version": RELAY_INTERNAL_VERSION,
        "type": T_RESPONSE,
        "source_node": source_node,
        "target_node": target_node,
        "installation_id": installation_id,
        "correlation_id": correlation_id,
        "frame": frame,
    }


def validate(env) -> dict:
    """Return the envelope if valid, else raise EnvelopeError. Rejects unknown version/type/shape."""
    if not isinstance(env, dict):
        raise EnvelopeError("envelope is not an object")
    if env.get("relay_internal_version") != RELAY_INTERNAL_VERSION:
        raise EnvelopeError(f"unsupported version {env.get('relay_internal_version')!r}")
    if env.get("type") not in (T_REQUEST, T_RESPONSE):
        raise EnvelopeError(f"unknown type {env.get('type')!r}")
    for k in ("source_node", "target_node", "installation_id", "correlation_id"):
        v = env.get(k)
        if not isinstance(v, str) or not v:
            raise EnvelopeError(f"missing/invalid {k}")
    if not isinstance(env.get("frame"), dict):
        raise EnvelopeError("frame must be an object")
    return env
