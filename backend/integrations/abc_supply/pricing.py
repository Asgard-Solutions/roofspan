"""ABC Supply Pricing API (source: https://apidocs.abcsupply.com/price-items/).

Endpoint:  POST {PRICING_PREFIX}/prices   (verified: /api/pricing/v2/prices)

Third-Party Aggregators MUST use a user token with pricing.read (client credentials are NOT allowed
for pricing). Up to 50 lines per request (RoofSpan batches larger sets). HTTP 200 is returned regardless
of per-line errors — callers MUST inspect each line's `status`.

$0.00 rule (mandatory): a line with status.code == "OK" and unitPrice == 0.00 means the branch offers the
item but has NOT entered pricing — this is NOT a free product. We normalize it to price_status="unavailable".
A per-line status.code != "OK" is also normalized to "unavailable" with the ABC message.

Purpose (source docs): exactly one of estimating | quoting | ordering. Estimate workflows use estimating,
Quote workflows use quoting, and Purchase-Order / final ABC order review use ordering.
"""
from __future__ import annotations

from .client import AbcClient
from .config import PRICING_PREFIX

PRICE_OK = "priced"
PRICE_UNAVAILABLE = "unavailable"

# ABC Price Items request limits/enums (documented).
MAX_PRICE_LINES = 50
VALID_PURPOSES = ("estimating", "quoting", "ordering")


def validate_purpose(purpose: str) -> str:
    p = (purpose or "").strip().lower()
    if p not in VALID_PURPOSES:
        raise ValueError(f"purpose must be one of {VALID_PURPOSES}, got '{purpose}'")
    return p


def _coerce_quantity(quantity):
    """ABC expects an integer quantity. Whole-number floats are coerced (2.0 -> 2). A genuinely
    fractional quantity cannot be safely mapped to an ABC integer quantity and is rejected."""
    if quantity is None:
        raise ValueError("quantity is required")
    q = float(quantity)
    if q <= 0:
        raise ValueError("quantity must be greater than zero")
    if not q.is_integer():
        raise ValueError(f"ABC Supply requires a whole-number quantity; {quantity} cannot be priced")
    return int(q)


def build_line(*, line_id: str, item_number: str, quantity: float, uom: str | None = None,
               length_value: float | None = None, length_uom: str | None = None) -> dict:
    line: dict = {"id": str(line_id), "itemNumber": item_number, "quantity": _coerce_quantity(quantity)}
    if uom:
        line["uom"] = uom
    # Dimensional items ONLY: send length when a variation is present. Never send null/{} for
    # non-dimensional products.
    if length_value is not None and length_uom:
        line["length"] = {"value": length_value, "uom": length_uom}
    return line


def _normalize_line(line: dict, *, request_id: str | None = None) -> dict:
    status = line.get("status") or {}
    code = (status.get("code") or "").upper()
    unit_price = line.get("unitPrice")
    currency = line.get("currency") or {}
    price_status = PRICE_OK
    message = status.get("message")
    if code != "OK":
        price_status = PRICE_UNAVAILABLE
    elif unit_price is None or float(unit_price) == 0.0:
        # Available at branch but branch has not entered pricing. NOT a free product.
        price_status = PRICE_UNAVAILABLE
        message = message or "Pricing unavailable. Contact this ABC Supply branch for pricing."
    return {
        "id": line.get("id"),
        "item_number": line.get("itemNumber"),
        "quantity": line.get("quantity"),
        "uom": line.get("uom"),
        "unit_price": (float(unit_price) if unit_price is not None else None),
        "currency": currency.get("code", "USD"),
        "currency_symbol": currency.get("symbol", "$"),
        "length": line.get("length"),
        "price_status": price_status,
        "status_code": status.get("code"),
        "status_message": message,
        "request_id": request_id,
    }


def _chunk(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


async def price_items(client: AbcClient, *, ship_to_number: str, branch_number: str, lines: list[dict],
                      purpose: str = "ordering", request_id: str | None = None) -> list[dict]:
    """Price 1..N lines. ABC allows max 50 lines/request, so larger sets are batched and merged,
    preserving each line's stable RoofSpan `id`. Read-only in effect (safe idempotent retry)."""
    purpose = validate_purpose(purpose)
    results: list[dict] = []
    batches = list(_chunk(lines, MAX_PRICE_LINES))
    multi = len(batches) > 1
    for idx, batch in enumerate(batches, start=1):
        rid = request_id
        if rid and multi:
            rid = f"{request_id}-b{idx}"  # traceable per-batch tracking id
        body: dict = {"shipToNumber": ship_to_number, "branchNumber": branch_number,
                      "purpose": purpose, "lines": batch}
        if rid:
            body["requestId"] = rid
        data = await client.post_json(f"{PRICING_PREFIX}/prices", json=body, allow_retry=True)
        resp_lines = data.get("lines") if isinstance(data, dict) else None
        resp_rid = (data.get("requestId") if isinstance(data, dict) else None) or rid
        results.extend(_normalize_line(l, request_id=resp_rid) for l in (resp_lines or []))
    # Preserve caller ordering by the stable line id (ABC generally echoes order, but do not rely on it).
    order = {str(l.get("id")): i for i, l in enumerate(lines)}
    results.sort(key=lambda r: order.get(str(r.get("id")), 1_000_000))
    return results
