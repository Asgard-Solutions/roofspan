"""Relay node registry + cross-node routing abstraction for MULTI-NODE Secure Relay on ECS/Fargate.

Correctness must NOT depend on ALB sticky sessions: an installation tunnel may land on relay node A while
a Mobile connection lands on node B. Valkey provides (1) installation -> relay-node registry with TTL
liveness, and (2) bounded Pub/Sub so node B can forward a routed frame to node A. Valkey holds only
ephemeral routing metadata — NEVER customer business data, never a durable database.

`RELAY_REGISTRY=memory` (dev/single-node/tests, default) | `valkey` (production). The Valkey client
(redis.asyncio, wire-compatible) is imported lazily so dev never needs it.
"""
from __future__ import annotations

import os
import time

REGISTRY_TTL_SECONDS = int(os.environ.get("RELAY_REGISTRY_TTL", "45"))  # heartbeat renews well within TTL


class MemoryRegistry:
    """Single-process registry (dev/tests). Newest live tunnel replaces a stale one."""

    def __init__(self, ttl: int = REGISTRY_TTL_SECONDS, now=time.time):
        self._ttl = ttl
        self._now = now
        self._reg: dict[str, tuple[str, float]] = {}  # installation_id -> (node_id, expires_at)

    def register(self, installation_id: str, node_id: str) -> None:
        # Duplicate connection / reconnect: the newest authenticated tunnel wins.
        self._reg[installation_id] = (node_id, self._now() + self._ttl)

    def heartbeat(self, installation_id: str, node_id: str) -> bool:
        cur = self._reg.get(installation_id)
        if not cur or cur[0] != node_id:
            return False
        self._reg[installation_id] = (node_id, self._now() + self._ttl)
        return True

    def unregister(self, installation_id: str, node_id: str) -> None:
        cur = self._reg.get(installation_id)
        if cur and cur[0] == node_id:
            del self._reg[installation_id]

    def lookup_node(self, installation_id: str) -> str | None:
        cur = self._reg.get(installation_id)
        if not cur:
            return None
        node_id, expires = cur
        if expires < self._now():  # stale (dead node) — not routable
            del self._reg[installation_id]
            return None
        return node_id


class ValkeyRegistry:
    """Production registry using Valkey (Redis-compatible). Keys carry TTL for automatic dead-node cleanup;
    a per-node Pub/Sub channel carries routed frames when the tunnel lives on another node."""

    def __init__(self, url: str, node_id: str, ttl: int = REGISTRY_TTL_SECONDS):
        import redis.asyncio as redis  # lazy

        self._r = redis.from_url(url, decode_responses=True)
        self._node = node_id
        self._ttl = ttl

    @staticmethod
    def _key(installation_id: str) -> str:
        return f"relay:route:{installation_id}"

    async def register(self, installation_id: str) -> None:
        await self._r.set(self._key(installation_id), self._node, ex=self._ttl)

    async def heartbeat(self, installation_id: str) -> bool:
        # Renew only if we still own the route (newest-tunnel-wins is enforced by re-register on connect).
        cur = await self._r.get(self._key(installation_id))
        if cur != self._node:
            return False
        await self._r.expire(self._key(installation_id), self._ttl)
        return True

    async def unregister(self, installation_id: str) -> None:
        cur = await self._r.get(self._key(installation_id))
        if cur == self._node:
            await self._r.delete(self._key(installation_id))

    async def lookup_node(self, installation_id: str) -> str | None:
        return await self._r.get(self._key(installation_id))  # None once TTL expires (dead node)

    def channel(self, node_id: str) -> str:
        return f"relay:node:{node_id}"


def get_registry(node_id: str):
    mode = os.environ.get("RELAY_REGISTRY", "memory").strip().lower()
    if mode == "valkey":
        url = os.environ.get("RELAY_VALKEY_URL")
        if not url:
            raise RuntimeError("RELAY_REGISTRY=valkey but RELAY_VALKEY_URL is not set")
        return ValkeyRegistry(url, node_id)
    return MemoryRegistry()
