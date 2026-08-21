"""ABC Supply integration — Phase 2 tests (Product API + Pricing API) against the local mock."""
import asyncio

import httpx

from integrations.abc_supply.config import AbcConfig
from integrations.abc_supply import auth as abc_auth
from integrations.abc_supply import products as abc_products
from integrations.abc_supply import pricing as abc_pricing
from integrations.abc_supply.client import AbcClient
from integrations.abc_supply.mock_server import mock_app


def _transport():
    return httpx.ASGITransport(app=mock_app)


def _cfg():
    return AbcConfig(environment="sandbox", client_id="test-client", client_secret="test-secret",
                     redirect_uri="http://127.0.0.1:8001/api/integrations/abc/callback", webhook_public_url=None,
                     oauth_base="http://abc-mock/oauth2", api_base="http://abc-mock", is_mock=True)


def _run(coro):
    return asyncio.run(coro)


def _client():
    cfg = _cfg()

    async def tok():
        verifier, challenge = abc_auth.generate_pkce()
        params = abc_auth.build_authorize_params(client_id=cfg.client_id, redirect_uri=cfg.redirect_uri, state="s",
                                                 code_challenge=challenge, scope="product.read pricing.read offline_access")
        async with httpx.AsyncClient(transport=_transport(), base_url="http://abc-mock", follow_redirects=False) as c:
            r = await c.get("/oauth2/v1/authorize", params=params)
        code = r.headers["location"].split("code=")[1].split("&")[0]
        t = await abc_auth.exchange_code(cfg, code=code, code_verifier=verifier, transport=_transport())
        return t["access_token"]

    return AbcClient(cfg, access_token=_run(tok()), transport=_transport())


# ---------------- Product ----------------
def test_search_by_description():
    c = _client()
    data = _run(abc_products.search_items(c, query="Mock", branch_number="18"))
    nums = [i["itemNumber"] for i in data["items"]]
    assert "MOCK-SHINGLE-ARCH-WW" in nums and len(nums) >= 3


def test_search_by_item_number_and_details():
    c = _client()
    item = _run(abc_products.get_item(c, "MOCK-SHINGLE-ARCH-WW"))
    assert item and item["itemNumber"] == "MOCK-SHINGLE-ARCH-WW"
    assert abc_products.item_available_at_branch(item, "18") is True


def test_branch_availability_true_false():
    c = _client()
    # Underlayment is available at 18 but not 409
    at18 = _run(abc_products.search_items(c, query="Underlayment", branch_number="18"))
    at409 = _run(abc_products.search_items(c, query="Underlayment", branch_number="409"))
    assert len(at18["items"]) == 1
    assert len(at409["items"]) == 0


def test_dimensional_flag():
    c = _client()
    item = _run(abc_products.get_item(c, "MOCK-DRIP-EDGE-DIM"))
    assert item["isDimensional"] is True


# ---------------- Pricing ----------------
def _price(c, lines):
    return _run(abc_pricing.price_items(c, ship_to_number="1163698", branch_number="18", lines=lines))


def test_standard_price():
    c = _client()
    res = _price(c, [abc_pricing.build_line(line_id="1", item_number="MOCK-SHINGLE-ARCH-WW", quantity=10, uom="SQ")])
    assert res[0]["price_status"] == "priced" and res[0]["unit_price"] == 135.36


def test_zero_price_is_unavailable_not_free():
    c = _client()
    res = _price(c, [abc_pricing.build_line(line_id="1", item_number="MOCK-RIDGE-CAP-NOPRICE", quantity=5, uom="BD")])
    assert res[0]["unit_price"] == 0.0
    assert res[0]["price_status"] == "unavailable"  # $0 must NOT be treated as free/priced


def test_dimensional_requires_length():
    c = _client()
    without = _price(c, [abc_pricing.build_line(line_id="1", item_number="MOCK-DRIP-EDGE-DIM", quantity=4, uom="PC")])
    assert without[0]["price_status"] == "unavailable"
    with_len = _price(c, [abc_pricing.build_line(line_id="1", item_number="MOCK-DRIP-EDGE-DIM", quantity=4, uom="PC", length_value=10, length_uom="ft")])
    assert with_len[0]["price_status"] == "priced" and with_len[0]["unit_price"] == 65.0


def test_invalid_item_priced_as_unavailable():
    c = _client()
    res = _price(c, [abc_pricing.build_line(line_id="1", item_number="NOPE-XYZ", quantity=1)])
    assert res[0]["price_status"] == "unavailable"


def test_multiple_lines_mixed():
    c = _client()
    res = _price(c, [
        abc_pricing.build_line(line_id="1", item_number="MOCK-SHINGLE-ARCH-WW", quantity=10, uom="SQ"),
        abc_pricing.build_line(line_id="2", item_number="MOCK-RIDGE-CAP-NOPRICE", quantity=5, uom="BD"),
    ])
    statuses = {l["item_number"]: l["price_status"] for l in res}
    assert statuses["MOCK-SHINGLE-ARCH-WW"] == "priced"
    assert statuses["MOCK-RIDGE-CAP-NOPRICE"] == "unavailable"
