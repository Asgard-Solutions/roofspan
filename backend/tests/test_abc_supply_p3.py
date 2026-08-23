"""ABC Supply integration — Phase 3 tests (Order provider) against the local mock."""
import asyncio

import httpx
import pytest

from integrations.abc_supply.config import AbcConfig
from integrations.abc_supply import auth as abc_auth
from integrations.abc_supply import orders as abc_orders
from integrations.abc_supply.client import AbcClient
from integrations.abc_supply.exceptions import AbcError
from integrations.abc_supply.mock_server import mock_app, _MOCK_ORDERS, _MOCK_BY_REQID


def _transport():
    return httpx.ASGITransport(app=mock_app)


def _cfg():
    return AbcConfig(environment="sandbox", client_id="c", client_secret="s",
                     redirect_uri="http://127.0.0.1:8001/api/integrations/abc/callback", webhook_public_url=None,
                     oauth_base="http://abc-mock/oauth2", api_base="http://abc-mock", is_mock=True)


def _run(coro):
    return asyncio.run(coro)


def _client():
    return AbcClient(_cfg(), access_token="mock-access-test", transport=_transport())


def _order(req_id, item="MOCK-SHINGLE-ARCH-WW", po="PO-TEST"):
    return {"requestId": req_id, "purchaseOrder": po, "branchNumber": "18", "deliveryService": "OTG",
            "typeCode": "SO", "currency": "USD", "shipTo": {"number": "1163698", "name": po},
            "lines": [abc_orders.build_order_line(line_id=1, item_number=item, item_description="X",
                                                  quantity=5, uom="SQ", unit_price=135.36)]}


def setup_function(_):
    _MOCK_ORDERS.clear()
    _MOCK_BY_REQID.clear()


def test_place_order_success():
    res = _run(abc_orders.place_order(_client(), _order("req-1")))
    assert res["ok"] and res["confirmation_number"].startswith("MOCK-CONF-")


def test_place_order_idempotent_same_request_id():
    c = _client()
    r1 = _run(abc_orders.place_order(c, _order("req-dup")))
    r2 = _run(abc_orders.place_order(c, _order("req-dup")))
    assert r1["confirmation_number"] == r2["confirmation_number"]
    assert len(_MOCK_ORDERS) == 1  # no duplicate order created


def test_place_order_rejected():
    # 400 rejection surfaces as AbcError (router maps this to a 'failed' submission).
    with pytest.raises(AbcError) as ei:
        _run(abc_orders.place_order(_client(), _order("req-rej", item="MOCK-REJECT")))
    assert ei.value.status == 400
    assert len(_MOCK_ORDERS) == 0  # rejected order is NOT recorded


def test_place_order_timeout_raises_but_records():
    # MOCK-TIMEOUT returns 504 (ambiguous). The order IS recorded so it can be reconciled.
    with pytest.raises(AbcError) as ei:
        _run(abc_orders.place_order(_client(), _order("req-to", item="MOCK-TIMEOUT")))
    assert ei.value.status in (502, 503, 504)
    assert len(_MOCK_ORDERS) == 1


def test_get_order_by_confirmation_and_history():
    c = _client()
    res = _run(abc_orders.place_order(c, _order("req-h", po="PO-HIST")))
    conf = res["confirmation_number"]
    detail = _run(abc_orders.get_order_by_confirmation(c, conf))
    assert detail["confirmation_number"] == conf
    assert detail["normalized_status"] == "processing"
    # v2 order history: {pagination, items}; items carry orderNumber (not purchaseOrder). Get each
    # order's detail to strong-match the RoofSpan purchaseOrder identifier.
    hist = _run(abc_orders.get_order_history(c))
    assert isinstance(hist, dict) and "pagination" in hist and "items" in hist, hist
    assert hist["items"], "expected at least one order in history"
    found = False
    for it in hist["items"]:
        d = _run(abc_orders.get_order_by_number(c, str(it["orderNumber"])))
        if d.get("purchase_order") == "PO-HIST":
            found = True
            break
    assert found, "PO-HIST not found via order history + detail"


def test_templates():
    res = _run(abc_orders.list_templates(_client()))
    assert isinstance(res, dict) and "templates" in res and "pagination" in res, res
    tmpls = res["templates"]
    assert tmpls and tmpls[0].get("templateId")
    t = _run(abc_orders.get_template(_client(), tmpls[0]["templateId"]))
    # get_template returns the raw ABC detail; normalize_template gives the stable RoofSpan shape.
    norm = abc_orders.normalize_template(t)
    assert norm["lines"] and norm["lines"][0]["item_number"]


def test_normalize_status():
    assert abc_orders.normalize_status("Invoiced") == "invoiced"
    assert abc_orders.normalize_status("Submitted") == "processing"
    assert abc_orders.normalize_status("Delivered") == "delivered"
