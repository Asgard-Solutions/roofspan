"""ABC Supply integration — Phase 4 tests (Notification provider + webhook auth) against the local mock."""
import asyncio

import httpx

from integrations.abc_supply.config import AbcConfig
from integrations.abc_supply import notifications as abc_notify
from integrations.abc_supply.client import AbcClient
from integrations.abc_supply.mock_server import mock_app, _MOCK_WEBHOOKS
from routers.abc_webhooks import verify_order_update_event, verify_order_invoiced_event


def _client():
    cfg = AbcConfig(environment="sandbox", client_id="c", client_secret="s", redirect_uri="", webhook_public_url=None,
                    oauth_base="http://abc-mock/oauth2", api_base="http://abc-mock", is_mock=True)
    return AbcClient(cfg, access_token="mock-access-x", transport=httpx.ASGITransport(app=mock_app))


def _run(c):
    return asyncio.run(c)


def setup_function(_):
    _MOCK_WEBHOOKS.clear()


def test_register_and_reconcile_single_webhook():
    c = _client()
    reg = _run(abc_notify.register_webhook(c, url="https://relay/api/webhooks/abc/orders"))
    assert reg["id"].startswith("MOCK-WEBHOOK-") and reg["secret"].startswith("MOCK-WEBHOOK-SECRET-")
    assert reg["events"] == ["ORDER_UPDATE", "ORDER_INVOICED"]
    listed = _run(abc_notify.list_webhooks(c))
    assert len(listed) == 1  # single integration-level webhook
    # secrets are not returned on list
    assert "secret" not in listed[0]


def test_patch_and_delete_webhook():
    c = _client()
    reg = _run(abc_notify.register_webhook(c, url="https://relay/old"))
    patched = _run(abc_notify.patch_webhook(c, reg["id"], url="https://relay/new"))
    assert patched["url"] == "https://relay/new"
    _run(abc_notify.delete_webhook(c, reg["id"]))
    assert _run(abc_notify.list_webhooks(c)) == []


def test_webhook_limit_enforced():
    c = _client()
    for i in range(5):
        _run(abc_notify.register_webhook(c, url=f"https://relay/{i}", name=f"wh{i}"))
    import pytest
    from integrations.abc_supply.exceptions import AbcError
    with pytest.raises(AbcError):
        _run(abc_notify.register_webhook(c, url="https://relay/6", name="wh6"))


def test_order_update_secret_validation_constant_time():
    assert verify_order_update_event("SECRET-123", "SECRET-123") is True
    assert verify_order_update_event("Bearer SECRET-123", "SECRET-123") is True
    assert verify_order_update_event("WRONG", "SECRET-123") is False
    assert verify_order_update_event(None, "SECRET-123") is False
    assert verify_order_update_event("SECRET-123", "") is False


def test_order_invoiced_accepts_authorization_or_apikey():
    # NEEDS ABC SANDBOX VERIFICATION: real transport. We accept either, only if it matches the secret.
    assert verify_order_invoiced_event("SECRET-9", None, "SECRET-9") is True
    assert verify_order_invoiced_event(None, "SECRET-9", "SECRET-9") is True
    assert verify_order_invoiced_event(None, "WRONG", "SECRET-9") is False
    assert verify_order_invoiced_event(None, None, "SECRET-9") is False
