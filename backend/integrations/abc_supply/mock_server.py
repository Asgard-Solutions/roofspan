"""Local mock ABC Supply server for development and integration testing.

Emulates the documented ABC contracts (OAuth authorize/token with PKCE, Account API,
Location API — Product/Pricing/Order/Notification added in later phases) with canned data
that matches the shapes on https://apidocs.abcsupply.com. This lets the full RoofSpan flow
be exercised end-to-end without real ABC Sandbox credentials.

Mounted on the main app at /abc-mock ONLY when ABC_MOCK_ENABLED is set. Also exposed as a
standalone FastAPI `mock_app` for unit tests (via httpx ASGITransport) and manual runs:
    ABC_MOCK_ENABLED=1 uvicorn integrations.abc_supply.mock_server:mock_app --port 8099

Tokens issued here are opaque strings prefixed with `mock-`. This module contains NO real
secrets and NO RoofSpan business data.
"""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, FastAPI, Request, Header, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse

from .auth import verify_pkce

router = APIRouter()

# In-memory state (process-local). Reset on restart — acceptable for a dev/test mock.
_AUTH_CODES: dict[str, dict] = {}      # code -> {code_challenge, scope, redirect_uri}
_ACCESS_TOKENS: dict[str, dict] = {}   # access_token -> {expires_at, scope}
_REFRESH_TOKENS: dict[str, dict] = {}  # refresh_token -> {scope}

ACCESS_TTL = 1800  # 30 minutes, per ABC docs


def _issue_tokens(scope: str, *, with_refresh: bool) -> dict:
    access = f"mock-access-{uuid.uuid4().hex}"
    _ACCESS_TOKENS[access] = {"expires_at": time.time() + ACCESS_TTL, "scope": scope}
    body = {"token_type": "Bearer", "access_token": access, "expires_in": ACCESS_TTL, "scope": scope}
    if with_refresh:
        refresh = f"mock-refresh-{uuid.uuid4().hex}"
        _REFRESH_TOKENS[refresh] = {"scope": scope}
        body["refresh_token"] = refresh
    return body


def _require_bearer(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    info = _ACCESS_TOKENS.get(token)
    if info:
        if info["expires_at"] < time.time():
            raise HTTPException(status_code=401, detail="Token expired")
        return info
    # Reload-resilient: the mock's in-memory token store is cleared on hot reload, but tokens persisted
    # (encrypted) in RoofSpan's DB remain valid by timestamp. Accept any well-formed mock token so the
    # dev flow survives restarts. (Real token expiry/refresh is exercised by the unit tests.)
    if token.startswith("mock-"):
        return {"expires_at": time.time() + ACCESS_TTL, "scope": ""}
    raise HTTPException(status_code=401, detail="Invalid or unknown token")


# ---------------- OAuth ----------------
@router.get("/oauth2/v1/authorize")
async def authorize(request: Request):
    q = request.query_params
    redirect_uri = q.get("redirect_uri")
    state = q.get("state", "")
    code_challenge = q.get("code_challenge", "")
    scope = q.get("scope", "")
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="redirect_uri is required")
    code = f"mock-code-{uuid.uuid4().hex}"
    _AUTH_CODES[code] = {"code_challenge": code_challenge, "scope": scope, "redirect_uri": redirect_uri}
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(url=f"{redirect_uri}{sep}code={code}&state={state}", status_code=302)


