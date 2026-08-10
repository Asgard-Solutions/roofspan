"""Cross-node Pub/Sub transport for the Secure Relay.

The relay forwards a routed frame to whichever node currently owns the installation tunnel by
publishing an envelope to that node's channel (``relay:node:{node_id}``) and subscribing to its own.

  * ValkeyTransport — production Redis/Valkey Pub/Sub (lazy import). One background reader task.
  * InProcessBus    — TESTS ONLY. Models node channels + publish/subscribe lifecycle in a single
                      process. NEVER production-selectable (build_transport never returns it).

Transports carry opaque already-serialized text messages; envelope schema/validation lives in the hub.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from relay import config as C

log = logging.getLogger("roofspan.relay.transport")

Handler = Callable[[str], Awaitable[None]]


class InProcessBus:
    """In-memory Pub/Sub broker shared by multiple RelayHubs in ONE process (tests only)."""

    def __init__(self):
        self._subs: dict[str, Handler] = {}

    async def start(self) -> None:  # symmetry with ValkeyTransport
        return None

    async def stop(self) -> None:
        self._subs.clear()

    async def subscribe(self, channel: str, handler: Handler) -> None:
        self._subs[channel] = handler

    async def unsubscribe(self, channel: str) -> None:
        self._subs.pop(channel, None)

    async def publish(self, channel: str, message: str) -> None:
        handler = self._subs.get(channel)
        if handler is None:
            return  # target node not present / not subscribed
        # Deliver asynchronously so publish() never blocks on the handler (mirrors real Pub/Sub).
        asyncio.create_task(handler(message))


class ValkeyTransport:
    """Production Valkey Pub/Sub. Subscribes to this node's channel; a single reader task dispatches
    incoming messages to the registered handler. Reconnect is handled by re-running the reader loop."""

    def __init__(self, url: str, node_id: str):
        import redis.asyncio as redis  # lazy

        self._redis = redis
        self._url = url
        # health_check_interval lets redis.asyncio detect a dead socket instead of hanging forever
        # on a half-open connection (otherwise a reader can silently stall = routing silently dead).
        self._r = redis.from_url(url, decode_responses=True, health_check_interval=2,
                                 socket_keepalive=True)
        self._node_id = node_id
        self._pubsub = None
        self._reader: asyncio.Task | None = None
        self._handler: Handler | None = None
        self._channel: str | None = None
        self._stopped = False

    async def start(self) -> None:  # pragma: no cover - requires live Valkey
        await self._r.ping()

    async def stop(self) -> None:  # pragma: no cover - requires live Valkey
        self._stopped = True
        if self._reader:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._pubsub is not None:
            try:
                await self._pubsub.aclose()
            except Exception:  # noqa: BLE001
                pass
        try:
            await self._r.aclose()
        except Exception:  # noqa: BLE001
            pass

    async def subscribe(self, channel: str, handler: Handler) -> None:  # pragma: no cover - live Valkey
        self._channel = channel
        self._handler = handler
        self._pubsub = self._r.pubsub()
        await self._pubsub.subscribe(channel)
        self._reader = asyncio.create_task(self._read_loop())

    async def unsubscribe(self, channel: str) -> None:  # pragma: no cover - live Valkey
        if self._pubsub is not None:
            await self._pubsub.unsubscribe(channel)

    async def publish(self, channel: str, message: str) -> None:  # pragma: no cover - live Valkey
        await self._r.publish(channel, message)

    async def _reconnect(self) -> None:  # pragma: no cover - live Valkey
        # Rebuild the client + pubsub from scratch — redis.asyncio can otherwise keep handing out a
        # dead pooled connection after the server bounces (Valkey failover/restart), never recovering.
        try:
            if self._pubsub is not None:
                await self._pubsub.aclose()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self._r.aclose()
        except Exception:  # noqa: BLE001
            pass
        self._r = self._redis.from_url(self._url, decode_responses=True, health_check_interval=2,
                                       socket_keepalive=True)
        self._pubsub = self._r.pubsub()
        await self._pubsub.subscribe(self._channel)

    async def _read_loop(self) -> None:  # pragma: no cover - live Valkey
        backoff = 1.0
        while not self._stopped:
            try:
                async for msg in self._pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    data = msg.get("data")
                    if self._handler is not None and data is not None:
                        asyncio.create_task(self._handler(data))
                backoff = 1.0
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                if self._stopped:
                    break
                log.warning("relay transport read loop error: %s (reconnect in %ss)", str(e)[:160], backoff)
                await asyncio.sleep(backoff)
                backoff = min(10.0, backoff * 2)
                try:
                    await self._reconnect()
                    backoff = 1.0
                except Exception:  # noqa: BLE001
                    pass


def build_transport(node_id: str):
    """Production transport only. Returns None in memory mode (single-node local routing needs none)."""
    if C.RELAY_REGISTRY == "valkey":
        if not C.RELAY_VALKEY_URL:
            raise RuntimeError("RELAY_REGISTRY=valkey but RELAY_VALKEY_URL is not set")
        return ValkeyTransport(C.RELAY_VALKEY_URL, node_id)
    return None
