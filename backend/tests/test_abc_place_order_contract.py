"""Contract tests for the shared, versioned ABC Place Order contract
(integrations/abc_supply/place_order_contract.validate_place_order).

These fixtures are built directly from ABC's documented Place Order examples
(https://apidocs.abcsupply.com/place-orders/) so a drift between RoofSpan's assumptions and ABC's
published schema is caught here. The SAME validator backs both production payload construction and the
ABC mock server, so they cannot diverge.
"""
from integrations.abc_supply.place_order_contract import (
    validate_place_order, CONTRACT_VERSION, ORDER_COMMENT_CODES, APPOINTMENT_TYPE_CODES,
)


def _doc_order(**overrides):
    """A valid order shaped like ABC's documented Place Order example."""
    order = {
        "requestId": "req-123",
        "purchaseOrder": "PO-1001",
        "branchNumber": "18",
        "deliveryService": "OTG",
        "typeCode": "SO",
        "currency": "USD",
        "shipTo": {"number": "1163698", "name": "PO-1001"},
        "lines": [{
            "id": "1", "itemNumber": "MOCK-SHINGLE-ARCH-WW", "itemDescription": "Architectural Shingle",
            "orderedQty": {"value": 30, "uom": "SQ"}, "unitPrice": {"value": 34.5, "uom": "SQ"},
        }],
    }
    order.update(overrides)
    return order


def test_contract_version_present():
    assert CONTRACT_VERSION
    assert ORDER_COMMENT_CODES == {"H", "F", "D"}
    assert APPOINTMENT_TYPE_CODES == {"AT", "AM", "PM", "FS", "ST", "TR"}


def test_documented_minimal_order_valid():
    assert validate_place_order(_doc_order()) == []


def test_documented_order_with_dates_and_TR_appointment_valid():
    # ABC's documented example: date under dates.deliveryRequestedFor, window under deliveryAppointment.
    order = _doc_order(
        dates={"deliveryRequestedFor": "2030-03-05"},
        deliveryAppointment={"instructionsTypeCode": "TR", "instructions": "Please leave in driveway",
                             "fromTime": "10:00", "toTime": "11:00", "timeZoneCode": "CT"},
    )
    assert validate_place_order(order) == []


def test_documented_order_comments_and_line_comments_valid():
    order = _doc_order(orderComments=[{"code": "H", "description": "Header note"},
                                      {"code": "F", "description": "Footer note"}])
    order["lines"][0]["comments"] = {"code": "D", "description": "Detail note"}
    assert validate_place_order(order) == []


# --- historical WRONG shapes must be rejected ---

def test_reject_bare_comments_string():
    errs = validate_place_order(_doc_order(comments="legacy string"))
    assert errs and "orderComments" in errs[0]


def test_reject_line_comment_as_string():
    order = _doc_order()
    order["lines"][0]["comments"] = "legacy bare string"
    errs = validate_place_order(order)
    assert errs and "line comment" in errs[0].lower()


def test_reject_line_comment_as_list():
    order = _doc_order()
    order["lines"][0]["comments"] = [{"code": "D", "description": "should be object"}]
    assert validate_place_order(order)


def test_reject_dates_delivery_appointment_time():
    errs = validate_place_order(_doc_order(dates={"deliveryAppointmentTime": "09:00-12:00"}))
    assert errs and "deliveryAppointment" in errs[0]


def test_reject_unsupported_delivery_service():
    for bad in ("OTB", "WCL", "ZZZ"):
        errs = validate_place_order(_doc_order(deliveryService=bad))
        assert errs, bad


def test_reject_appointment_bad_code():
    errs = validate_place_order(_doc_order(deliveryAppointment={"instructionsTypeCode": "ZZ"}))
    assert errs and "instructionsTypeCode" in errs[0]


def test_reject_ST_without_fromtime():
    errs = validate_place_order(_doc_order(deliveryAppointment={"instructionsTypeCode": "ST"}))
    assert errs and "fromTime" in errs[0]


def test_reject_TR_without_totime():
    errs = validate_place_order(_doc_order(
        deliveryAppointment={"instructionsTypeCode": "TR", "fromTime": "09:00"}))
    assert errs and "toTime" in errs[0]


def test_reject_instructions_over_255():
    errs = validate_place_order(_doc_order(
        deliveryAppointment={"instructionsTypeCode": "AT", "instructions": "x" * 256}))
    assert errs and "255" in errs[0]


def test_reject_missing_required_fields():
    assert validate_place_order({}) , "empty order must be invalid"
    assert validate_place_order(_doc_order(requestId=""))
    assert validate_place_order(_doc_order(shipTo={}))
    assert validate_place_order(_doc_order(lines=[]))
    assert validate_place_order(_doc_order(purchaseOrder="X" * 21))


def test_reject_line_missing_ordered_qty():
    order = _doc_order()
    order["lines"][0].pop("orderedQty")
    assert validate_place_order(order)
