"""Runtime contract for the packaged RelayWorker outbox bootstrap."""
from __future__ import annotations

import asyncio
import sys
import threading
import types
from pathlib import Path

import pytest

WINBUILD = Path(__file__).resolve().parents[1] / "winbuild"
sys.path.insert(0, str(WINBUILD))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import relay_entry


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


def test_connector_identity_requires_a_nonempty_outbox_token():
    with pytest.raises(RuntimeError, match="incomplete"):
        relay_entry.parse_connector_identity({
            "installation_id": "11111111-1111-1111-1111-111111111111",
            "relay_ws_url": "wss://relay.roofspan.io/api/relay/installation",
        })


def test_real_relay_worker_passes_connector_token_to_installation_tunnel(monkeypatch):
    constructed = []
    ready = threading.Event()

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "installation_id": "11111111-1111-1111-1111-111111111111",
                "relay_ws_url": "wss://relay.roofspan.io/api/relay/installation",
                "connector_token": "loopback-outbox-secret",
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return FakeResponse()

    class FakeTunnel:
        def __init__(self, *args, **kwargs):
            constructed.append((args, kwargs))
            ready.set()

        async def run(self):
            await asyncio.Event().wait()

        def stop(self):
            pass

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.AsyncClient = FakeAsyncClient
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    import licensing
    fake_identity = types.ModuleType("licensing.identity")
    fake_identity.get_or_create_identity = lambda: (object(), "public")
    monkeypatch.setitem(sys.modules, "licensing.identity", fake_identity)
    monkeypatch.setattr(licensing, "identity", fake_identity, raising=False)

    import relay
    fake_tunnel_module = types.ModuleType("relay.tunnel_client")
    fake_tunnel_module.InstallationTunnel = FakeTunnel
    monkeypatch.setitem(sys.modules, "relay.tunnel_client", fake_tunnel_module)
    monkeypatch.setattr(relay, "tunnel_client", fake_tunnel_module, raising=False)

    worker = relay_entry.RelayWorker(_Logger())
    worker.start()
    try:
        assert ready.wait(3), "RelayWorker never constructed InstallationTunnel"
        assert constructed
        _args, kwargs = constructed[0]
        assert kwargs["outbox_token"] == "loopback-outbox-secret"
    finally:
        worker.stop()
        worker.wait(3)
