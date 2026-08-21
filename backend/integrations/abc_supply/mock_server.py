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
    if not info:
        raise HTTPException(status_code=401, detail="Invalid or unknown token")
    if info["expires_at"] < time.time():
        raise HTTPException(status_code=401, detail="Token expired")
    return info


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


# Standalone app (tests / manual runs).
mock_app = FastAPI(title="Mock ABC Supply")
mock_app.include_router(router)
