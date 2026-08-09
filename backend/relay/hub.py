"""In-memory relay routing hub. Holds live installation tunnels and correlates Mobile
request/response by request_id. Nothing is persisted — bodies live only in transit."""
import asyncio
import logging

from relay import protocol as P

log = logging.getLogger("roofspan.relay")


class RelayUnavailable(Exception):
    """No live installation tunnel for the target installation."""


class InstallationConn:
    def __init__(self, installation_id: str, ws):
        self.installation_id = installation_id
        self.ws = ws
        self.pending: dict[str, asyncio.Future] = {}
        self.send_lock = asyncio.Lock()


class RelayHub:
    def __init__(self):
        self._installs: dict[str, InstallationConn] = {}

    def register(self, conn: InstallationConn) -> None:
        prev = self._installs.get(conn.installation_id)
        if prev is not None:
            # Replace a stale tunnel: fail its in-flight requests so callers don't hang.
            for fut in list(prev.pending.values()):
                if not fut.done():
                    fut.set_exception(RelayUnavailable("installation tunnel replaced"))
        self._installs[conn.installation_id] = conn
        log.info("relay: installation tunnel connected id=%s (tunnels=%d)", conn.installation_id, len(self._installs))

    def unregister(self, installation_id: str, conn: InstallationConn) -> None:
        if self._installs.get(installation_id) is conn:
            del self._installs[installation_id]
            for fut in list(conn.pending.values()):
                if not fut.done():
                    fut.set_exception(RelayUnavailable("installation tunnel disconnected"))
            log.info("relay: installation tunnel disconnected id=%s (tunnels=%d)", installation_id, len(self._installs))

    def is_connected(self, installation_id: str) -> bool:
        return installation_id in self._installs

    def resolve(self, installation_id: str, request_id: str, response: dict) -> None:
        conn = self._installs.get(installation_id)
        if conn is None:
            return
        fut = conn.pending.get(request_id)
        if fut is not None and not fut.done():
            fut.set_result(response)

    async def route(self, installation_id: str, request_frame: dict, timeout: float) -> dict:
        conn = self._installs.get(installation_id)
        if conn is None:
            raise RelayUnavailable("installation tunnel not connected")
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


hub = RelayHub()
