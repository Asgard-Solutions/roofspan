"""Single, versioned source of truth for the ABC Supply Place Order request contract.

Source: https://apidocs.abcsupply.com/place-orders/

BOTH sides use this module so they can never drift:
  * production payload construction (backend/routers/purchasing.py abc_submit) validates the order it
    builds against this contract before sending (defense in depth), and
  * the ABC mock server (integrations/abc_supply/mock_server.py) rejects any request that violates it.

`validate_place_order(order)` returns a list of human-readable error strings ([] == valid). It intentionally
validates the fields RoofSpan sends plus the shapes ABC's documentation is strict about, and it explicitly
rejects the historical WRONG shapes that used to slip through (a bare `comments` string, a line comment that
is not a {code, description} object, and a time window under `dates.deliveryAppointmentTime`).
"""
from __future__ import annotations

from .orders import DELIVERY_SERVICE_CODES

# Bump when the ABC Place Order contract materially changes.
CONTRACT_VERSION = "2025-05"

# Order-level + line-level comment codes: H=header, F=footer, D=detail.
ORDER_COMMENT_CODES = {"H", "F", "D"}
# deliveryAppointment.instructionsTypeCode: AT=Anytime, AM=Morning, PM=Afternoon, FS=First Stop,
# ST=Specific Time, TR=Time Range. fromTime applies to ST & TR; toTime only to TR.
APPOINTMENT_TYPE_CODES = {"AT", "AM", "PM", "FS", "ST", "TR"}
MAX_INSTRUCTIONS = 255
PO_FIELD_MAX = 20


def _validate_comments(order: dict, lines: list) -> str | None:
    if "comments" in order:
        return "Invalid order: use `orderComments` array of {code, description}, not a `comments` string."
    oc = order.get("orderComments")
    if oc is not None:
        if not isinstance(oc, list):
            return "Invalid orderComments: expected an array of {code, description} objects."
        for c in oc:
            if not isinstance(c, dict) or not str(c.get("description") or "").strip():
                return "Invalid orderComments entry: each comment needs a code and description."
            if c.get("code") not in ORDER_COMMENT_CODES:
                return f"Invalid orderComments code '{c.get('code')}': must be one of H, F, D."
    for ln in lines:
        lc = ln.get("comments")
        if lc is None:
            continue
        if not isinstance(lc, dict):
            return "Invalid line comment: expected a {code, description} object."
        if not str(lc.get("description") or "").strip():
            return "Invalid line comment: each comment needs a code and description."
        if lc.get("code") not in ORDER_COMMENT_CODES:
            return f"Invalid line comment code '{lc.get('code')}': must be one of H, F, D."
    return None


def _validate_appointment(order: dict) -> str | None:
    dates = order.get("dates") or {}
    if isinstance(dates, dict) and "deliveryAppointmentTime" in dates:
        return "Invalid order: use a `deliveryAppointment` object, not `dates.deliveryAppointmentTime`."
    appt = order.get("deliveryAppointment")
    if appt is None:
        return None
    if not isinstance(appt, dict):
        return "Invalid deliveryAppointment: expected an object with instructionsTypeCode."
    code = appt.get("instructionsTypeCode")
    if code not in APPOINTMENT_TYPE_CODES:
        return f"Invalid deliveryAppointment instructionsTypeCode '{code}': must be one of AT, AM, PM, FS, ST, TR."
    if code in ("ST", "TR") and not str(appt.get("fromTime") or "").strip():
        return f"deliveryAppointment type '{code}' requires a fromTime."
    if code == "TR" and not str(appt.get("toTime") or "").strip():
        return "deliveryAppointment type 'TR' requires a toTime."
    if str(appt.get("instructions") or "") and len(appt["instructions"]) > MAX_INSTRUCTIONS:
        return f"deliveryAppointment instructions must be {MAX_INSTRUCTIONS} characters or fewer."
    return None


def _validate_structure(order: dict) -> list[str]:
    errs: list[str] = []
    if not str(order.get("requestId") or "").strip():
        errs.append("Order is missing requestId.")
    po = str(order.get("purchaseOrder") or "").strip()
    if not po:
        errs.append("Order is missing purchaseOrder.")
    elif len(po) > PO_FIELD_MAX:
        errs.append(f"purchaseOrder must be {PO_FIELD_MAX} characters or fewer.")
    if not str(order.get("branchNumber") or "").strip():
        errs.append("Order is missing branchNumber.")
    ship_to = order.get("shipTo")
    if not isinstance(ship_to, dict) or not str(ship_to.get("number") or "").strip():
        errs.append("Order is missing shipTo.number.")
    ds = order.get("deliveryService")
    if ds is not None and ds not in DELIVERY_SERVICE_CODES:
        errs.append(f"deliveryService '{ds}' is not a valid ABC code.")
    lines = order.get("lines")
    if not isinstance(lines, list) or not lines:
        errs.append("Order must have at least one line.")
    else:
        for i, ln in enumerate(lines):
            if not isinstance(ln, dict):
                errs.append(f"Line {i + 1} is malformed.")
                continue
            if not str(ln.get("itemNumber") or "").strip():
                errs.append(f"Line {i + 1} is missing itemNumber.")
            oq = ln.get("orderedQty")
            if not isinstance(oq, dict) or oq.get("value") is None or not str(oq.get("uom") or "").strip():
                errs.append(f"Line {i + 1} needs orderedQty with value and uom.")
    return errs


def validate_place_order(order: dict) -> list[str]:
    """Validate a single ABC Place Order object against the versioned contract.
    Returns [] when valid, else a list of error messages (structural errors first)."""
    if not isinstance(order, dict):
        return ["Order must be a JSON object."]
    errs = _validate_structure(order)
    lines = order.get("lines") if isinstance(order.get("lines"), list) else []
    comment_err = _validate_comments(order, lines)
    if comment_err:
        errs.append(comment_err)
    appt_err = _validate_appointment(order)
    if appt_err:
        errs.append(appt_err)
    return errs
