"""Relay node registry + cross-node routing abstraction for MULTI-NODE Secure Relay on ECS/Fargate.

Correctness must NOT depend on ALB sticky sessions: an installation tunnel may land on relay node A
while a Mobile connection lands on node B. The registry maps installation_id -> owning relay node id
with TTL liveness so node B can discover that node A owns the tunnel and forward the routed frame
over Pub/Sub. The registry holds ONLY ephemeral routing metadata — NEVER customer business data.

Interfaces:
  * MemoryRegistry       — SYNC, single-process (kept for existing unit tests). node_id per call.
  * AsyncMemoryRegistry  — ASYNC, node-bound, shareable backing store (dev/tests, multi-node unit tests).
  * ValkeyRegistry       — ASYNC, node-bound, production. Ownership-sensitive ops are ATOMIC (Lua)
                           so an older owner can never delete/renew a newer owner's registration.

`RelayHub` always talks to the ASYNC interface (AsyncMemoryRegistry | ValkeyRegistry).
"""
from __future__ import annotations

import time

from relay import config as C

REGISTRY_TTL_SECONDS = C.REGISTRY_TTL_SECONDS  # heartbeat renews well within TTL


def _route_key(installation_id: str) -> str:
    return f"relay:route:{installation_id}"


def node_channel(node_id: str) -> str:
    return f"relay:node:{node_id}"


class MemoryRegistry:
    """SYNC single-process registry (legacy unit tests). Newest live tunnel replaces a stale one."""

    def __init__(self, ttl: int = REGISTRY_TTL_SECONDS, now=time.time):
        self._ttl = ttl
        self._now = now
        self._reg: dict[str, tuple[str, float]] = {}  # installation_id -> (node_id, expires_at)

    def register(self, installation_id: str, node_id: str) -> None:
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


class AsyncMemoryRegistry:
    """ASYNC node-bound registry (dev/tests). Pass a shared ``store`` dict to model multiple nodes
    sharing one Valkey-equivalent keyspace in a single process (multi-node unit tests)."""

    def __init__(self, node_id: str, ttl: int = REGISTRY_TTL_SECONDS, now=time.time, store: dict | None = None):
        self.node_id = node_id
        self._ttl = ttl
        self._now = now
        self._reg: dict[str, tuple[str, float]] = store if store is not None else {}

    async def register(self, installation_id: str) -> None:
        # Newest authenticated tunnel wins — authoritative, unconditional.
        self._reg[installation_id] = (self.node_id, self._now() + self._ttl)

    async def heartbeat(self, installation_id: str) -> bool:
        cur = self._reg.get(installation_id)
        if not cur or cur[0] != self.node_id or cur[1] < self._now():
            return False
        self._reg[installation_id] = (self.node_id, self._now() + self._ttl)
        return True

    async def unregister(self, installation_id: str) -> None:
        # Compare-and-delete: only the current owner may delete (older owner can't drop a newer one).
        cur = self._reg.get(installation_id)
        if cur and cur[0] == self.node_id:
            del self._reg[installation_id]

    async def lookup_node(self, installation_id: str) -> str | None:
        cur = self._reg.get(installation_id)
        if not cur:
            return None
        node_id, expires = cur
        if expires < self._now():
            del self._reg[installation_id]
            return None
        return node_id


# Atomic ownership-sensitive Valkey ops (avoid GET-then-DELETE / GET-then-EXPIRE races).
_LUA_COMPARE_DEL = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
_LUA_COMPARE_PEXPIRE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end"


class ValkeyRegistry:
    """Production registry using Valkey (Redis-compatible). Keys carry TTL for automatic dead-node
    cleanup. Ownership-sensitive ops are atomic (Lua) so newest-tunnel-wins is race-safe."""

    def __init__(self, url: str, node_id: str, ttl: int = REGISTRY_TTL_SECONDS):
        import redis.asyncio as redis  # lazy

        self._r = redis.from_url(url, decode_responses=True)
        self.node_id = node_id
        self._ttl = ttl

    async def register(self, installation_id: str) -> None:
        # Newest authenticated tunnel wins — authoritative SET with TTL.
        await self._r.set(_route_key(installation_id), self.node_id, ex=self._ttl)

    async def heartbeat(self, installation_id: str) -> bool:
        renewed = await self._r.eval(
            _LUA_COMPARE_PEXPIRE, 1, _route_key(installation_id), self.node_id, str(self._ttl * 1000)
        )
        return bool(renewed)

    async def unregister(self, installation_id: str) -> None:
        await self._r.eval(_LUA_COMPARE_DEL, 1, _route_key(installation_id), self.node_id)

    async def lookup_node(self, installation_id: str) -> str | None:
        return await self._r.get(_route_key(installation_id))  # None once TTL expires (dead node)

    async def aclose(self) -> None:  # pragma: no cover - prod lifecycle
        try:
            await self._r.aclose()
        except Exception:  # noqa: BLE001
            pass


def get_registry(node_id: str):
    """Build the ASYNC registry for the given node. Reads env live (so tests can monkeypatch),
    falling back to the config snapshot. Fails fast for misconfigured Valkey."""
    import os

    mode = os.environ.get("RELAY_REGISTRY", C.RELAY_REGISTRY).strip().lower()
    if mode == "valkey":
        url = os.environ.get("RELAY_VALKEY_URL", C.RELAY_VALKEY_URL or "")
        if not url:
            raise RuntimeError("RELAY_REGISTRY=valkey but RELAY_VALKEY_URL is not set")
        return ValkeyRegistry(url, node_id)
    return AsyncMemoryRegistry(node_id)
