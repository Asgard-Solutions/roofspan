"""Focused tests for the ZIP/postal geocoding endpoint (network-free; httpx is faked).

Covers: authoritative US Census ZCTA polygon path (real ZIP boundary), the Nominatim fallback when no
Census polygon exists, bbox/center derivation, and error handling. Only the ZIP string is forwarded.

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


class _Router:
    """Fake httpx.AsyncClient that routes GETs by URL to a Nominatim or Census payload."""
    captured = []

    def __init__(self, nomi, census, nomi_status=200, census_status=200):
        self._nomi, self._census = nomi, census
        self._ns, self._cs = nomi_status, census_status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        _Router.captured.append({"url": url, "params": params, "headers": headers})
        if "tigerweb.geo.census.gov" in url:
            return _Resp(self._cs, self._census)
        return _Resp(self._ns, self._nomi)


def _fake(monkeypatch, nomi, census, nomi_status=200, census_status=200):
    _Router.captured = []
    monkeypatch.setattr(settings_router.httpx, "AsyncClient",
                        lambda *a, **k: _Router(nomi, census, nomi_status, census_status))


def _run(coro):
    return asyncio.run(coro)


_NOMI_78701 = [{"boundingbox": ["30.22", "30.31", "-97.79", "-97.69"], "lat": "30.27", "lon": "-97.74",
                "display_name": "78701, Austin, Travis County, Texas, United States",
                "geojson": {"type": "Point", "coordinates": [-97.74, 30.27]}}]
# A tiny square ZCTA polygon (stand-in for the real 264-vertex Census boundary)
_CENSUS_POLY = {"features": [{"type": "Feature", "properties": {"ZCTA5": "78701"},
                "geometry": {"type": "Polygon", "coordinates": [[[-97.75, 30.25], [-97.73, 30.25],
                             [-97.73, 30.28], [-97.75, 30.28], [-97.75, 30.25]]]}}]}


def test_us_zip_returns_authoritative_census_polygon(monkeypatch):
    _fake(monkeypatch, _NOMI_78701, _CENSUS_POLY)
    out = _run(settings_router.geocode_zip(zip="78701", country="us", user=object()))
    assert out["geometry"]["type"] == "Polygon"                      # REAL boundary, not a Point
    assert out["geometry"]["coordinates"][0][0] == [-97.75, 30.25]
    # bbox derived from the polygon extent (tight), center is its midpoint
    assert out["bbox"] == [[-97.75, 30.25], [-97.73, 30.28]]
    assert out["center"] == pytest.approx([-97.74, 30.265])
    assert "Austin" in out["display_name"]                           # friendly name from Nominatim
    # both upstreams were queried and only the ZIP was forwarded
    assert any("census" in c["url"] for c in _Router.captured)
    census_call = next(c for c in _Router.captured if "census" in c["url"])
    assert census_call["params"]["where"] == "ZCTA5='78701'"


def test_us_zip_without_census_polygon_falls_back_to_nominatim(monkeypatch):
    _fake(monkeypatch, _NOMI_78701, {"features": []})               # Census has no ZCTA
    out = _run(settings_router.geocode_zip(zip="78701", country="us", user=object()))
    assert out["geometry"]["type"] == "Point"                        # fell back to Nominatim geometry
    assert out["bbox"] == [[-97.79, 30.22], [-97.69, 30.31]]         # Nominatim bbox
    assert out["center"] == [-97.74, 30.27]


def test_non_us_skips_census_and_uses_nominatim(monkeypatch):
    _fake(monkeypatch, _NOMI_78701, _CENSUS_POLY)
    _run(settings_router.geocode_zip(zip="SW1A", country="gb", user=object()))
    assert not any("census" in c["url"] for c in _Router.captured)   # Census is US-only


def test_not_found_returns_404(monkeypatch):
    _fake(monkeypatch, [], {"features": []})
    with pytest.raises(HTTPException) as ei:
        _run(settings_router.geocode_zip(zip="99999", country="us", user=object()))
    assert ei.value.status_code == 404


def test_empty_returns_400():
    with pytest.raises(HTTPException) as ei:
        _run(settings_router.geocode_zip(zip="   ", country="us", user=object()))
    assert ei.value.status_code == 400


def test_nominatim_upstream_error_returns_502(monkeypatch):
    _fake(monkeypatch, [], {"features": []}, nomi_status=500)
    with pytest.raises(HTTPException) as ei:
        _run(settings_router.geocode_zip(zip="78701", country="us", user=object()))
    assert ei.value.status_code == 502
