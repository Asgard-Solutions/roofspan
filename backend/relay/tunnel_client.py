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
    def __init__(self, relay_ws_url: str, installation_id: str, private_key, local_api_url: str):
        self.url = relay_ws_url
        self.installation_id = installation_id
        self.priv = private_key
        self.local = local_api_url.rstrip("/")
        self._stop = False
        self.ready = asyncio.Event()

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
        await ws.send(P.dumps(out))

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
            async for msg in ws:
                frame = P.loads(msg)
                t = frame.get("type")
                if t == P.T_REQUEST:
                    asyncio.create_task(self._forward(ws, frame))
                elif t == P.T_PING:
                    await ws.send(P.dumps({"type": P.T_PONG, "ts": frame.get("ts")}))

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
