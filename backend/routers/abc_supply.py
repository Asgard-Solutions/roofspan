"""ABC Supply integration API (RoofSpan Office / Desktop only) — prefix /api/integrations/abc.

Owns per-install ABC configuration, the OAuth 2.0 (Authorization Code + PKCE) connect flow,
encrypted token storage + automatic refresh, and account/branch selection. All ABC HTTP access
goes through integrations.abc_supply.* . Business/purchasing data stays in local PostgreSQL.

RBAC: connect/disconnect/config/defaults are owner|administrator (SENSITIVE_ROLES).
Read (status/accounts/branches) is owner|administrator|office (MANAGE_ROLES).
The OAuth /callback is a top-level browser redirect and is intentionally unauthenticated;
it is protected by the opaque `state` value bound to the in-flight authorization.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import AbcIntegration, User
from core import require_roles, SENSITIVE_ROLES, MANAGE_ROLES, encrypt_secret, decrypt_secret, log_action
from integrations.abc_supply import config as abc_config
from integrations.abc_supply import auth as abc_auth
from integrations.abc_supply.client import AbcClient
from integrations.abc_supply import accounts as abc_accounts
from integrations.abc_supply import locations as abc_locations
from integrations.abc_supply import products as abc_products
from integrations.abc_supply import pricing as abc_pricing
from integrations.abc_supply.exceptions import AbcError, AbcAuthError, AbcNotConfigured
from integrations.abc_supply.schemas import (
    AbcConfigUpdate, AbcSecretUpdate, AbcDefaultsUpdate, AbcStatusOut, AbcConnectOut,
    AbcTestResult, AbcShipToOut, AbcBranchOut, AbcProductSearchIn, AbcProductOut, AbcPriceIn,
)

log = logging.getLogger("roofspan.abc")
router = APIRouter(prefix="/api/integrations/abc", tags=["abc-supply"])


# --------------------------- helpers ---------------------------
async def _get_or_create(db: AsyncSession) -> AbcIntegration:
    row = (await db.execute(select(AbcIntegration))).scalars().first()
    if not row:
        row = AbcIntegration(environment=abc_config.DEFAULT_ENVIRONMENT, status="not_connected")
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def _safe_decrypt(cipher: str | None) -> str | None:
    if not cipher:
        return None
    try:
        return decrypt_secret(cipher)
    except Exception:
        return None


def _public_base(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def _effective_redirect(row: AbcIntegration, request: Request) -> str:
    # In mock mode the redirect must always target this deployment's public base (the mock/OAuth round
    # trip happens in the browser). A stored redirect_uri only applies to real ABC (must match what was
    # registered with ABC exactly).
    default = f"{_public_base(request)}/api/integrations/abc/callback"
    if abc_config.mock_enabled():
        return default
    return row.redirect_uri or default


def _build_cfg(row: AbcIntegration, *, redirect_uri: str | None = None) -> abc_config.AbcConfig:
    return abc_config.build_config(
        environment=row.environment,
        client_id=row.client_id,
        client_secret=_safe_decrypt(row.client_secret_ciphertext),
        redirect_uri=redirect_uri if redirect_uri is not None else row.redirect_uri,
        webhook_public_url=row.webhook_public_url,
    )


def _store_tokens(row: AbcIntegration, tok: dict) -> None:
    access = tok.get("access_token")
    refresh = tok.get("refresh_token")
    expires_in = int(tok.get("expires_in") or 1800)
    if access:
        row.access_token_ciphertext = encrypt_secret(access)
    if refresh:
        row.refresh_token_ciphertext = encrypt_secret(refresh)
    row.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    row.token_scopes = tok.get("scope") or row.token_scopes


async def _ensure_user_token(db: AsyncSession, row: AbcIntegration, request: Request) -> str:
    """Return a valid user access token, transparently refreshing if it is expiring.
    Raises AbcAuthError (setting status=reconnect_required) if the connection is unusable."""
    if row.status == "not_connected" or not row.access_token_ciphertext:
        raise AbcNotConfigured("ABC Supply is not connected.")
    exp = row.token_expires_at
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    needs_refresh = exp is None or exp <= datetime.now(timezone.utc) + timedelta(seconds=60)
    if needs_refresh:
        refresh = _safe_decrypt(row.refresh_token_ciphertext)
        cfg = _build_cfg(row, redirect_uri=_effective_redirect(row, request))
        if not refresh:
            row.status = "reconnect_required"
            await db.commit()
            raise AbcAuthError("Your ABC Supply connection has expired. Please reconnect ABC Supply.")
        try:
            tok = await abc_auth.refresh_token(cfg, refresh=refresh, scope=abc_config.USER_SCOPES)
        except AbcError:
            row.status = "reconnect_required"
            await db.commit()
            raise AbcAuthError("Your ABC Supply connection has expired. Please reconnect ABC Supply.")
        _store_tokens(row, tok)
        row.status = "connected"
        await db.commit()
        await db.refresh(row)
    return _safe_decrypt(row.access_token_ciphertext)  # type: ignore[return-value]


def _status_out(row: AbcIntegration, request: Request) -> AbcStatusOut:
    cid = row.client_id or ""
    return AbcStatusOut(
        environment=row.environment,
        status=row.status,
        is_mock=abc_config.mock_enabled(),
        has_client_id=bool(row.client_id),
        has_client_secret=bool(row.client_secret_ciphertext),
        client_id_masked=(f"{cid[:4]}…{cid[-4:]}" if len(cid) >= 8 else ("••••" if cid else None)),
        redirect_uri=row.redirect_uri,
        redirect_uri_effective=_effective_redirect(row, request),
        webhook_public_url=row.webhook_public_url,
        connected_identity=row.connected_identity,
        default_ship_to_number=row.default_ship_to_number,
        default_branch_number=row.default_branch_number,
        token_scopes=row.token_scopes,
        token_expires_at=row.token_expires_at,
        connected_at=row.connected_at,
        last_connected_at=row.last_connected_at,
    )


def _map_ship_to(st: dict) -> AbcShipToOut:
    branches = st.get("branches") or []
    home = next((b.get("number") for b in branches if b.get("homeBranch")), None)
    return AbcShipToOut(
        number=str(st.get("number") or ""),
        name=st.get("name"),
        status=st.get("status"),
        address=st.get("address"),
        bill_to_number=(st.get("billTo") or {}).get("number"),
        bill_to_name=(st.get("billTo") or {}).get("name"),
        sold_to_number=(st.get("soldTo") or {}).get("number"),
        sold_to_name=(st.get("soldTo") or {}).get("name"),
        branches=branches,
        home_branch_number=home,
    )


# --------------------------- config ---------------------------
@router.get("/status", response_model=AbcStatusOut)
async def get_status(request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    return _status_out(row, request)


@router.put("/config", response_model=AbcStatusOut)
async def update_config(payload: AbcConfigUpdate, request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    if payload.environment is not None:
        env = payload.environment.strip().lower()
        if env not in abc_config.DEFAULT_BASES:
            raise HTTPException(status_code=422, detail="environment must be 'sandbox' or 'production'")
        row.environment = env
    if payload.client_id is not None:
        row.client_id = payload.client_id.strip() or None
    if payload.redirect_uri is not None:
        row.redirect_uri = payload.redirect_uri.strip() or None
    if payload.webhook_public_url is not None:
        row.webhook_public_url = payload.webhook_public_url.strip() or None
    row.updated_by = user.email
    await db.commit()
    await db.refresh(row)
    await log_action(db, user=user, action="abc.config.update", entity_type="abc_integration", entity_id=str(row.id),
                     detail={"environment": row.environment, "has_client_id": bool(row.client_id)}, request=request)
    return _status_out(row, request)


@router.put("/config/secret", response_model=AbcStatusOut)
async def set_client_secret(payload: AbcSecretUpdate, request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    secret = payload.client_secret.strip()
    row.client_secret_ciphertext = encrypt_secret(secret)
    row.client_secret_last4 = secret[-4:]
    row.updated_by = user.email
    await db.commit()
    await db.refresh(row)
    await log_action(db, user=user, action="abc.config.set_secret", entity_type="abc_integration", entity_id=str(row.id), request=request)
    return _status_out(row, request)


@router.delete("/config/secret", response_model=AbcStatusOut)
async def clear_client_secret(request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    row.client_secret_ciphertext = None
    row.client_secret_last4 = None
    row.updated_by = user.email
    await db.commit()
    await db.refresh(row)
    return _status_out(row, request)


# --------------------------- OAuth connect ---------------------------
@router.post("/connect", response_model=AbcConnectOut)
async def connect(request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    if not row.client_id or (not abc_config.mock_enabled() and not row.client_secret_ciphertext):
        raise HTTPException(status_code=400, detail="Configure ABC Client ID and Client Secret before connecting.")
    redirect_uri = _effective_redirect(row, request)
    cfg = _build_cfg(row, redirect_uri=redirect_uri)
    verifier, challenge = abc_auth.generate_pkce()
    state = abc_auth.generate_state()
    row.pkce_verifier_ciphertext = encrypt_secret(verifier)
    row.oauth_state = state
    await db.commit()
    params = abc_auth.build_authorize_params(
        client_id=cfg.client_id, redirect_uri=redirect_uri, state=state,
        code_challenge=challenge, scope=abc_config.USER_SCOPES,
    )
    base = cfg.authorize_endpoint(public_base=_public_base(request))
    from urllib.parse import urlencode
    authorize_url = f"{base}?{urlencode(params)}"
    await log_action(db, user=user, action="abc.connect.start", entity_type="abc_integration", entity_id=str(row.id), request=request)
    return AbcConnectOut(authorize_url=authorize_url)


@router.get("/callback")
async def oauth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Browser redirect target from ABC. Validates state, exchanges code for tokens, stores them
    encrypted, loads the connected identity, then redirects back to the RoofSpan Settings UI."""
    public = _public_base(request)
    ui_ok = f"{public}/admin/settings/abc?abc=connected"
    ui_err = f"{public}/admin/settings/abc?abc=error"
    params = request.query_params
    err = params.get("error")
    code = params.get("code")
    state = params.get("state")
    if err:
        return RedirectResponse(url=f"{ui_err}&reason={err}", status_code=302)
    row = (await db.execute(select(AbcIntegration).where(AbcIntegration.oauth_state == state))).scalars().first()
    if not row or not state or row.oauth_state != state or not code:
        return RedirectResponse(url=f"{ui_err}&reason=invalid_state", status_code=302)

    verifier = _safe_decrypt(row.pkce_verifier_ciphertext)
    redirect_uri = _effective_redirect(row, request)
    cfg = _build_cfg(row, redirect_uri=redirect_uri)
    try:
        tok = await abc_auth.exchange_code(cfg, code=code, code_verifier=verifier or "")
    except AbcError:
        log.warning("ABC token exchange failed")
        return RedirectResponse(url=f"{ui_err}&reason=token_exchange", status_code=302)

    _store_tokens(row, tok)
    row.oauth_state = None
    row.pkce_verifier_ciphertext = None
    now = datetime.now(timezone.utc)
    row.status = "connected"
    row.connected_at = row.connected_at or now
    row.last_connected_at = now
    await db.commit()
    await db.refresh(row)

    # Best-effort: load a connected identity for display. Do not fail the connection on error.
    try:
        access = _safe_decrypt(row.access_token_ciphertext)
        client = AbcClient(cfg, access_token=access)
        ship_tos = await abc_accounts.list_ship_to_accounts(client)
        identity = {"ship_to_count": len(ship_tos)}
        if ship_tos:
            first = ship_tos[0]
            identity.update({
                "sold_to_name": (first.get("soldTo") or {}).get("name"),
                "sold_to_number": (first.get("soldTo") or {}).get("number"),
                "bill_to_number": (first.get("billTo") or {}).get("number"),
            })
        row.connected_identity = identity
        await db.commit()
    except Exception:
        log.info("ABC identity preload skipped")

    await log_action(db, user=None, action="abc.connect", entity_type="abc_integration", entity_id=str(row.id), request=request)
    return RedirectResponse(url=ui_ok, status_code=302)


