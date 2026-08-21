"""Common async HTTP client for all ABC Supply resource APIs.

Responsibilities: bearer-token injection, timeouts, request IDs, bounded retries with
429 Retry-After handling, and normalization of non-2xx responses into AbcError. Write
operations (e.g. Place Order) are NOT retried here — the caller controls idempotency.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

import httpx

from .config import AbcConfig
from .exceptions import AbcTransportError, normalize_status

log = logging.getLogger("roofspan.abc")

_MAX_RETRIES = 3
_MAX_BACKOFF_SECONDS = 8.0
# Idempotent methods that are safe to auto-retry on 429/transient network errors.
_RETRYABLE_METHODS = {"GET", "HEAD"}


class AbcClient:
    def __init__(self, cfg: AbcConfig, *, access_token: str | None = None, transport=None):
        self.cfg = cfg
        self.access_token = access_token
        self._transport = transport  # httpx transport override (mock/tests)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        headers: dict | None = None,
        allow_retry: bool | None = None,
    ) -> httpx.Response:
        url = f"{self.cfg.api_base}{path}"
        req_headers = {"Accept": "application/json", "X-Request-Id": uuid.uuid4().hex}
        if self.access_token:
            req_headers["Authorization"] = f"Bearer {self.access_token}"
        if headers:
            req_headers.update(headers)

        retry = allow_retry if allow_retry is not None else (method.upper() in _RETRYABLE_METHODS)
        attempts = _MAX_RETRIES if retry else 1
        resp: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=25, transport=self._transport) as client:
                    resp = await client.request(method, url, json=json, params=params, headers=req_headers)
            except httpx.HTTPError as exc:
                if retry and attempt < attempts - 1:
                    await asyncio.sleep(min(2 ** attempt, _MAX_BACKOFF_SECONDS))
                    continue
                raise AbcTransportError("Could not reach ABC Supply.") from exc

            if resp.status_code == 429 and retry and attempt < attempts - 1:
                retry_after = resp.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else 2 ** attempt
                except ValueError:
                    wait = 2 ** attempt
                await asyncio.sleep(min(wait, _MAX_BACKOFF_SECONDS))
                continue
            return resp
        return resp  # type: ignore[return-value]

    async def get_json(self, path: str, *, params: dict | None = None) -> object:
        resp = await self.request("GET", path, params=params)
        return self._json_or_raise(resp)

    async def post_json(self, path: str, *, json: dict | None = None, allow_retry: bool = False) -> object:
        resp = await self.request("POST", path, json=json, allow_retry=allow_retry)
        return self._json_or_raise(resp)

    @staticmethod
    def _json_or_raise(resp: httpx.Response) -> object:
        if 200 <= resp.status_code < 300:
            if resp.status_code == 204 or not resp.content:
                return {}
            try:
                return resp.json()
            except ValueError as exc:
                raise normalize_status(502, "invalid JSON from ABC Supply") from exc
        raise normalize_status(resp.status_code, resp.text)
