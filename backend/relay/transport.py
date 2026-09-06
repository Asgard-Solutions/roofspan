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
    """In-memory Pub/Sub broker shared by multiple RelayHubs in ONE process (tests only).

    Supports MULTIPLE subscribers per channel so several nodes can share the broadcast channel in a
    single process (broadcast fan-out tests); node channels naturally have one subscriber each."""

    def __init__(self):
        self._subs: dict[str, list[Handler]] = {}

    async def start(self) -> None:  # symmetry with ValkeyTransport
        return None

    async def stop(self) -> None:
        self._subs.clear()

    async def subscribe(self, channel: str, handler: Handler) -> None:
        self._subs.setdefault(channel, []).append(handler)

    async def unsubscribe(self, channel: str) -> None:
        self._subs.pop(channel, None)

    async def publish(self, channel: str, message: str) -> None:
        handlers = list(self._subs.get(channel, ()))
        # Deliver asynchronously so publish() never blocks on a handler (mirrors real Pub/Sub).
        for handler in handlers:
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
        self._handlers: dict[str, Handler] = {}   # channel -> handler (supports node + broadcast)
        self._channels: list[str] = []
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
        # Additive: a node subscribes to BOTH its node channel and the shared broadcast channel on the
        # same pubsub connection; the read loop dispatches by the message's channel.
        self._handlers[channel] = handler
        if channel not in self._channels:
            self._channels.append(channel)
        if self._pubsub is None:
            self._pubsub = self._r.pubsub()
        await self._pubsub.subscribe(channel)
        if self._reader is None:
            self._reader = asyncio.create_task(self._read_loop())

    async def unsubscribe(self, channel: str) -> None:  # pragma: no cover - live Valkey
        self._handlers.pop(channel, None)
        if channel in self._channels:
            self._channels.remove(channel)
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
        for ch in self._channels:
            await self._pubsub.subscribe(ch)

    async def _read_loop(self) -> None:  # pragma: no cover - live Valkey
        backoff = 1.0
        while not self._stopped:
            try:
                async for msg in self._pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    ch = msg.get("channel")
                    data = msg.get("data")
                    handler = self._handlers.get(ch)
                    if handler is not None and data is not None:
                        asyncio.create_task(handler(data))
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