@router.post("/oauth2/v1/token")
async def token(request: Request):
    form = await request.form()
    grant = form.get("grant_type")
    if grant == "authorization_code":
        code = form.get("code", "")
        verifier = form.get("code_verifier", "")
        rec = _AUTH_CODES.pop(code, None)
        if not rec:
            return JSONResponse(status_code=400, content={"error": "invalid_grant"})
        if rec["code_challenge"] and not verify_pkce(verifier, rec["code_challenge"]):
            return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "PKCE failed"})
        scope = rec["scope"] or ""
        return _issue_tokens(scope, with_refresh="offline_access" in scope)
    if grant == "refresh_token":
        refresh = form.get("refresh_token", "")
        scope = form.get("scope", "")
        rec = _REFRESH_TOKENS.pop(refresh, None)  # rotate refresh token
        if not rec:
            return JSONResponse(status_code=400, content={"error": "invalid_grant"})
        return _issue_tokens(scope or rec["scope"], with_refresh=True)
    if grant == "client_credentials":
        scope = form.get("scope", "")
        return _issue_tokens(scope, with_refresh=False)
    return JSONResponse(status_code=400, content={"error": "unsupported_grant_type"})


# ---------------- Account API ----------------
_HOME_BRANCH = {
    "homeBranch": True, "number": "18", "name": "ABC Supply - Madison, WI",
    "storefront": "abc", "status": "active", "type": "Branch",
    "links": {"self": "https://partners-sb.abcsupply.com/api/location/v1/branches/18"},
}
_OKC_BRANCH = {
    "homeBranch": False, "number": "409", "name": "ABC Supply - Oklahoma City, OK",
    "storefront": "abc", "status": "active", "type": "Branch",
    "links": {"self": "https://partners-sb.abcsupply.com/api/location/v1/branches/409"},
}

_SOLD_TO = {
    "name": "EASY ROOFING", "number": "116660", "status": "active", "isSellable": True,
    "address": {"line1": "123 MAIN ST", "line2": "", "line3": "", "city": "MADISON", "state": "WI", "postal": "53719", "country": "USA"},
    "branches": [_HOME_BRANCH],
}
_BILL_TO = {
    "name": "EASY ROOFING", "number": "116660", "status": "active",
    "address": {"line1": "123 MAIN ST", "line2": "", "line3": "", "city": "MADISON", "state": "WI", "postal": "53719", "country": "USA"},
    "billingInstructions": [{"code": "N", "description": "Do not print on the invoice"}],
    "branches": [_HOME_BRANCH],
    "soldTo": {"number": "116660", "name": "EASY ROOFING", "status": "active", "links": {"self": ""}},
}
_SHIP_TO_ACTIVE = {
    "name": "EASY ROOFING - JOB SITE", "number": "1163698", "status": "active",
    "address": {"line1": "123 JOB ST", "line2": "", "line3": "", "city": "MADISON", "state": "WI", "postal": "53719", "country": "USA"},
    "contacts": {"links": {"self": "https://partners-sb.abcsupply.com/api/account/v1/shiptos/1163698/contacts"}},
    "billTo": {"number": "116660", "name": "EASY ROOFING", "status": "active", "links": {"self": ""}},
    "soldTo": {"number": "116660", "name": "EASY ROOFING", "status": "active", "links": {"self": ""}},
    "branches": [_HOME_BRANCH, _OKC_BRANCH],
}
_SHIP_TO_RETIRED = {
    "name": "OLD RETIRED SITE", "number": "9999999", "status": "inactive",
    "address": {"line1": "1 OLD RD", "line2": "", "line3": "", "city": "MADISON", "state": "WI", "postal": "53719", "country": "USA"},
    "branches": [],  # retired ERP account — must be filtered out by RoofSpan
    "billTo": {"number": "116660", "name": "EASY ROOFING", "status": "inactive", "links": {"self": ""}},
    "soldTo": {"number": "116660", "name": "EASY ROOFING", "status": "inactive", "links": {"self": ""}},
}


