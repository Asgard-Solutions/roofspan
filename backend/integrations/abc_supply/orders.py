"""ABC Supply Order API (source: https://apidocs.abcsupply.com/place-orders/ and /get-orders/).

Verified endpoints:
  POST {ORDER_PREFIX}/orders                      (body is a JSON ARRAY of order objects; 202 Accepted)
  GET  {ORDER_PREFIX}/orders/{orderNumber}
  GET  {ORDER_PREFIX}/orders?confirmationNumber=  (order detail by confirmation)

Place-order response: {request:{batchId,...,ordersSucceded}, orders:[{requestId, confirmationNumber, message}]}.
NOTE: only a confirmationNumber is returned at submit; the orderNumber appears later via Get Order.
`requestId` is the client-provided tracking id — RoofSpan uses its durable submission key here for idempotency.

NEEDS ABC DOC/SANDBOX VERIFICATION: exact Order History and Order Template endpoint paths/filters are not
fully captured from the public docs. `get_order_history`, `list_templates`, `get_template` are isolated here
and supported in the local mock; reconcile once verified against Sandbox.
"""
from __future__ import annotations

from .client import AbcClient
from .config import ORDER_PREFIX

# Order 99-line limit; purchaseOrder field limited to 20 chars (per docs).
MAX_ORDER_LINES = 99
PO_FIELD_MAX = 20

_STATUS_MAP = {
    "submitted": "processing", "accepted": "processing", "processing": "processing", "open": "processing",
    "scheduled": "scheduled", "shipped": "shipped", "delivered": "delivered",
    "invoiced": "invoiced", "cancelled": "cancelled", "canceled": "cancelled",
}


def normalize_status(raw: str | None) -> str:
    return _STATUS_MAP.get((raw or "").strip().lower(), "processing")


def build_order_line(*, line_id, item_number, item_description, quantity, uom,
                     unit_price=None, price_uom=None, length_value=None, length_uom=None) -> dict:
    line: dict = {
        "id": str(line_id), "itemNumber": item_number, "itemDescription": item_description,
        "orderedQty": {"value": quantity, "uom": uom},
    }
    if unit_price is not None:
        line["unitPrice"] = {"value": unit_price, "uom": price_uom or uom}
    if length_value is not None and length_uom:
        line["dimensions"] = {"length": {"uom": length_uom, "value": length_value}}
    return line


async def place_order(client: AbcClient, order: dict) -> dict:
    """Submit ONE order. Body is a single-element array per the ABC contract. Not auto-retried."""
    data = await client.post_json(f"{ORDER_PREFIX}/orders", json=[order], allow_retry=False)
    orders = (data or {}).get("orders") or []
    first = orders[0] if orders else {}
    return {
        "ok": bool(first.get("confirmationNumber")),
        "confirmation_number": first.get("confirmationNumber"),
        "request_id": first.get("requestId"),
        "message": first.get("message"),
        "batch_id": (data or {}).get("request", {}).get("batchId"),
        "raw": data,
    }


def _normalize_order(data: dict) -> dict:
    so = data.get("salesOrder") or {}
    amounts = data.get("orderAmounts") or {}
    branch = data.get("branch") or {}
    shipments = []
    for s in data.get("shipments") or []:
        hist = s.get("deliveryHistory") or []
        shipments.append({
            "shipment_number": s.get("shipmentNumber"), "status": s.get("status"),
            "delivered_on": (s.get("dates") or {}).get("deliveredOn"),
            "invoiced_on": (s.get("dates") or {}).get("invoicedOn"),
            "latest_delivery_event": (hist[0].get("name") if hist else None),
            "delivery_history": hist,
        })
    return {
        "confirmation_number": so.get("confirmationNumber"),
        "order_number": so.get("orderNumber"),
        "purchase_order": so.get("purchaseOrder"),
        "abc_status": so.get("status"),
        "normalized_status": normalize_status(so.get("status")),
        "order_type": so.get("orderType"),
        "delivery_service": so.get("deliveryService"),
        "branch_number": branch.get("number"),
        "branch_name": branch.get("name"),
        "amounts": {"sub_total": amounts.get("subTotal"), "tax": amounts.get("tax"), "total": amounts.get("total")},
        "dates": data.get("dates"),
        "lines": data.get("lines") or [],
        "shipments": shipments,
    }


async def get_order_by_confirmation(client: AbcClient, confirmation_number: str) -> dict:
    data = await client.get_json(f"{ORDER_PREFIX}/orders", params={"confirmationNumber": confirmation_number})
    return _normalize_order(data if isinstance(data, dict) else {})


async def get_order_by_number(client: AbcClient, order_number: str) -> dict:
    data = await client.get_json(f"{ORDER_PREFIX}/orders/{order_number}")
    return _normalize_order(data if isinstance(data, dict) else {})


# --- NEEDS ABC DOC/SANDBOX VERIFICATION (paths/filters) ---
async def get_order_history(client: AbcClient, *, ship_to: str | None = None, branch: str | None = None) -> list[dict]:
    params: dict = {}
    if ship_to:
        params["shipToNumber"] = ship_to
    if branch:
        params["branchNumber"] = branch
    data = await client.get_json(f"{ORDER_PREFIX}/orders/history", params=params)  # NEEDS ABC DOC/SANDBOX VERIFICATION
    orders = data.get("orders") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    return orders or []


async def list_templates(client: AbcClient) -> list[dict]:
    data = await client.get_json(f"{ORDER_PREFIX}/templates")  # NEEDS ABC DOC/SANDBOX VERIFICATION
    return (data.get("templates") if isinstance(data, dict) else data) or []


async def get_template(client: AbcClient, template_id: str) -> dict:
    data = await client.get_json(f"{ORDER_PREFIX}/templates/{template_id}")  # NEEDS ABC DOC/SANDBOX VERIFICATION
    return data if isinstance(data, dict) else {}
