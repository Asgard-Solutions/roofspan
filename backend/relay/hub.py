"""Secure Relay routing hub — LOCAL tunnels + MULTI-NODE cross-node routing via a registry + Pub/Sub.

Nothing is persisted; bodies live only in transit. Each relay node runs one RelayHub with a stable
node id. An installation tunnel that authenticates here is (1) held in the local ``_installs`` map and
(2) registered as ``installation_id -> this node`` in the shared registry (newest tunnel wins). A Mobile
request routes directly when the tunnel is local, otherwise the hub looks up the owning node and
forwards a bounded, versioned envelope over Pub/Sub, correlating the response by request id.

Backward compatible: with the default construction (memory registry, no transport) behavior is pure
single-node local routing, so the existing single-node relay suite is unchanged.
"""
from __future__ import annotations

import asyncio
import logging

from relay import config as C
from relay import envelope as E
from relay import protocol as P
from relay import registry as R
from relay import transport as T

log = logging.getLogger("roofspan.relay")


class RelayUnavailable(Exception):
    """No live installation tunnel for the target installation (locally or on any node)."""


class RelayPayloadTooLarge(Exception):
    """Cross-node envelope exceeds the relay payload ceiling; rejected before publish."""


class InstallationConn:
    def __init__(self, installation_id: str, ws):
        self.installation_id = installation_id
        self.ws = ws
        self.pending: dict[str, asyncio.Future] = {}
        self.send_lock = asyncio.Lock()


