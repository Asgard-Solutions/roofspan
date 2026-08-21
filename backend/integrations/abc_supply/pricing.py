"""ABC Supply Pricing API (source: https://apidocs.abcsupply.com/price-items/).

Endpoint:  POST {PRICING_PREFIX}/prices   (verified: /api/pricing/v2/prices)

Third-Party Aggregators MUST use a user token with pricing.read (client credentials are NOT allowed
for pricing). Up to 50 lines per request. HTTP 200 is returned regardless of per-line errors — callers
MUST inspect each line's `status`.

$0.00 rule (mandatory): a line with status.code == "OK" and unitPrice == 0.00 means the branch offers the
item but has NOT entered pricing — this is NOT a free product. We normalize it to price_status="unavailable".
A per-line status.code != "OK" is also normalized to "unavailable" with the ABC message.
"""
from __future__ import annotations

from .client import AbcClient
from .config import PRICING_PREFIX

PRICE_OK = "priced"
PRICE_UNAVAILABLE = "unavailable"


def build_line(*, line_id: str, item_number: str, quantity: float, uom: str | None = None,
               length_value: float | None = None, length_uom: str | None = None) -> dict:
    line: dict = {"id": str(line_id), "itemNumber": item_number, "quantity": quantity}
    if uom:
        line["uom"] = uom
    if length_value is not None and length_uom:
        line["length"] = {"value": length_value, "uom": length_uom}
    return line


def _normalize_line(line: dict) -> dict:
    status = line.get("status") or {}
    code = (status.get("code") or "").upper()
    unit_price = line.get("unitPrice")
    price_status = PRICE_OK
    message = status.get("message")
    if code != "OK":
        price_status = PRICE_UNAVAILABLE
    elif unit_price is None or float(unit_price) == 0.0:
        # Available at branch but branch has not entered pricing.
        price_status = PRICE_UNAVAILABLE
        message = message or "Pricing unavailable. Contact this ABC Supply branch for pricing."
    return {
        "id": line.get("id"),
        "item_number": line.get("itemNumber"),
        "quantity": line.get("quantity"),
        "uom": line.get("uom"),
        "unit_price": (float(unit_price) if unit_price is not None else None),
        "currency": (line.get("currency") or {}).get("code", "USD"),
        "length": line.get("length"),
        "price_status": price_status,
        "status_code": status.get("code"),
        "status_message": message,
    }


async def price_items(client: AbcClient, *, ship_to_number: str, branch_number: str, lines: list[dict],
                      purpose: str = "ordering", request_id: str | None = None) -> list[dict]:
    body: dict = {"shipToNumber": ship_to_number, "branchNumber": branch_number, "purpose": purpose, "lines": lines}
    if request_id:
        body["requestId"] = request_id
    # Pricing is a write-style POST but read-only in effect; safe to retry idempotently.
    data = await client.post_json(f"{PRICING_PREFIX}/prices", json=body, allow_retry=True)
    resp_lines = data.get("lines") if isinstance(data, dict) else None
    return [_normalize_line(l) for l in (resp_lines or [])]
