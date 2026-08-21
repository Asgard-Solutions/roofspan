"""ABC Supply integration — Phase 1 tests (OAuth/PKCE, token refresh, Account & Location APIs).

These exercise the ABC provider layer end-to-end against the in-process local mock ABC server
(integrations.abc_supply.mock_server) via an httpx ASGITransport — no real ABC calls, no DB.
Router/UI level flows are validated separately (curl + testing agent) against the running app.
"""
import asyncio

import httpx
import pytest

from integrations.abc_supply.config import AbcConfig
from integrations.abc_supply import auth as abc_auth
from integrations.abc_supply import accounts as abc_accounts
from integrations.abc_supply import locations as abc_locations
from integrations.abc_supply.client import AbcClient
from integrations.abc_supply.exceptions import AbcAuthError
from integrations.abc_supply.mock_server import mock_app


def _transport():
    return httpx.ASGITransport(app=mock_app)


def _cfg():
    return AbcConfig(
        environment="sandbox",
        client_id="test-client",
        client_secret="test-secret",
        redirect_uri="http://127.0.0.1:8001/api/integrations/abc/callback",
        webhook_public_url=None,
        oauth_base="http://abc-mock/oauth2",
        api_base="http://abc-mock",
        is_mock=True,
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------------- PKCE ----------------
def test_pkce_generate_and_verify():
    verifier, challenge = abc_auth.generate_pkce()
    assert 43 <= len(verifier) <= 128
    assert abc_auth.verify_pkce(verifier, challenge) is True
    assert abc_auth.verify_pkce("wrong-verifier", challenge) is False


async def _authorize_get_code(cfg, *, challenge, scope):
    params = abc_auth.build_authorize_params(
        client_id=cfg.client_id, redirect_uri=cfg.redirect_uri, state="xyz",
        code_challenge=challenge, scope=scope,
    )
    async with httpx.AsyncClient(transport=_transport(), base_url="http://abc-mock", follow_redirects=False) as c:
        r = await c.get("/oauth2/v1/authorize", params=params)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert "state=xyz" in loc
    code = loc.split("code=")[1].split("&")[0]
    return code


# ---------------- OAuth token flows ----------------
def test_authorization_code_flow_with_pkce():
    cfg = _cfg()

    async def scenario():
        verifier, challenge = abc_auth.generate_pkce()
        code = await _authorize_get_code(cfg, challenge=challenge, scope="account.read offline_access")
        tok = await abc_auth.exchange_code(cfg, code=code, code_verifier=verifier, transport=_transport())
        return tok

    tok = _run(scenario())
    assert tok["access_token"].startswith("mock-access-")
    assert tok["token_type"] == "Bearer"
    assert tok["expires_in"] == 1800
    assert "refresh_token" in tok  # offline_access requested


def test_authorization_code_flow_rejects_bad_pkce_verifier():
    cfg = _cfg()

    async def scenario():
        _, challenge = abc_auth.generate_pkce()
        code = await _authorize_get_code(cfg, challenge=challenge, scope="account.read offline_access")
        return await abc_auth.exchange_code(cfg, code=code, code_verifier="tampered-verifier", transport=_transport())

    with pytest.raises(AbcAuthError):
        _run(scenario())


def test_refresh_token_rotation():
    cfg = _cfg()

    async def scenario():
        verifier, challenge = abc_auth.generate_pkce()
        code = await _authorize_get_code(cfg, challenge=challenge, scope="account.read offline_access")
        tok = await abc_auth.exchange_code(cfg, code=code, code_verifier=verifier, transport=_transport())
        refreshed = await abc_auth.refresh_token(cfg, refresh=tok["refresh_token"], scope="account.read offline_access", transport=_transport())
        return tok, refreshed

    tok, refreshed = _run(scenario())
    assert refreshed["access_token"] != tok["access_token"]
    assert refreshed["refresh_token"] != tok["refresh_token"]  # rotated


def test_client_credentials_has_no_refresh_token():
    cfg = _cfg()
    tok = _run(abc_auth.client_credentials_token(cfg, scope="location.read product.read", transport=_transport()))
    assert tok["access_token"].startswith("mock-access-")
    assert "refresh_token" not in tok


# ---------------- API auth guard ----------------
def test_api_requires_bearer_token():
    cfg = _cfg()
    client = AbcClient(cfg, access_token=None, transport=_transport())
    with pytest.raises(AbcAuthError):
        _run(abc_accounts.list_ship_to_accounts(client))


# ---------------- Account API ----------------
def _connected_client():
    cfg = _cfg()

    async def get_token():
        verifier, challenge = abc_auth.generate_pkce()
        code = await _authorize_get_code(cfg, challenge=challenge, scope="account.read location.read offline_access")
        tok = await abc_auth.exchange_code(cfg, code=code, code_verifier=verifier, transport=_transport())
        return tok["access_token"]

    token = _run(get_token())
    return AbcClient(cfg, access_token=token, transport=_transport())


def test_list_ship_to_filters_retired_accounts():
    client = _connected_client()
    ship_tos = _run(abc_accounts.list_ship_to_accounts(client))
    numbers = [s["number"] for s in ship_tos]
    assert "1163698" in numbers           # active, has branches
    assert "9999999" not in numbers       # retired (empty branches[]) filtered out
    assert all(s.get("branches") for s in ship_tos)


def test_get_ship_to_and_contacts():
    client = _connected_client()
    st = _run(abc_accounts.get_ship_to(client, "1163698"))
    assert st["number"] == "1163698"
    assert len(st["branches"]) >= 1
    contacts = _run(abc_accounts.get_ship_to_contacts(client, "1163698"))
    assert "contacts" in contacts


# ---------------- Location API ----------------
def test_search_branches_by_state():
    client = _connected_client()
    branches = _run(abc_locations.search_branches(client, state="WI"))
    assert len(branches) == 2
    assert branches[0]["branch"]["number"] == "18"


def test_get_branch_by_number():
    client = _connected_client()
    b = _run(abc_locations.get_branch(client, "18"))
    assert b["branch"]["number"] == "18"
