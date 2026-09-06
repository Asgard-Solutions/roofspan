"""Installation-side OUTBOUND relay tunnel client.

Runs on the customer Windows installation (here: in-container for proof). Opens an authenticated
outbound WebSocket to the relay (no inbound firewall/port-forwarding/VPN), then forwards routed
Mobile requests to the LOCAL FastAPI and streams responses back. Bounded reconnect/backoff.
"""
import asyncio
import logging
import os
import time

import httpx
import websockets

from licensing import reqsig
from relay import protocol as P

log = logging.getLogger("roofspan.relay.tunnel")


class InstallationTunnel:
    def __init__(self, relay_ws_url: str, installation_id: str, private_key, local_api_url: str,
                 outbox_token: str | None = None, outbox_poll_wait_ms: int = 20000,
                 accept_timeout: float = 10.0):
        self.url = relay_ws_url
        self.installation_id = installation_id
        self.priv = private_key
        self.local = local_api_url.rstrip("/")
        self._stop = False
        self.ready = asyncio.Event()
        # Office->Field outbox drain (only runs when a loopback connector token is provided).
        self.outbox_token = outbox_token
        self.outbox_poll_wait_ms = outbox_poll_wait_ms
        self.accept_timeout = accept_timeout
        self._send_lock = asyncio.Lock()             # serialize all writes on the single tunnel socket
        self._accept_waiters: dict[str, asyncio.Future] = {}  # event_id -> future resolved by broadcast_ack

    async def _ws_send(self, ws, frame: dict):
        async with self._send_lock:
            await ws.send(P.dumps(frame))

    async def _forward(self, ws, frame: dict):
        rid = frame["request_id"]
        try:
            path = frame.get("path", "/")
            q = frame.get("query", "")
            url = self.local + path + (("?" + q) if q else "")
            headers = dict(frame.get("headers", {}) or {})
            for h in ("host", "Host", "content-length", "Content-Length"):
                headers.pop(h, None)
            # Org-level map imagery: authorize tile-proxy fetches with a short-lived, office-signed
            # tile token instead of the salesperson's (expiring) access token. Keeps the MapTiler key
            # org-wide so a rep's expired session never blanks the map.
            if frame.get("method", "GET").upper() == "GET" and path.startswith("/api/map/tiles/"):
                try:
                    from core import create_tile_token
                    headers["Authorization"] = f"Bearer {create_tile_token()}"
                except Exception:
                    pass
            mp = frame.get("multipart")
            async with httpx.AsyncClient(timeout=60) as c:
                if mp and isinstance(mp, dict):
                    # Reconstruct multipart/form-data (photos/files) — httpx sets the boundary.
                    for h in ("content-type", "Content-Type"):
                        headers.pop(h, None)
                    f = mp.get("file") or {}
                    files = {f.get("field", "file"): (f.get("name", "upload"), P.b64d(f.get("b64", "")),
                                                       f.get("type", "application/octet-stream"))}
                    r = await c.request(frame.get("method", "POST"), url, headers=headers,
                                        data=mp.get("data", {}) or {}, files=files)
                else:
                    r = await c.request(frame.get("method", "GET"), url, headers=headers,
                                        content=P.b64d(frame.get("body", "")))
            out = {"type": P.T_RESPONSE, "request_id": rid, "status": r.status_code,
                   "headers": {"content-type": r.headers.get("content-type", "application/json")},
                   "body": P.b64e(r.content)}
        except Exception as e:  # noqa: BLE001
            out = {"type": P.T_RESPONSE, "request_id": rid, "status": 502,
                   "headers": {"content-type": "application/json"},
                   "body": P.b64e(b'{"detail":"local forward failed"}')}
            log.warning("tunnel forward error rid=%s: %s", rid, str(e)[:200])
        await self._ws_send(ws, out)

    # ---- Office -> Field durable outbox drain --------------------------------------------------
    async def _lease_outbox(self):
        url = self.local + "/api/relay/connector/outbox/lease"
        headers = {"X-Connector-Token": self.outbox_token or ""}
        body = {"wait_ms": self.outbox_poll_wait_ms, "lease_seconds": 30, "max_events": 64}
        async with httpx.AsyncClient(timeout=self.outbox_poll_wait_ms / 1000.0 + 15) as c:
            r = await c.post(url, headers=headers, json=body)
        if r.status_code != 200:
            raise RuntimeError(f"lease http {r.status_code}")
        return (r.json() or {}).get("events", [])

    async def _ack_outbox(self, event_ids):
        if not event_ids:
            return
        url = self.local + "/api/relay/connector/outbox/ack"
        headers = {"X-Connector-Token": self.outbox_token or ""}
        async with httpx.AsyncClient(timeout=20) as c:
            await c.post(url, headers=headers, json={"event_ids": event_ids})

    async def _outbox_pump(self, ws):
        """Long-poll the local outbox, forward each event up the tunnel, and ACK only AFTER the Relay
        sends its acceptance (broadcast_ack). Un-acked events are redelivered once their lease expires."""
        while not self._stop:
            try:
                events = await self._lease_outbox()
            except Exception as e:  # noqa: BLE001 - transient local error, retry
                if self._stop:
                    break
                await asyncio.sleep(2.0)
                continue
            acked = []
            for ev in events:
                event_id = ev.get("event_id")
                if not event_id:
                    continue
                loop = asyncio.get_event_loop()
                fut = loop.create_future()
                self._accept_waiters[event_id] = fut
                try:
                    await self._ws_send(ws, ev)  # ev already has type=measurement_changed + event_id
                    await asyncio.wait_for(fut, timeout=self.accept_timeout)
                    acked.append(event_id)  # Relay accepted responsibility -> safe to retire the row
                except Exception:  # noqa: BLE001 - no acceptance -> leave un-acked -> lease-expiry retry
                    pass
                finally:
                    self._accept_waiters.pop(event_id, None)
            try:
                await self._ack_outbox(acked)
            except Exception:  # noqa: BLE001 - ack ret/retry: rows just re-lease later, no data loss
                pass

    def _resolve_acceptance(self, frame: dict):
        event_id = frame.get("event_id")
        fut = self._accept_waiters.get(event_id) if event_id else None
        if fut is not None and not fut.done():
            fut.set_result(frame)

    async def run_once(self):
        async with websockets.connect(self.url, max_size=16 * 1024 * 1024) as ws:
            await ws.send(P.dumps({"type": P.T_HELLO, "installation_id": self.installation_id,
                                   "protocol": P.PROTOCOL_VERSION}))
            ch = P.loads(await ws.recv())
            if ch.get("type") != P.T_CHALLENGE:
                raise RuntimeError(f"expected challenge, got {ch}")
            nonce = ch["nonce"]
            ts = str(int(time.time()))
            sig = reqsig.sign_request(self.priv, installation_id=self.installation_id,
                                      timestamp=ts, nonce=nonce, body=nonce.encode())
            await ws.send(P.dumps({"type": P.T_AUTH, "timestamp": ts, "signature": sig}))
            ready = P.loads(await ws.recv())
            if ready.get("type") != P.T_READY:
                raise RuntimeError(f"relay auth failed: {ready}")
            self.ready.set()
            log.info("tunnel ready installation=%s", self.installation_id)
            pump = None
            if self.outbox_token:
                pump = asyncio.create_task(self._outbox_pump(ws))
            try:
                async for msg in ws:
                    frame = P.loads(msg)
                    t = frame.get("type")
                    if t == P.T_REQUEST:
                        asyncio.create_task(self._forward(ws, frame))
                    elif t == P.T_BROADCAST_ACK:
                        self._resolve_acceptance(frame)
                    elif t == P.T_PING:
                        await self._ws_send(ws, {"type": P.T_PONG, "ts": frame.get("ts")})
            finally:
                if pump is not None:
                    pump.cancel()
                    try:
                        await pump
                    except (asyncio.CancelledError, Exception):  # noqa: BLE001
                        pass
                for fut in list(self._accept_waiters.values()):
                    if not fut.done():
                        fut.cancel()
                self._accept_waiters.clear()

    async def run(self, max_backoff: float = 30.0):
        backoff = 1.0
        while not self._stop:
            try:
                await self.run_once()
                backoff = 1.0
            except Exception as e:  # noqa: BLE001
                self.ready.clear()
                if self._stop:
                    break
                log.warning("tunnel disconnected: %s (reconnect in %ss)", str(e)[:160], backoff)
                await asyncio.sleep(backoff)
                backoff = min(max_backoff, backoff * 2)

    def stop(self):
        self._stop = True
