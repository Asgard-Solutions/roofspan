"""HTTP-level verification that the ABC mock server uses the shared validate_place_order
contract and thus rejects historical wrong shapes (WCL/OTB, bare comments, dates.deliveryAppointmentTime,
bad appointment codes, ST-without-fromTime, TR-without-toTime, instructions>255, string line comment).
Also verifies a documented valid order returns 200 + MOCK-CONF-*.

Uses the public REACT_APP_BACKEND_URL and the ABC mock OAuth flow.
"""
from __future__ import annotations

import copy
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
ORDERS_URL = f"{BASE_URL}/api/abc-mock/api/order/v2/orders"
TOKEN_URL = f"{BASE_URL}/api/abc-mock/oauth2/v1/token"


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials", "client_id": "test", "client_secret": "test"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _valid_order(**overrides) -> dict:
    order = {
        "requestId": f"req-{uuid.uuid4().hex[:12]}",
        "purchaseOrder": f"PO-{uuid.uuid4().hex[:8]}",
        "branchNumber": "18",
        "deliveryService": "OTG",
        "typeCode": "SO",
        "currency": "USD",
        "shipTo": {"number": "1163698", "name": "PO test"},
        "lines": [{
            "id": "1",
            "itemNumber": "MOCK-SHINGLE-ARCH-WW",
            "itemDescription": "Architectural Shingle",
            "orderedQty": {"value": 30, "uom": "SQ"},
            "unitPrice": {"value": 34.5, "uom": "SQ"},
        }],
    }
    order.update(overrides)
    return order


def _post(order: dict, headers: dict):
    return requests.post(ORDERS_URL, json=[order], headers=headers, timeout=20)


def test_valid_documented_order_returns_mock_conf(headers):
    r = _post(_valid_order(), headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # Batch envelope: {"request": {...}, "orders": [{"confirmationNumber": "MOCK-CONF-*"}]}
    orders = body.get("orders") if isinstance(body, dict) else body
    assert orders, f"no orders in response: {body}"
    conf = orders[0].get("confirmationNumber") or ""
    assert "MOCK-CONF" in str(conf), f"expected MOCK-CONF-* got: {orders[0]}"


@pytest.mark.parametrize("bad_ds", ["WCL", "OTB", "ZZZ"])
def test_reject_unsupported_delivery_service(headers, bad_ds):
    r = _post(_valid_order(deliveryService=bad_ds), headers)
    assert r.status_code == 400, r.text
    assert "deliveryService" in r.text or "delivery" in r.text.lower()


def test_reject_bare_comments_string(headers):
    r = _post(_valid_order(comments="legacy string"), headers)
    assert r.status_code == 400
    assert "orderComments" in r.text


def test_reject_line_comment_as_string(headers):
    o = _valid_order()
    o["lines"][0]["comments"] = "legacy bare"
    r = _post(o, headers)
    assert r.status_code == 400
    assert "line comment" in r.text.lower()


def test_reject_line_comment_as_list(headers):
    o = _valid_order()
    o["lines"][0]["comments"] = [{"code": "D", "description": "should be object"}]
    r = _post(o, headers)
    assert r.status_code == 400


def test_reject_dates_delivery_appointment_time(headers):
    r = _post(_valid_order(dates={"deliveryAppointmentTime": "09:00-12:00"}), headers)
    assert r.status_code == 400
    assert "deliveryAppointment" in r.text


def test_reject_bad_appointment_type_code(headers):
    r = _post(_valid_order(deliveryAppointment={"instructionsTypeCode": "ZZ"}), headers)
    assert r.status_code == 400
    assert "instructionsTypeCode" in r.text


def test_reject_ST_without_fromtime(headers):
    r = _post(_valid_order(deliveryAppointment={"instructionsTypeCode": "ST"}), headers)
    assert r.status_code == 400
    assert "fromTime" in r.text


def test_reject_TR_without_totime(headers):
    r = _post(_valid_order(
        deliveryAppointment={"instructionsTypeCode": "TR", "fromTime": "09:00"}), headers)
    assert r.status_code == 400
    assert "toTime" in r.text


def test_reject_instructions_over_255(headers):
    r = _post(_valid_order(
        deliveryAppointment={"instructionsTypeCode": "AT", "instructions": "x" * 256}), headers)
    assert r.status_code == 400
    assert "255" in r.text


def test_reject_missing_ship_to_number(headers):
    o = _valid_order()
    o["shipTo"] = {}
    r = _post(o, headers)
    assert r.status_code == 400
    assert "shipTo" in r.text


def test_reject_po_over_20_chars(headers):
    r = _post(_valid_order(purchaseOrder="X" * 21), headers)
    assert r.status_code == 400
    assert "purchaseOrder" in r.text or "20" in r.text
