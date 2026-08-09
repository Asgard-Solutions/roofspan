"""C0 hardening: SubscriptionGuardMiddleware fail-SAFE behavior on internal errors.

Directly exercises the middleware dispatch with a stubbed effective-state provider so we can force an
unexpected internal licensing error and assert the guard blocks protected routes (503) while leaving
the recovery allowlist reachable.
"""
import json
from types import SimpleNamespace

import pytest

from licensing import service
from licensing.middleware import SubscriptionGuardMiddleware


def _req(path, method="GET"):
    return SimpleNamespace(url=SimpleNamespace(path=path), method=method)


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _passthrough(request):
    return SimpleNamespace(status_code=200, _passed=True)


def _mw():
    return SubscriptionGuardMiddleware(app=lambda: None)


@pytest.mark.anyio
async def test_guard_fails_safe_on_internal_error(monkeypatch):
    async def boom():
        raise RuntimeError("simulated internal licensing failure")
    monkeypatch.setattr(service, "effective_state_cached", boom)
    resp = await _mw().dispatch(_req("/api/leads"), _passthrough)
    assert resp.status_code == 503
    body = json.loads(bytes(resp.body))
    assert body["code"] == "licensing_error"
    assert not getattr(resp, "_passed", False)  # protected route was NOT allowed through


@pytest.mark.anyio
async def test_guard_allowlist_reachable_even_on_internal_error(monkeypatch):
    async def boom():
        raise RuntimeError("simulated internal licensing failure")
    monkeypatch.setattr(service, "effective_state_cached", boom)
    # auth/subscription/license/billing are not guarded -> pass through regardless of guard errors
    for path in ("/api/auth/login", "/api/subscription", "/api/license/status", "/api/billing/portal-url"):
        resp = await _mw().dispatch(_req(path, method="POST" if "auth" in path else "GET"), _passthrough)
        assert getattr(resp, "_passed", False), path


@pytest.mark.anyio
async def test_guard_blocks_when_suspended(monkeypatch):
    async def suspended():
        return "SUSPENDED"
    monkeypatch.setattr(service, "effective_state_cached", suspended)
    resp = await _mw().dispatch(_req("/api/leads"), _passthrough)
    assert resp.status_code == 403
    assert json.loads(bytes(resp.body))["code"] == "subscription_inactive"


@pytest.mark.anyio
async def test_guard_allows_when_active(monkeypatch):
    async def active():
        return "ACTIVE"
    monkeypatch.setattr(service, "effective_state_cached", active)
    resp = await _mw().dispatch(_req("/api/leads"), _passthrough)
    assert getattr(resp, "_passed", False)