@router.post("/api/account/v1/search/accounts")
async def search_accounts(request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    return {
        "pagination": {"itemsPerPage": 50, "pageNumber": 1, "totalPages": 1, "totalItems": 1},
        "soldTos": [_SOLD_TO],
        "billTos": [_BILL_TO],
        "shipTos": [_SHIP_TO_ACTIVE, _SHIP_TO_RETIRED],
    }


@router.get("/api/account/v1/soldtos/{number}")
async def get_sold_to(number: str, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    return {**_SOLD_TO, "number": number}


@router.get("/api/account/v1/billtos/{number}")
async def get_bill_to(number: str, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    return {**_BILL_TO, "number": number}


@router.get("/api/account/v1/shiptos/{number}")
async def get_ship_to(number: str, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    return {**_SHIP_TO_ACTIVE, "number": number}


@router.get("/api/account/v1/shiptos/{number}/contacts")
async def get_ship_to_contacts(number: str, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    return {"contacts": [{"name": "Pat Jacobsen", "type": "Delivery", "phone": "6085551234", "email": "pat@example.com"}]}


# ---------------- Location API ----------------
_BRANCH_DETAIL = {
    "branch": {"number": "409", "name": "ABC Supply - Oklahoma City, OK", "storefront": "abc", "distance": 8, "status": "open", "type": "Branch"},
    "address": {"addressLine1": "3404 Kenilworth Ave", "addressLine2": "N/A", "addressLine3": "N/A", "city": "Oklahoma City", "state": "OK", "postal": "73102", "country": "USA"},
    "locale": {"lat": "35.46", "long": "-97.51", "timeZoneCode": "CT", "timeZoneDescription": "America/Chicago"},
    "contact": {"phones": ["4055551700 - ext 1234"], "emails": ["branch409@abcsupply.com"], "fax": "4055551701"},
    "manager": {"firstName": "Ryan", "lastName": "Mannick", "email": "ryan.mannick@abcsupply.com", "title": "Managing Partner"},
    "hoursOfOperation": [{"type": "DAILY", "days": "MON - FRI", "open": "7 AM", "close": "5 PM", "notes": ""}],
    "links": {"self": "https://partners-sb.abcsupply.com/api/location/v1/branches/409", "website": "https://www.abcsupply.com/location/409"},
}
_BRANCH_18 = {
    "branch": {"number": "18", "name": "ABC Supply - Madison, WI", "storefront": "abc", "distance": 2, "status": "open", "type": "Branch"},
    "address": {"addressLine1": "500 W Beltline Hwy", "addressLine2": "N/A", "addressLine3": "N/A", "city": "Madison", "state": "WI", "postal": "53719", "country": "USA"},
    "locale": {"lat": "43.06", "long": "-89.44", "timeZoneCode": "CT", "timeZoneDescription": "America/Chicago"},
    "contact": {"phones": ["6085551700"], "emails": ["branch18@abcsupply.com"], "fax": ""},
    "manager": {"firstName": "Dana", "lastName": "Cole", "email": "dana.cole@abcsupply.com", "title": "Branch Manager"},
    "hoursOfOperation": [{"type": "DAILY", "days": "MON - FRI", "open": "7 AM", "close": "5 PM", "notes": ""}],
    "links": {"self": "https://partners-sb.abcsupply.com/api/location/v1/branches/18", "website": "https://www.abcsupply.com/location/18"},
}


@router.get("/api/location/v1/branches")
async def search_branches(request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    return [_BRANCH_18, _BRANCH_DETAIL]


@router.get("/api/location/v1/branches/{number}")
async def get_branch(number: str, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    if number == "18":
        return _BRANCH_18
    return {**_BRANCH_DETAIL, "branch": {**_BRANCH_DETAIL["branch"], "number": number}}


# ---------------- Product API (Phase 2) ----------------
# Synthetic roofing catalog. Item numbers are CLEARLY synthetic (MOCK-*) and are NOT real ABC items.
_MOCK_ITEMS = [
    {
        "itemNumber": "MOCK-SHINGLE-ARCH-WW", "familyId": "PFam_MOCK_SHINGLE",
        "familyName": "Mock Architectural Shingles", "isDimensional": False,
        "itemDescription": "Mock Architectural Shingles - Weathered Wood (3 bundles/square)",
        "status": "Active", "color": {"name": "Weathered Wood", "code": "384", "description": "Product Color"},
        "uoms": [{"name": "Square", "code": "SQ", "description": "estimate"}, {"name": "Bundle", "code": "BD", "description": "stocking"}],
        "images": [{"assetId": "mock-shingle-arch-ww", "type": "PrimaryProductImage", "href": "http://127.0.0.1:8001/api/abc-mock/api/product/v1/items/mock-shingle-arch-ww/images"}],
        "hierarchy": {"productGroup": {"label": "Steep Slope Products", "category": {"label": "Steep Slope Roofing"}}},
        "manufacturer": "MockBrand", "branchNumbers": ["18", "409"],
    },
    {
        "itemNumber": "MOCK-UNDERLAYMENT-30", "familyId": "PFam_MOCK_UNDER",
        "familyName": "Mock Synthetic Underlayment", "isDimensional": False,
        "itemDescription": "Mock Synthetic Roofing Underlayment 30 (10 sq roll)", "status": "Active",
        "uoms": [{"name": "Roll", "code": "RL", "description": "stocking"}],
        "images": [], "hierarchy": {"productGroup": {"label": "Underlayment", "category": {"label": "Roofing Accessories"}}},
        "manufacturer": "MockBrand", "branchNumbers": ["18"],  # NOT available at 409
    },
    {
        "itemNumber": "MOCK-DRIP-EDGE-DIM", "familyId": "PFam_MOCK_DRIP",
        "familyName": "Mock Drip Edge", "isDimensional": True,
        "itemDescription": "Mock Aluminum Drip Edge (dimensional - length required)", "status": "Active",
        "uoms": [{"name": "Piece", "code": "PC", "description": "stocking"}],
        "images": [], "hierarchy": {"productGroup": {"label": "Metal", "category": {"label": "Roofing Accessories"}}},
        "manufacturer": "MockBrand", "branchNumbers": ["18", "409"],
    },
    {
        "itemNumber": "MOCK-RIDGE-CAP-NOPRICE", "familyId": "PFam_MOCK_RIDGE",
        "familyName": "Mock Ridge Cap", "isDimensional": False,
        "itemDescription": "Mock Hip & Ridge Cap Shingles (branch pricing not entered)", "status": "Active",
        "uoms": [{"name": "Bundle", "code": "BD", "description": "stocking"}],
        "images": [], "hierarchy": {"productGroup": {"label": "Steep Slope Products", "category": {"label": "Hip & Ridge"}}},
        "manufacturer": "MockBrand", "branchNumbers": ["18", "409"],
    },
    {
        "itemNumber": "MOCK-ICEWATER-BARRIER", "familyId": "PFam_MOCK_IW",
        "familyName": "Mock Ice & Water Barrier", "isDimensional": False,
        "itemDescription": "Mock Ice and Water Barrier Membrane (2 sq roll)", "status": "Active",
        "uoms": [{"name": "Roll", "code": "RL", "description": "stocking"}],
        "images": [], "hierarchy": {"productGroup": {"label": "Underlayment", "category": {"label": "Roofing Accessories"}}},
        "manufacturer": "MockBrand", "branchNumbers": ["18", "409"],
    },
    {  # priceable, but ABC place-order REJECTS this item (tests order rejection)
        "itemNumber": "MOCK-REJECT", "familyId": "PFam_MOCK_TEST", "familyName": "Mock Test",
        "isDimensional": False, "itemDescription": "Mock Reject-On-Order Test Item", "status": "Active",
        "uoms": [{"name": "Each", "code": "EA", "description": "stocking"}], "images": [],
        "hierarchy": {"productGroup": {"label": "Test", "category": {"label": "Test"}}},
        "manufacturer": "MockBrand", "branchNumbers": ["18", "409"],
    },
    {  # priceable, but ABC place-order times out AFTER accepting (tests unknown-state + reconcile)
        "itemNumber": "MOCK-TIMEOUT", "familyId": "PFam_MOCK_TEST", "familyName": "Mock Test",
        "isDimensional": False, "itemDescription": "Mock Timeout-On-Order Test Item", "status": "Active",
        "uoms": [{"name": "Each", "code": "EA", "description": "stocking"}], "images": [],
        "hierarchy": {"productGroup": {"label": "Test", "category": {"label": "Test"}}},
        "manufacturer": "MockBrand", "branchNumbers": ["18", "409"],
    },
]
_PRICE_TABLE = {  # (itemNumber) -> unit price in the mock
    "MOCK-SHINGLE-ARCH-WW": 135.36,
    "MOCK-UNDERLAYMENT-30": 89.5,
    "MOCK-ICEWATER-BARRIER": 112.0,
    "MOCK-REJECT": 9.99,
    "MOCK-TIMEOUT": 4.5,
    # MOCK-DRIP-EDGE-DIM priced by length below; MOCK-RIDGE-CAP-NOPRICE intentionally 0.00 (unavailable)
}


def _item_view(it: dict, *, branch_filter: str | None, embed_branches: bool) -> dict:
    view = {k: v for k, v in it.items() if k != "branchNumbers"}
    if embed_branches:
        view["branches"] = [{"number": n, "links": {"self": f"http://127.0.0.1:8001/api/abc-mock/api/location/v1/branches/{n}"}} for n in it["branchNumbers"]]
    return view


@router.post("/api/product/v1/search/items")
async def search_items(request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    body = await request.json()
    filters = body.get("filters") or []
    embed = "branches" in (body.get("embed") or [])
    branch_filter = None
    contains_key = contains_val = eq_item = eq_family = None
    for f in filters:
        cond, key, vals = f.get("condition"), f.get("key"), (f.get("values") or [])
        val = vals[0] if vals else None
        if cond == "contains":
            contains_key, contains_val = key, (val or "").lower()
        elif cond == "equals" and key == "itemNumber":
            eq_item = val
        elif cond == "equals" and key == "productFamilyId":
            eq_family = val
        elif cond == "equals" and key == "branchNumber":
            branch_filter = val
    results = []
    for it in _MOCK_ITEMS:
        if eq_item and it["itemNumber"] != eq_item:
            continue
        if eq_family and it["familyId"] != eq_family:
            continue
        if contains_val:
            hay = (it["itemDescription"] if contains_key != "itemNumber" else it["itemNumber"]).lower()
            if contains_val not in hay:
                continue
        if branch_filter and branch_filter not in it["branchNumbers"]:
            continue
        results.append(_item_view(it, branch_filter=branch_filter, embed_branches=embed))
    return {"pagination": {"itemsPerPage": 25, "pageNumber": 1, "totalPages": 1, "totalItems": len(results)}, "items": results}


@router.get("/api/product/v1/items/{asset_id}/images")
async def get_item_image(asset_id: str, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    # 1x1 transparent PNG.
    import base64 as _b64
    png = _b64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    from fastapi.responses import Response as _Resp
    return _Resp(content=png, media_type="image/png")


# Full-catalog retrieval for sync (GET /api/product/v1/items). Includes a synthetic DISCONTINUED item so
# incremental/inactive handling can be exercised. `sinceLastModifiedDateTime` filters by lastModifiedDateTime.
_CATALOG_LAST_MODIFIED = "2026-06-01T00:00:00Z"
_MOCK_DISCONTINUED = {
    "itemNumber": "MOCK-DISCONTINUED", "familyId": "PFam_MOCK_OLD", "familyName": "Mock Discontinued",
    "isDimensional": False, "itemDescription": "Mock Discontinued Shingle (no longer stocked)",
    "status": "Inactive", "uoms": [{"name": "Bundle", "code": "BD", "description": "stocking"}], "images": [],
    "hierarchy": {"productGroup": {"label": "Steep Slope Products", "category": {"label": "Steep Slope Roofing"}}},
    "manufacturer": "MockBrand", "branchNumbers": ["18"],
}


def _catalog_items():
    items = [dict(it, lastModifiedDateTime=_CATALOG_LAST_MODIFIED) for it in _MOCK_ITEMS]
    items.append(dict(_MOCK_DISCONTINUED, lastModifiedDateTime="2026-06-10T00:00:00Z"))
    return items


@router.get("/api/product/v1/items")
async def list_items_mock(request: Request, authorization: str | None = Header(default=None),
                          pageNumber: int = 1, itemsPerPage: int = 100,
                          sinceLastModifiedDateTime: str | None = None, embed: str | None = None):
    _require_bearer(authorization)
    all_items = _catalog_items()
    if sinceLastModifiedDateTime:
        all_items = [it for it in all_items if it["lastModifiedDateTime"] >= sinceLastModifiedDateTime]
    total = len(all_items)
    total_pages = max(1, (total + itemsPerPage - 1) // itemsPerPage) if total else 1
    start = (pageNumber - 1) * itemsPerPage
    page_items = all_items[start:start + itemsPerPage]
    embed_branches = embed == "branches"
    views = [_item_view(it, branch_filter=None, embed_branches=embed_branches) for it in page_items]
    for v, src in zip(views, page_items):
        v["lastModifiedDateTime"] = src["lastModifiedDateTime"]
        v["status"] = src.get("status", "Active")
        if not embed_branches:
            v["branchNumbers"] = src["branchNumbers"]
    return {"pagination": {"itemsPerPage": itemsPerPage, "pageNumber": pageNumber, "totalPages": total_pages, "totalItems": total},
            "items": views}



# ---------------- Pricing API (Phase 2, /api/pricing/v2/prices) ----------------
@router.post("/api/pricing/v2/prices")
async def price_items(request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    body = await request.json()
    known = {it["itemNumber"] for it in _MOCK_ITEMS}
    out_lines = []
    for line in body.get("lines") or []:
        item = line.get("itemNumber")
        qty = line.get("quantity")
        uom = line.get("uom")
        length = line.get("length")
        base = {"id": line.get("id"), "itemNumber": item, "quantity": qty, "uom": uom,
                "currency": {"code": "USD", "symbol": "$"}}
        if item not in known:
            base.update({"unitPrice": 0.00, "status": {"code": "Error", "message": f"Cannot price item {item}. Call for pricing."}})
        elif item == "MOCK-RIDGE-CAP-NOPRICE":
            base.update({"unitPrice": 0.00, "status": {"code": "OK", "message": "Priced Successfully"}})  # $0 = branch has not entered pricing
        elif item == "MOCK-DRIP-EDGE-DIM":
            if not length:
                base.update({"unitPrice": 0.00, "status": {"code": "Error", "message": "This item requires a length variation before pricing can be retrieved."}})
            else:
                base.update({"unitPrice": round(6.5 * float(length.get("value") or 1), 2), "length": length, "status": {"code": "OK", "message": "Priced Successfully"}})
        else:
            base.update({"unitPrice": _PRICE_TABLE.get(item, 0.00), "status": {"code": "OK", "message": "Priced Successfully"}})
        out_lines.append(base)
    return {"requestId": body.get("requestId"), "shipToNumber": body.get("shipToNumber"),
            "branchNumber": body.get("branchNumber"), "purpose": body.get("purpose"), "lines": out_lines}


# ---------------- Order API (Phase 3, /api/order/v2) ----------------
_MOCK_ORDERS: dict[str, dict] = {}   # confirmationNumber -> normalized-ish order record
_MOCK_BY_REQID: dict[str, str] = {}  # requestId -> confirmationNumber


def _order_record(conf: str, order_number: str, order: dict) -> dict:
    branch = order.get("branchNumber")
    lines = order.get("lines") or []
    total = 0.0
    for l in lines:
        q = (l.get("orderedQty") or {}).get("value") or 0
        up = (l.get("unitPrice") or {}).get("value") or 0
        total += float(q) * float(up)
    return {
        "salesOrder": {"confirmationNumber": conf, "orderNumber": order_number,
                       "purchaseOrder": order.get("purchaseOrder"), "createdDate": "2026-06-17",
                       "orderType": "Delivery", "deliveryService": order.get("deliveryService"),
                       "status": "Processing", "currency": order.get("currency", "USD")},
        "dates": order.get("dates"),
        "orderAmounts": {"subTotal": round(total, 2), "tax": 0.0, "total": round(total, 2)},
        "shipTo": order.get("shipTo"),
        "branch": {"number": branch, "name": f"ABC Supply - Branch {branch}", "storefront": "abc"},
        "lines": lines,
        "shipments": [{"shipmentNumber": f"{order_number}-1", "status": "Scheduled",
                       "dates": {"deliveryRequestedOn": (order.get("dates") or {}).get("deliveryRequestedFor")},
                       "deliveryHistory": [{"name": "Scheduled", "code": "AG", "localTime": "2026-06-17T09:00:00-05:00"}]}],
    }


@router.post("/api/order/v2/orders")
async def place_order_mock(request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    body = await request.json()
    order = body[0] if isinstance(body, list) and body else (body if isinstance(body, dict) else {})
    lines = order.get("lines") or []
    req_id = order.get("requestId")
    # Rejection scenario (documented error shape: 400 with per-order message).
    if any(l.get("itemNumber") == "MOCK-REJECT" for l in lines):
        return JSONResponse(status_code=400, content={
            "request": {"ordersReceived": 1, "ordersFailed": 1, "ordersSucceded": 0},
            "orders": [{"requestId": req_id, "message": "Order rejected: item MOCK-REJECT is not orderable at this branch."}]})
    # Idempotency at the ABC layer: same requestId returns the same confirmation, never a new order.
    if req_id and req_id in _MOCK_BY_REQID:
        conf = _MOCK_BY_REQID[req_id]
        return {"request": {"batchId": "B-DUP", "ordersReceived": 1, "ordersFailed": 0, "ordersSucceded": 1},
                "orders": [{"requestId": req_id, "confirmationNumber": conf, "message": "Ordered successfully"}]}
    seq = len(_MOCK_ORDERS) + 1
    conf = f"MOCK-CONF-{10000 + seq}"
    order_number = f"MOCK-ORDER-{20000 + seq}"
    _MOCK_ORDERS[conf] = _order_record(conf, order_number, order)
    if req_id:
        _MOCK_BY_REQID[req_id] = conf
    # Timeout-after-accept scenario: order IS recorded (reconcilable) but we return an ambiguous 504.
    if any(l.get("itemNumber") == "MOCK-TIMEOUT" for l in lines):
        return JSONResponse(status_code=504, content={"message": "Gateway timeout"})
    return {"request": {"batchId": f"B{seq}", "receivedTime": "2026-06-17T09:00:00", "ordersReceived": 1,
                        "ordersFailed": 0, "ordersSucceded": 1},
            "orders": [{"requestId": req_id, "confirmationNumber": conf, "message": "Ordered successfully"}]}


@router.get("/api/order/v2/orders/history")
async def order_history_mock(request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    orders = []
    for rec in _MOCK_ORDERS.values():
        so = rec["salesOrder"]
        orders.append({"confirmationNumber": so["confirmationNumber"], "orderNumber": so["orderNumber"],
                       "purchaseOrder": so["purchaseOrder"], "status": so["status"], "createdDate": so["createdDate"],
                       "branch": rec["branch"], "total": rec["orderAmounts"]["total"],
                       "deliveryStatus": rec["shipments"][0]["status"] if rec["shipments"] else None})
    return {"orders": orders}


@router.get("/api/order/v2/orders/{order_number}")
async def get_order_by_number_mock(order_number: str, request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    for rec in _MOCK_ORDERS.values():
        if rec["salesOrder"]["orderNumber"] == order_number:
            return rec
    raise HTTPException(status_code=404, detail="Order not found")


@router.get("/api/order/v2/orders")
async def get_order_by_conf_mock(request: Request, confirmationNumber: str | None = None, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    rec = _MOCK_ORDERS.get(confirmationNumber or "")
    if not rec:
        raise HTTPException(status_code=404, detail="Order not found")
    return rec


@router.get("/api/order/v2/templates")
async def list_templates_mock(request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    return {"templates": [
        {"id": "MOCK-TMPL-1", "name": "Standard Reroof Kit", "lastUpdated": "2026-05-01",
         "items": [{"itemNumber": "MOCK-SHINGLE-ARCH-WW", "quantity": 30, "uom": "SQ"},
                   {"itemNumber": "MOCK-UNDERLAYMENT-30", "quantity": 3, "uom": "RL"},
                   {"itemNumber": "MOCK-ICEWATER-BARRIER", "quantity": 2, "uom": "RL"}]},
    ]}


@router.get("/api/order/v2/templates/{template_id}")
async def get_template_mock(template_id: str, request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    return {"id": template_id, "name": "Standard Reroof Kit", "lastUpdated": "2026-05-01",
            "items": [{"itemNumber": "MOCK-SHINGLE-ARCH-WW", "quantity": 30, "uom": "SQ"},
                      {"itemNumber": "MOCK-UNDERLAYMENT-30", "quantity": 3, "uom": "RL"}]}


# ---------------- Notification API (Phase 4, /api/notification/v2/webhooks) ----------------
_MOCK_WEBHOOKS: dict[str, dict] = {}


@router.post("/api/notification/v2/webhooks")
async def register_webhook_mock(request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    body = await request.json()
    if len(_MOCK_WEBHOOKS) >= 5:
        raise HTTPException(status_code=400, detail="Maximum of 5 webhooks per application")
    wid = f"MOCK-WEBHOOK-{len(_MOCK_WEBHOOKS) + 1}"
    rec = {"id": wid, "name": body.get("name"), "type": body.get("type"), "events": body.get("events"),
           "url": body.get("url"), "status": "REGISTERED", "secret": f"MOCK-WEBHOOK-SECRET-{wid}"}
    _MOCK_WEBHOOKS[wid] = rec
    return rec


@router.get("/api/notification/v2/webhooks")
async def list_webhooks_mock(request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    # secrets are only returned at registration time in real ABC; omit here on list
    return {"webhooks": [{k: v for k, v in w.items() if k != "secret"} for w in _MOCK_WEBHOOKS.values()]}


@router.get("/api/notification/v2/webhooks/{webhook_id}")
async def get_webhook_mock(webhook_id: str, request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    w = _MOCK_WEBHOOKS.get(webhook_id)
    if not w:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {k: v for k, v in w.items() if k != "secret"}


@router.patch("/api/notification/v2/webhooks/{webhook_id}")
async def patch_webhook_mock(webhook_id: str, request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    w = _MOCK_WEBHOOKS.get(webhook_id)
    if not w:
        raise HTTPException(status_code=404, detail="Webhook not found")
    body = await request.json()
    w.update({k: body[k] for k in ("name", "events", "url") if k in body})
    return {k: v for k, v in w.items() if k != "secret"}


@router.delete("/api/notification/v2/webhooks/{webhook_id}")
async def delete_webhook_mock(webhook_id: str, request: Request, authorization: str | None = Header(default=None)):
    _require_bearer(authorization)
    _MOCK_WEBHOOKS.pop(webhook_id, None)
    return JSONResponse(status_code=204, content=None)


# Standalone app (tests / manual runs).
mock_app = FastAPI(title="Mock ABC Supply")
mock_app.include_router(router)
