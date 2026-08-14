"""Network-free test for the RentCast direct-ZIP pull client (fetch_rentcast_by_zip)."""
import asyncio
import rentcast


class _Resp:
    def __init__(self, batch):
        self._b = batch

    def raise_for_status(self):
        pass

    def json(self):
        return self._b


class _Client:
    calls = []

    def __init__(self, pages):
        self._pages = pages
        self._i = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, path, params=None, headers=None):
        _Client.calls.append({"path": path, "params": params, "headers": headers})
        batch = self._pages[self._i] if self._i < len(self._pages) else []
        self._i += 1
        return _Resp(batch)


def test_fetch_rentcast_by_zip_uses_zipcode_and_api_key(monkeypatch):
    _Client.calls = []
    page = [{"id": f"p{i}", "zipCode": "78701", "latitude": 30.27, "longitude": -97.74} for i in range(3)]
    monkeypatch.setattr(rentcast.httpx, "AsyncClient", lambda *a, **k: _Client([page]))
    out = asyncio.run(rentcast.fetch_rentcast_by_zip("KEY123", "78701", max_records=500))
    assert len(out) == 3
    c = _Client.calls[0]
    assert c["path"] == "/properties"
    assert c["params"]["zipCode"] == "78701"          # native ZIP filter (exact), not lat/lng/radius
    assert "radius" not in c["params"] and "latitude" not in c["params"]
    assert c["headers"]["X-Api-Key"] == "KEY123"      # auth header
    # a single short page ends pagination (no extra request)
    assert len(_Client.calls) == 1


def test_fetch_rentcast_by_zip_paginates_until_max(monkeypatch):
    _Client.calls = []
    full = [{"id": f"p{i}", "latitude": 1, "longitude": 1} for i in range(500)]
    monkeypatch.setattr(rentcast.httpx, "AsyncClient", lambda *a, **k: _Client([full, full[:10]]))
    out = asyncio.run(rentcast.fetch_rentcast_by_zip("K", "90210", max_records=510))
    assert len(out) == 510
    assert _Client.calls[1]["params"]["offset"] == 500   # second page requested at offset 500
