"""Focused tests for the ZIP/postal geocoding proxy (network-free; httpx is faked).

Verifies the Nominatim boundingbox -> [lng,lat] bbox transform, the [lon,lat] center, and error handling
(empty input -> 400, no result -> 404). Only the ZIP string is forwarded upstream.

Run: cd /app/backend && python -m pytest tests/test_geocode_zip.py -o addopts='' -q
"""
import asyncio
import pytest
from fastapi import HTTPException

from routers import settings as settings_router


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


class _Client:
    captured = {}

    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        _Client.captured = {"url": url, "params": params, "headers": headers}
        return _Resp(self._status, self._payload)


def _fake_httpx(monkeypatch, payload, status=200):
    monkeypatch.setattr(settings_router.httpx, "AsyncClient", lambda *a, **k: _Client(payload, status))


def _run(coro):
    return asyncio.run(coro)


def test_geocode_zip_transforms_bbox_and_center(monkeypatch):
    payload = [{"boundingbox": ["30.2250094", "30.31523", "-97.7949873", "-97.6910466"],
                "lat": "30.2701199", "lon": "-97.7430163",
                "display_name": "78701, Austin, Travis County, Texas, United States"}]
    _fake_httpx(monkeypatch, payload)
    out = _run(settings_router.geocode_zip(zip="78701", country="us", user=object()))
    # center is [lon, lat]
    assert out["center"] == [-97.7430163, 30.2701199]
    # Nominatim boundingbox [south, north, west, east] -> [[west, south], [east, north]]
    assert out["bbox"] == [[-97.7949873, 30.2250094], [-97.6910466, 30.31523]]
    assert "78701" in out["display_name"]
    # only the ZIP is forwarded upstream (+ country); a proper User-Agent is set (Nominatim policy)
    assert _Client.captured["params"]["postalcode"] == "78701"
    assert _Client.captured["params"]["countrycodes"] == "us"
    assert "RoofSpan" in _Client.captured["headers"]["User-Agent"]


def test_geocode_zip_not_found_returns_404(monkeypatch):
    _fake_httpx(monkeypatch, [])
    with pytest.raises(HTTPException) as ei:
        _run(settings_router.geocode_zip(zip="99999999", country="us", user=object()))
    assert ei.value.status_code == 404


def test_geocode_zip_empty_returns_400():
    with pytest.raises(HTTPException) as ei:
        _run(settings_router.geocode_zip(zip="   ", country="us", user=object()))
    assert ei.value.status_code == 400


def test_geocode_zip_upstream_error_returns_502(monkeypatch):
    _fake_httpx(monkeypatch, [], status=500)
    with pytest.raises(HTTPException) as ei:
        _run(settings_router.geocode_zip(zip="78701", country="us", user=object()))
    assert ei.value.status_code == 502