class RelayHub:
    def __init__(self, node_id: str, registry=None, transport=None):
        self.node_id = node_id
        self._registry = registry
        self._transport = transport
        self._installs: dict[str, InstallationConn] = {}
        self._cross_pending: dict[str, asyncio.Future] = {}  # correlation_id -> future (this node is origin)
        self._hb_task: asyncio.Task | None = None
        self._started = False

    # ---- lifecycle ---------------------------------------------------------
    async def startup(self) -> None:
        """Idempotent. Starts the Pub/Sub listener + heartbeat loop only when a transport exists
        (i.e. multi-node/Valkey mode). Single-node/memory mode needs neither."""
        if self._started:
            return
        self._started = True
        if self._transport is not None:
            await self._transport.start()
            await self._transport.subscribe(R.node_channel(self.node_id), self._on_envelope)
            self._hb_task = asyncio.create_task(self._heartbeat_loop())
            log.info("relay hub started node=%s (multi-node, valkey)", self.node_id)
        else:
            log.info("relay hub started node=%s (single-node, memory)", self.node_id)

    async def shutdown(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._hb_task is not None:
            self._hb_task.cancel()
            try:
                await self._hb_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._hb_task = None
        if self._transport is not None:
            await self._transport.stop()

    # ---- local tunnel registration ----------------------------------------
    async def register(self, conn: InstallationConn) -> None:
        prev = self._installs.get(conn.installation_id)
        if prev is not None and prev is not conn:
            # Replace a stale local tunnel: fail its in-flight requests so callers don't hang.
            for fut in list(prev.pending.values()):
                if not fut.done():
                    fut.set_exception(RelayUnavailable("installation tunnel replaced"))
        self._installs[conn.installation_id] = conn
        if self._registry is not None:
            await self._registry.register(conn.installation_id)  # newest authenticated tunnel wins
        log.info("relay: installation tunnel connected id=%s node=%s (local=%d)",
                 conn.installation_id, self.node_id, len(self._installs))

    async def unregister(self, installation_id: str, conn: InstallationConn) -> None:
        # Only drop the local map entry if it is still THIS connection (an older conn must never
        # evict a newer one) and only release shared ownership if this node still owns it.
        if self._installs.get(installation_id) is conn:
            del self._installs[installation_id]
            for fut in list(conn.pending.values()):
                if not fut.done():
                    fut.set_exception(RelayUnavailable("installation tunnel disconnected"))
            if self._registry is not None:
                await self._registry.unregister(installation_id)  # compare-and-delete (owner-safe)
            log.info("relay: installation tunnel disconnected id=%s node=%s (local=%d)",
                     installation_id, self.node_id, len(self._installs))

    def is_connected(self, installation_id: str) -> bool:
        return installation_id in self._installs

    def resolve(self, installation_id: str, request_id: str, response: dict) -> None:
        """Called when a LOCAL installation tunnel returns a response for a routed request."""
        conn = self._installs.get(installation_id)
        if conn is None:
            return
        fut = conn.pending.get(request_id)
        if fut is not None and not fut.done():
            fut.set_result(response)

    # ---- routing -----------------------------------------------------------
    async def route(self, installation_id: str, request_frame: dict, timeout: float) -> dict:
        conn = self._installs.get(installation_id)
        if conn is not None:
            return await self._route_local_conn(conn, request_frame, timeout)  # local: never touch Valkey
        if self._registry is None:
            raise RelayUnavailable("installation tunnel not connected")
        owner = await self._registry.lookup_node(installation_id)
        if owner is None:
            raise RelayUnavailable("installation tunnel not connected")
        if owner == self.node_id:
            # We are the recorded owner but hold no local tunnel — stale; not routable here.
            raise RelayUnavailable("installation tunnel not connected")
        if self._transport is None:
            raise RelayUnavailable("cross-node routing unavailable")
        return await self._route_cross_node(owner, installation_id, request_frame, timeout)

    async def _route_local_conn(self, conn: InstallationConn, request_frame: dict, timeout: float) -> dict:
        rid = request_frame["request_id"]
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        conn.pending[rid] = fut
        try:
            async with conn.send_lock:
                await conn.ws.send_text(P.dumps(request_frame))
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            conn.pending.pop(rid, None)

    async def _route_cross_node(self, owner: str, installation_id: str, request_frame: dict, timeout: float) -> dict:
        cid = request_frame["request_id"]
        env = E.build_request(self.node_id, owner, installation_id, cid, request_frame)
        raw = P.dumps(env)
        if len(raw.encode("utf-8")) > C.MAX_ENVELOPE_BYTES:
            raise RelayPayloadTooLarge("cross-node request envelope too large")
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._cross_pending[cid] = fut
        try:
            await self._transport.publish(R.node_channel(owner), raw)
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._cross_pending.pop(cid, None)  # never leak correlation entries

    # ---- cross-node Pub/Sub handling --------------------------------------
    async def _on_envelope(self, raw: str) -> None:
        try:
            env = E.validate(P.loads(raw))
        except Exception as e:  # noqa: BLE001 - malformed envelopes are dropped safely
            log.warning("relay: dropped malformed cross-node envelope: %s", str(e)[:160])
            return
        if env["type"] == E.T_REQUEST:
            await self._handle_remote_request(env)
        else:
            self._handle_remote_response(env)

    async def _handle_remote_request(self, env: dict) -> None:
        installation_id = env["installation_id"]
        cid = env["correlation_id"]
        source = env["source_node"]
        conn = self._installs.get(installation_id)
        if conn is None:
            resp_frame = {"__relay_error__": "tunnel_unavailable"}
        else:
            try:
                resp_frame = await self._route_local_conn(conn, env["frame"], C.REQUEST_TIMEOUT)
            except RelayUnavailable:
                resp_frame = {"__relay_error__": "tunnel_unavailable"}
            except (asyncio.TimeoutError, TimeoutError):
                resp_frame = {"__relay_error__": "request_timeout"}
        out = E.build_response(self.node_id, source, installation_id, cid, resp_frame)
        raw = P.dumps(out)
        if len(raw.encode("utf-8")) > C.MAX_ENVELOPE_BYTES:
            out = E.build_response(self.node_id, source, installation_id, cid,
                                   {"__relay_error__": "response_too_large"})
            raw = P.dumps(out)
        await self._transport.publish(R.node_channel(source), raw)

    def _handle_remote_response(self, env: dict) -> None:
        cid = env["correlation_id"]
        fut = self._cross_pending.get(cid)
        if fut is None or fut.done():
            return  # unknown / duplicate / late response — ignore safely
        frame = env["frame"]
        err = frame.get("__relay_error__") if isinstance(frame, dict) else None
        if err == "request_timeout":
            fut.set_exception(asyncio.TimeoutError())
        elif err:
            fut.set_exception(RelayUnavailable(err))
        else:
            fut.set_result(frame)

    # ---- heartbeat ---------------------------------------------------------
    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(C.HEARTBEAT_INTERVAL)
            for installation_id, conn in list(self._installs.items()):
                try:
                    owned = await self._registry.heartbeat(installation_id)
                except Exception as e:  # noqa: BLE001
                    log.warning("relay heartbeat error id=%s: %s", installation_id, str(e)[:160])
                    continue
                if not owned:
                    # A newer authenticated tunnel took ownership elsewhere — this local tunnel is
                    # superseded/stale. Drop it locally (fail pending) so we never serve a stale route.
                    if self._installs.get(installation_id) is conn:
                        del self._installs[installation_id]
                        for fut in list(conn.pending.values()):
                            if not fut.done():
                                fut.set_exception(RelayUnavailable("installation tunnel superseded"))
                        log.info("relay: local tunnel superseded id=%s node=%s", installation_id, self.node_id)


def build_hub() -> RelayHub:
    node_id = C.NODE_ID
    registry = R.get_registry(node_id)
    transport = T.build_transport(node_id)
    return RelayHub(node_id, registry=registry, transport=transport)


hub = build_hub()