@router.post("/disconnect", response_model=AbcStatusOut)
async def disconnect(request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    row.access_token_ciphertext = None
    row.refresh_token_ciphertext = None
    row.token_expires_at = None
    row.token_scopes = None
    row.oauth_state = None
    row.pkce_verifier_ciphertext = None
    row.connected_identity = None
    row.status = "not_connected"
    row.updated_by = user.email
    await db.commit()
    await db.refresh(row)
    await log_action(db, user=user, action="abc.disconnect", entity_type="abc_integration", entity_id=str(row.id), request=request)
    return _status_out(row, request)


@router.post("/test", response_model=AbcTestResult)
async def test_connection(request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    await log_action(db, user=user, action="abc.test", entity_type="abc_integration", entity_id=str(row.id), request=request)
    try:
        if row.status == "connected" and row.access_token_ciphertext:
            access = await _ensure_user_token(db, row, request)
            client = AbcClient(_build_cfg(row, redirect_uri=_effective_redirect(row, request)), access_token=access)
            ship_tos = await abc_accounts.list_ship_to_accounts(client)
            return AbcTestResult(ok=True, message=f"Connected. Found {len(ship_tos)} active ABC ship-to account(s).")
        # Not connected: try application-level (client credentials) to validate app configuration.
        if not row.client_id or not row.client_secret_ciphertext:
            return AbcTestResult(ok=False, message="Configure ABC Client ID and Client Secret, then Connect.")
        cfg = _build_cfg(row)
        tok = await abc_auth.client_credentials_token(cfg, scope=abc_config.CLIENT_CREDENTIAL_SCOPES)
        client = AbcClient(cfg, access_token=tok.get("access_token"))
        branches = await abc_locations.search_branches(client, state="WI")
        return AbcTestResult(ok=True, message=f"Application credentials valid. Location API reachable ({len(branches)} branch result(s)). Connect an account to enable pricing/ordering.")
    except AbcError as e:
        return AbcTestResult(ok=False, message=e.user_message)


# --------------------------- accounts / branches / defaults ---------------------------
@router.get("/accounts", response_model=list[AbcShipToOut])
async def list_accounts(request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    access = await _ensure_user_token(db, row, request)
    client = AbcClient(_build_cfg(row, redirect_uri=_effective_redirect(row, request)), access_token=access)
    try:
        ship_tos = await abc_accounts.list_ship_to_accounts(client)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    return [_map_ship_to(st) for st in ship_tos]


@router.get("/branches", response_model=list[AbcBranchOut])
async def list_branches(request: Request, ship_to: str | None = None, state: str | None = None,
                        user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    access = await _ensure_user_token(db, row, request)
    client = AbcClient(_build_cfg(row, redirect_uri=_effective_redirect(row, request)), access_token=access)
    try:
        if ship_to:
            # Ship-To determines eligible branches. Read them from the account record.
            st = await abc_accounts.get_ship_to(client, ship_to)
            branches = st.get("branches") or []
            return [
                AbcBranchOut(number=str(b.get("number") or ""), name=b.get("name"), storefront=b.get("storefront"),
                             status=b.get("status"), home_branch=b.get("homeBranch"))
                for b in branches
            ]
        results = await abc_locations.search_branches(client, state=state or "WI")
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    out = []
    for r in results:
        b = r.get("branch") or {}
        out.append(AbcBranchOut(
            number=str(b.get("number") or ""), name=b.get("name"), storefront=b.get("storefront"),
            status=b.get("status"), distance=b.get("distance"), address=r.get("address"),
        ))
    return out


@router.put("/defaults", response_model=AbcStatusOut)
async def set_defaults(payload: AbcDefaultsUpdate, request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    if payload.default_ship_to_number is not None:
        row.default_ship_to_number = payload.default_ship_to_number.strip() or None
        await log_action(db, user=user, action="abc.account.select", entity_type="abc_integration", entity_id=str(row.id),
                         detail={"ship_to": row.default_ship_to_number}, request=request)
    if payload.default_branch_number is not None:
        row.default_branch_number = payload.default_branch_number.strip() or None
        await log_action(db, user=user, action="abc.branch.select", entity_type="abc_integration", entity_id=str(row.id),
                         detail={"branch": row.default_branch_number}, request=request)
    row.updated_by = user.email
    await db.commit()
    await db.refresh(row)
    return _status_out(row, request)


# --------------------------- products / pricing (Phase 2) ---------------------------
async def _connected_client(db: AsyncSession, request: Request) -> AbcClient:
    row = await _get_or_create(db)
    access = await _ensure_user_token(db, row, request)
    return AbcClient(_build_cfg(row, redirect_uri=_effective_redirect(row, request)), access_token=access)


def _map_product(item: dict, branch_number: str | None) -> AbcProductOut:
    hier = item.get("hierarchy") or {}
    pg = hier.get("productGroup") or {}
    cat = (pg.get("category") or {}).get("label") if isinstance(pg.get("category"), dict) else None
    color = item.get("color") or {}
    return AbcProductOut(
        item_number=str(item.get("itemNumber") or ""),
        description=item.get("itemDescription"),
        family_id=item.get("familyId"),
        family_name=item.get("familyName"),
        manufacturer=item.get("manufacturer"),
        is_dimensional=bool(item.get("isDimensional")),
        uoms=item.get("uoms") or [],
        color=color.get("name") if isinstance(color, dict) else None,
        product_family=pg.get("label") or cat,
        image_url=abc_products.primary_image_href(item),
        available_at_branch=abc_products.item_available_at_branch(item, branch_number) if branch_number else None,
        branch_number=branch_number,
    )


@router.post("/products/search", response_model=list[AbcProductOut])
async def product_search(payload: AbcProductSearchIn, request: Request,
                         user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    client = await _connected_client(db, request)
    try:
        data = await abc_products.search_items(
            client, query=payload.query, by=payload.by, family_id=payload.family_id,
            branch_number=payload.branch_number, embed_branches=True, page_number=payload.page,
        )
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    row = await _get_or_create(db)
    await log_action(db, user=user, action="abc.product.search", entity_type="abc_integration", entity_id=str(row.id),
                     detail={"query": (payload.query or payload.family_id or "")[:120]}, request=request)
    return [_map_product(it, payload.branch_number) for it in (data.get("items") or [])]


@router.get("/products/{item_number}", response_model=AbcProductOut)
async def product_detail(item_number: str, request: Request, branch_number: str | None = None,
                         user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    client = await _connected_client(db, request)
    try:
        item = await abc_products.get_item(client, item_number)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    row = await _get_or_create(db)
    await log_action(db, user=user, action="abc.product.view", entity_type="abc_integration", entity_id=str(row.id),
                     detail={"item": item_number}, request=request)
    return _map_product(item, branch_number)


@router.get("/products/{item_number}/image")
async def product_image(item_number: str, request: Request, href: str,
                        user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """Lazy image proxy: fetches the ABC image href with the user token so the browser never sees the token.
    Only ABC hosts (or the local mock) are allowed."""
    row = await _get_or_create(db)
    cfg = _build_cfg(row)
    allowed = href.startswith(cfg.api_base) or "abcsupply.com" in href
    if not allowed:
        raise HTTPException(status_code=400, detail="Invalid image host")
    access = await _ensure_user_token(db, row, request)
    import httpx
    from fastapi.responses import Response
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(href, headers={"Authorization": f"Bearer {access}"})
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not load product image")
    if r.status_code != 200:
        raise HTTPException(status_code=404, detail="Image unavailable")
    return Response(content=r.content, media_type=r.headers.get("content-type", "image/png"))


@router.post("/pricing")
async def price(payload: AbcPriceIn, request: Request,
                user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    if not payload.lines:
        raise HTTPException(status_code=400, detail="No lines to price")
    client = await _connected_client(db, request)
    lines = [
        abc_pricing.build_line(line_id=l.id, item_number=l.item_number, quantity=l.quantity, uom=l.uom,
                               length_value=l.length_value, length_uom=l.length_uom)
        for l in payload.lines
    ]
    try:
        result = await abc_pricing.price_items(client, ship_to_number=payload.ship_to_number,
                                               branch_number=payload.branch_number, lines=lines, purpose=payload.purpose)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    row = await _get_or_create(db)
    await log_action(db, user=user, action="abc.price.lookup", entity_type="abc_integration", entity_id=str(row.id),
                     detail={"count": len(result)}, request=request)
    return {"lines": result}


# --------------------------- orders: history / detail / templates (Phase 3, read-only) ---------------------------
@router.get("/orders/history")
async def order_history(request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    from integrations.abc_supply import orders as abc_orders
    row = await _get_or_create(db)
    client = await _connected_client(db, request)
    try:
        orders = await abc_orders.get_order_history(client, ship_to=row.default_ship_to_number, branch=row.default_branch_number)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    return {"orders": orders}


@router.get("/orders/{confirmation_number}")
async def order_detail(confirmation_number: str, request: Request,
                       user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    from integrations.abc_supply import orders as abc_orders
    client = await _connected_client(db, request)
    try:
        return await abc_orders.get_order_by_confirmation(client, confirmation_number)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)


@router.get("/templates")
async def order_templates(request: Request, user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    from integrations.abc_supply import orders as abc_orders
    client = await _connected_client(db, request)
    try:
        return {"templates": await abc_orders.list_templates(client)}
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
