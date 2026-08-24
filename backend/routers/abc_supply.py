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

from db import get_db, SessionLocal
from models import AbcIntegration, User, Material, AbcCatalogItem, AbcCatalogSync, AbcAccountLink
from core import require_roles, SENSITIVE_ROLES, MANAGE_ROLES, encrypt_secret, decrypt_secret, log_action
from integrations.abc_supply import config as abc_config
from integrations.abc_supply import auth as abc_auth
from integrations.abc_supply.client import AbcClient
from integrations.abc_supply import accounts as abc_accounts
from integrations.abc_supply import locations as abc_locations
from integrations.abc_supply import products as abc_products
from integrations.abc_supply import pricing as abc_pricing
from integrations.abc_supply import catalog as abc_catalog
from services import inventory_core as inv_core
from integrations.abc_supply.exceptions import AbcError, AbcAuthError, AbcNotConfigured
from integrations.abc_supply.schemas import (
    AbcConfigUpdate, AbcSecretUpdate, AbcDefaultsUpdate, AbcStatusOut, AbcConnectOut,
    AbcTestResult, AbcShipToOut, AbcBranchOut, AbcProductSearchIn, AbcProductOut, AbcPriceIn,
    AbcCatalogItemOut, AbcCatalogContext, AbcCatalogListOut, AbcCatalogSyncOut,
    AbcAddToInventoryIn, AbcAddToInventoryOut,
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


@router.get("/go-live-check")
async def go_live_check(user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """One-click Production readiness check for ABC Supply — confirms the environment is Production,
    the mock is OFF, app credentials exist, the OAuth connection is live with the required scopes, and
    (recommended) default Ship-To/branch are set. `ready` is true only when all CRITICAL checks pass."""
    row = await _get_or_create(db)
    scopes = set((row.token_scopes or "").replace(",", " ").split())
    required_scopes = ["pricing.read", "order.read", "order.write", "account.read"]
    missing = [s for s in required_scopes if s not in scopes]
    checks = [
        {"key": "environment", "label": "Environment is Production", "severity": "critical",
         "ok": row.environment == "production",
         "detail": f"Currently: {row.environment}." + ("" if row.environment == "production"
                   else " Switch to Production in ABC Supply settings.")},
        {"key": "mock_off", "label": "Live ABC mode (mock disabled)", "severity": "critical",
         "ok": not abc_config.mock_enabled(),
         "detail": "ABC mock is ON — real orders/pricing are simulated." if abc_config.mock_enabled()
                   else "Requests go to the live ABC Supply API."},
        {"key": "credentials", "label": "Production app credentials entered", "severity": "critical",
         "ok": bool(row.client_id) and bool(row.client_secret_ciphertext),
         "detail": "Client ID and Secret are set." if (row.client_id and row.client_secret_ciphertext)
                   else "Enter the Production Client ID and Secret."},
        {"key": "connected", "label": "Connected to ABC Supply", "severity": "critical",
         "ok": row.status == "connected",
         "detail": f"Connection status: {row.status}." + ("" if row.status == "connected" else " Click Connect to authorize."),
         },
        {"key": "identity", "label": "Authorized ABC account", "severity": "info",
         "ok": bool(row.connected_identity),
         "detail": (f"Connected as {row.connected_identity}." if row.connected_identity else "No connected identity yet.")},
        {"key": "scopes", "label": "Required permissions granted", "severity": "critical",
         "ok": row.status == "connected" and not missing,
         "detail": ("All required scopes granted." if not missing
                    else f"Reconnect to grant: {', '.join(missing)}.") if row.status == "connected"
                    else "Connect first to verify granted scopes."},
        {"key": "defaults", "label": "Default Ship-To and branch set", "severity": "recommended",
         "ok": bool(row.default_ship_to_number) and bool(row.default_branch_number),
         "detail": (f"Ship-To {row.default_ship_to_number}, branch {row.default_branch_number}."
                    if (row.default_ship_to_number and row.default_branch_number)
                    else "Set defaults so new ABC orders are pre-filled.")},
    ]
    ready = all(c["ok"] for c in checks if c["severity"] == "critical")
    return {"ready": ready, "environment": row.environment, "is_mock": abc_config.mock_enabled(),
            "checks": checks}


@router.put("/config", response_model=AbcStatusOut)
async def update_config(payload: AbcConfigUpdate, request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    env_changed = False
    if payload.environment is not None:
        env = payload.environment.strip().lower()
        if env not in abc_config.DEFAULT_BASES:
            raise HTTPException(status_code=422, detail="environment must be 'sandbox' or 'production'")
        if env != row.environment:
            env_changed = True
        row.environment = env
    if env_changed:
        # ABC registers separate apps + issues environment-specific tokens for Sandbox vs Production.
        # Switching environments invalidates the old credentials, so force a clean reconnect: clear the
        # client_id/secret and any tokens and require the production app credentials to be re-entered.
        row.client_id = None
        row.client_secret_ciphertext = None
        row.client_secret_last4 = None
        row.access_token_ciphertext = None
        row.refresh_token_ciphertext = None
        row.token_expires_at = None
        row.token_scopes = None
        row.connected_identity = None
        row.connected_at = None
        row.status = "not_connected"
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
                     detail={"environment": row.environment, "has_client_id": bool(row.client_id),
                             "environment_switched": env_changed}, request=request)
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
            # Prefer the branch list from the account SEARCH result (this is what populated the
            # Ship-To picker). ABC's Ship-To DETAIL endpoint sometimes omits branches, which would
            # otherwise leave the branch picker empty. Fall back to detail, then Location search.
            branches: list[dict] = []
            try:
                ship_tos = await abc_accounts.list_ship_to_accounts(client)
                match = next((s for s in ship_tos if str(s.get("number")) == str(ship_to)), None)
                branches = (match or {}).get("branches") or []
            except AbcError:
                branches = []
            if not branches:
                st = await abc_accounts.get_ship_to(client, ship_to)
                branches = st.get("branches") or []
                if not branches:
                    state = (st.get("address") or {}).get("state")
                    if state:
                        results = await abc_locations.search_branches(client, state=state)
                        return [
                            AbcBranchOut(
                                number=str((r.get("branch") or {}).get("number") or ""),
                                name=(r.get("branch") or {}).get("name"),
                                storefront=(r.get("branch") or {}).get("storefront"),
                                status=(r.get("branch") or {}).get("status"),
                                distance=(r.get("branch") or {}).get("distance"),
                                address=r.get("address"),
                            ) for r in results
                        ]
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
    try:
        lines = [
            abc_pricing.build_line(line_id=l.id, item_number=l.item_number, quantity=l.quantity, uom=l.uom,
                                   length_value=l.length_value, length_uom=l.length_uom)
            for l in payload.lines
        ]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        result = await abc_pricing.price_items(client, ship_to_number=payload.ship_to_number,
                                               branch_number=payload.branch_number, lines=lines,
                                               purpose=payload.purpose, request_id=payload.request_id)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    row = await _get_or_create(db)
    await log_action(db, user=user, action="abc.price.lookup", entity_type="abc_integration", entity_id=str(row.id),
                     detail={"count": len(result)}, request=request)
    return {"lines": result}


# --------------------------- orders: history / detail / templates (Phase 3, read-only) ---------------------------
@router.get("/orders/history")
async def order_history(request: Request, start_date: str | None = None, end_date: str | None = None,
                        page_number: int = 1, items_per_page: int = 20,
                        user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """ABC account-level order history (documented Order v2 /orders/orderHistory). Preserves pagination."""
    from integrations.abc_supply import orders as abc_orders
    client = await _connected_client(db, request)
    try:
        result = await abc_orders.get_order_history(
            client, start_date=start_date, end_date=end_date,
            page_number=page_number, items_per_page=items_per_page)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    items = result["items"]
    # Strong-identifier matching back to RoofSpan POs (never assume every ABC order originated here):
    # match each history row's ABC orderNumber against PurchaseOrder.external_order_number.
    from models import PurchaseOrder as _PO
    onums = [str(it.get("orderNumber")) for it in items if it.get("orderNumber")]
    matches: dict[str, _PO] = {}
    if onums:
        rows = (await db.execute(select(_PO).where(_PO.external_order_number.in_(onums)).order_by(_PO.created_at.asc()))).scalars().all()
        matches = {str(p.external_order_number): p for p in rows}  # asc order -> most recent PO wins
    for it in items:
        p = matches.get(str(it.get("orderNumber")))
        it["roofspan_po_id"] = str(p.id) if p else None
        it["roofspan_po_number"] = p.number if p else None
        it["roofspan_matched"] = bool(p)
    return {"pagination": result["pagination"], "items": items}


@router.get("/orders/{identifier}")
async def order_detail(identifier: str, request: Request,
                       user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """Get ABC order by confirmation number OR order number (documented Get Order, both forms).
    Also attaches a strong-identifier match back to a RoofSpan PO when one exists."""
    from integrations.abc_supply import orders as abc_orders
    from models import PurchaseOrder as _PO
    client = await _connected_client(db, request)
    try:
        data = await abc_orders.get_order_by_confirmation(client, identifier)
        if not data:
            data = await abc_orders.get_order_by_number(client, identifier)
    except AbcError:
        try:
            data = await abc_orders.get_order_by_number(client, identifier)
        except AbcError as e:
            raise HTTPException(status_code=502, detail=e.user_message)
    if isinstance(data, dict):
        conf = data.get("confirmation_number")
        onum = data.get("order_number")
        p = None
        conds = []
        if conf:
            conds.append(_PO.external_confirmation_number == conf)
        if onum:
            conds.append(_PO.external_order_number == onum)
        if conds:
            p = (await db.execute(select(_PO).where(or_(*conds)).order_by(_PO.created_at.desc()))).scalars().first()
        data["roofspan_po_id"] = str(p.id) if p else None
        data["roofspan_po_number"] = p.number if p else None
        data["roofspan_matched"] = bool(p)
    return data


@router.get("/templates")
async def order_templates(request: Request, account_number: str | None = None, page_number: int = 1,
                          items_per_page: int = 40,
                          user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """ABC order templates for the connected Bill-To account (read-only). Preserves pagination."""
    from integrations.abc_supply import orders as abc_orders
    row = await _get_or_create(db)
    acct = account_number or getattr(row, "default_bill_to_number", None) or getattr(row, "default_ship_to_number", None)
    client = await _connected_client(db, request)
    try:
        result = await abc_orders.list_templates(
            client, account_number=acct, page_number=page_number, items_per_page=items_per_page)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    return {"templates": result["templates"], "pagination": result["pagination"]}


@router.get("/templates/{template_id}")
async def order_template_detail(template_id: str, request: Request,
                                user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """Full ABC order template detail (documented get-order-template-by-id), normalized for display + conversion."""
    from integrations.abc_supply import orders as abc_orders
    client = await _connected_client(db, request)
    try:
        raw = await abc_orders.get_template(client, template_id)
        return abc_orders.normalize_template(raw)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)


# --------------------------- vendor catalog (Inventory) ---------------------------
from sqlalchemy import or_, func  # noqa: E402


async def _catalog_context(db: AsyncSession, row: AbcIntegration, branch_override: str | None) -> AbcCatalogContext:
    ship_to = row.default_ship_to_number
    branch = branch_override or row.default_branch_number
    ship_to_name = None
    if ship_to:
        link = (await db.execute(select(AbcAccountLink).where(AbcAccountLink.ship_to_number == ship_to))).scalars().first()
        ship_to_name = link.ship_to_name if link else None
    connected = row.status == "connected" and bool(row.access_token_ciphertext)
    return AbcCatalogContext(
        connected=connected, ship_to_number=ship_to, ship_to_name=ship_to_name, branch_number=branch,
        needs_ship_to=(connected and not ship_to), needs_branch=(connected and not branch),
    )


async def _existing_material_numbers(db: AsyncSession) -> set[str]:
    rows = (await db.execute(select(Material.abc_item_number).where(Material.abc_item_number.isnot(None)))).scalars().all()
    return {str(n) for n in rows if n}


def _catalog_out_from_row(r: AbcCatalogItem, branch: str | None, in_inventory: bool) -> AbcCatalogItemOut:
    branches = r.branch_numbers or []
    available = (str(branch) in [str(b) for b in branches]) if branch else None
    return AbcCatalogItemOut(
        id=str(r.id), item_number=r.abc_item_number, description=r.description, manufacturer=r.manufacturer,
        brand=r.brand, category=r.category, family_id=r.family_id, family_name=r.family_name,
        unit_of_measure=r.unit_of_measure, uoms=r.uoms or [], status=r.status, is_dimensional=r.is_dimensional,
        image_url=r.image_url, available_at_branch=available, branch_number=branch,
        in_inventory=in_inventory or bool(r.material_id), material_id=(str(r.material_id) if r.material_id else None),
    )


def _catalog_out_from_raw(item: dict, branch: str | None, existing: set[str]) -> AbcCatalogItemOut:
    fields = abc_catalog.map_catalog_fields(item)
    num = fields["abc_item_number"]
    branches = fields.get("branch_numbers") or []
    available = (str(branch) in [str(b) for b in branches]) if branch else None
    return AbcCatalogItemOut(
        id=None, item_number=num, description=fields.get("description"), manufacturer=fields.get("manufacturer"),
        brand=fields.get("brand"), category=fields.get("category"), family_id=fields.get("family_id"),
        family_name=fields.get("family_name"), unit_of_measure=fields.get("unit_of_measure"),
        uoms=fields.get("uoms") or [], status=fields.get("status") or "active",
        is_dimensional=bool(fields.get("is_dimensional")), image_url=fields.get("image_url"),
        available_at_branch=available, branch_number=branch, in_inventory=(num in existing), material_id=None,
    )


@router.get("/catalog", response_model=AbcCatalogListOut)
async def catalog_list(request: Request, q: str | None = None, page: int = 1, page_size: int = 25,
                       category: str | None = None, active_only: bool = True, branch: str | None = None,
                       live: bool = False, user: User = Depends(require_roles(*MANAGE_ROLES)),
                       db: AsyncSession = Depends(get_db)):
    """Browse/search the ABC vendor catalog. Serves the local cache by default (fast, paginated); set
    live=true (or when the cache is empty) to query ABC directly and warm the cache. ABC availability is
    branch-specific and is NEVER RoofSpan on-hand stock."""
    row = await _get_or_create(db)
    ctx = await _catalog_context(db, row, branch)
    page = max(1, page)
    page_size = min(max(page_size, 1), 100)
    eff_branch = ctx.branch_number
    cache_count = (await db.execute(select(func.count(AbcCatalogItem.id)))).scalar() or 0

    use_live = (live or cache_count == 0) and ctx.connected
    if use_live:
        client = await _connected_client(db, request)
        try:
            data = await abc_products.search_items(client, query=q, by="itemDescription",
                                                   branch_number=(branch if branch else None),
                                                   embed_branches=True, page_number=page, items_per_page=page_size)
        except AbcError as e:
            raise HTTPException(status_code=502, detail=e.user_message)
        items_raw = data.get("items") or []
        for it in items_raw:  # opportunistic cache warm (best-effort)
            try:
                await abc_catalog.upsert_catalog_item(db, it)
            except Exception:
                pass
        await db.commit()
        existing = await _existing_material_numbers(db)
        out = [_catalog_out_from_raw(it, eff_branch, existing) for it in items_raw]
        if active_only:
            out = [o for o in out if o.status == "active"]
        if category:
            out = [o for o in out if (o.category or "").lower() == category.lower()]
        pg = data.get("pagination") or {}
        await log_action(db, user=user, action="abc.catalog.search", entity_type="abc_integration", entity_id=str(row.id),
                         detail={"q": (q or "")[:120], "source": "live"}, request=request)
        return AbcCatalogListOut(items=out, page=page, page_size=page_size, total=pg.get("totalItems"),
                                 total_pages=pg.get("totalPages"), source="live", context=ctx)

    # ---- local cache browse ----
    stmt = select(AbcCatalogItem)
    count_stmt = select(func.count(AbcCatalogItem.id))
    conds = []
    if active_only:
        conds.append(AbcCatalogItem.status == "active")
    if category:
        conds.append(func.lower(AbcCatalogItem.category) == category.lower())
    if q:
        like = f"%{q}%"
        conds.append(or_(AbcCatalogItem.description.ilike(like), AbcCatalogItem.abc_item_number.ilike(like),
                         AbcCatalogItem.manufacturer.ilike(like)))
    for c in conds:
        stmt = stmt.where(c)
        count_stmt = count_stmt.where(c)
    total = (await db.execute(count_stmt)).scalar() or 0
    stmt = stmt.order_by(AbcCatalogItem.description.asc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    existing = await _existing_material_numbers(db)
    out = [_catalog_out_from_row(r, eff_branch, r.abc_item_number in existing) for r in rows]
    total_pages = max(1, (int(total) + page_size - 1) // page_size)
    return AbcCatalogListOut(items=out, page=page, page_size=page_size, total=int(total),
                             total_pages=total_pages, source="cache", context=ctx)


@router.get("/catalog/sync/status", response_model=AbcCatalogSyncOut)
async def catalog_sync_status(user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    sync = await abc_catalog.get_sync_row(db)
    return AbcCatalogSyncOut(status=sync.status, last_synced_at=sync.last_synced_at,
                             last_full_sync_at=sync.last_full_sync_at, items_synced=sync.items_synced,
                             total_items=sync.total_items, last_error=sync.last_error, started_at=sync.started_at)


async def _run_sync_task(full: bool, started_by: str | None):
    """Background catalog sync with its own DB session + client (survives request lifecycle)."""
    async with SessionLocal() as db:
        try:
            row = await _get_or_create(db)
            if row.status != "connected" or not row.access_token_ciphertext:
                sync = await abc_catalog.get_sync_row(db)
                sync.status = "failed"; sync.last_error = "ABC Supply is not connected."
                await db.commit()
                return
            access = _safe_decrypt(row.access_token_ciphertext)
            client = AbcClient(_build_cfg(row), access_token=access)
            await abc_catalog.run_sync(db, client, full=full, started_by=started_by)
        except Exception as exc:  # noqa: BLE001
            try:
                sync = await abc_catalog.get_sync_row(db)
                sync.status = "failed"; sync.last_error = str(exc)[:480]
                await db.commit()
            except Exception:
                pass


@router.post("/catalog/sync", response_model=AbcCatalogSyncOut)
async def catalog_sync(request: Request, full: bool = False, user: User = Depends(require_roles(*MANAGE_ROLES)),
                       db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    if row.status != "connected" or not row.access_token_ciphertext:
        raise HTTPException(status_code=400, detail="Connect ABC Supply before synchronizing the catalog.")
    sync = await abc_catalog.get_sync_row(db)
    if sync.status == "syncing":
        raise HTTPException(status_code=409, detail="A catalog sync is already in progress.")
    # Full sync when explicitly requested OR when there has never been a successful full sync.
    do_full = full or sync.last_full_sync_at is None
    await log_action(db, user=user, action="abc.catalog.sync", entity_type="abc_integration", entity_id=str(row.id),
                     detail={"full": do_full}, request=request)
    import asyncio
    asyncio.create_task(_run_sync_task(do_full, user.email))
    return AbcCatalogSyncOut(status="syncing", last_synced_at=sync.last_synced_at,
                             last_full_sync_at=sync.last_full_sync_at, items_synced=sync.items_synced,
                             total_items=sync.total_items, last_error=None, started_at=datetime.now(timezone.utc))


@router.get("/catalog/{item_number}", response_model=AbcCatalogItemOut)
async def catalog_detail(item_number: str, request: Request, branch: str | None = None,
                         user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    row = await _get_or_create(db)
    ctx = await _catalog_context(db, row, branch)
    eff_branch = ctx.branch_number
    cached = (await db.execute(select(AbcCatalogItem).where(AbcCatalogItem.abc_item_number == item_number))).scalars().first()
    existing = await _existing_material_numbers(db)
    if cached:
        return _catalog_out_from_row(cached, eff_branch, cached.abc_item_number in existing)
    if not ctx.connected:
        raise HTTPException(status_code=404, detail="Product not found in local catalog. Sync or connect ABC Supply.")
    client = await _connected_client(db, request)
    try:
        item = await abc_products.get_item(client, item_number)
    except AbcError as e:
        raise HTTPException(status_code=502, detail=e.user_message)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        await abc_catalog.upsert_catalog_item(db, item)
        await db.commit()
    except Exception:
        await db.rollback()
    return _catalog_out_from_raw(item, eff_branch, existing)


@router.post("/catalog/{item_number}/add-to-inventory", response_model=AbcAddToInventoryOut)
async def catalog_add_to_inventory(item_number: str, payload: AbcAddToInventoryIn, request: Request,
                                   user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """Create or link a RoofSpan Material from an ABC catalog item, preserving the ABC identity for future
    pricing/ordering. Never duplicates: if this ABC item already maps to a Material, returns it unchanged.
    ABC branch availability is NOT written to quantity_on_hand (defaults to 0 per existing inventory rules)."""
    row = await _get_or_create(db)
    # Ensure we have the catalog row (fetch live if needed and connected).
    cat = (await db.execute(select(AbcCatalogItem).where(AbcCatalogItem.abc_item_number == item_number))).scalars().first()
    if not cat:
        if row.status != "connected" or not row.access_token_ciphertext:
            raise HTTPException(status_code=404, detail="Product not in local catalog. Sync the ABC catalog first.")
        client = await _connected_client(db, request)
        try:
            item = await abc_products.get_item(client, item_number)
        except AbcError as e:
            raise HTTPException(status_code=502, detail=e.user_message)
        if not item:
            raise HTTPException(status_code=404, detail="ABC product not found")
        cat, _ = await abc_catalog.upsert_catalog_item(db, item)
        await db.commit()
        await db.refresh(cat)

    # Already linked? (durable ABC↔RoofSpan mapping — never create a second identity)
    existing = None
    if cat.material_id:
        existing = await db.get(Material, cat.material_id)
    if not existing:
        existing = (await db.execute(select(Material).where(Material.abc_item_number == item_number))).scalars().first()
    if existing:
        if not cat.material_id:
            cat.material_id = existing.id
        # Backfill master identity from the ABC catalog when the material is missing it (never
        # clobber a value the user already curated).
        if cat.manufacturer and not existing.manufacturer:
            existing.manufacturer = cat.manufacturer
        if cat.brand and not existing.brand:
            existing.brand = cat.brand
        # Ensure the ABC supplier mapping exists for this (possibly pre-existing) material.
        sup = await inv_core.ensure_supplier(db, "ABC Supply", integration_provider="abc_supply")
        await inv_core.upsert_supplier_material(
            db, material_id=existing.id, supplier_id=sup.id, integration_provider="abc_supply",
            external_item_id=item_number, supplier_item_number=item_number,
            supplier_description=cat.description, supplier_uom=cat.unit_of_measure,
            availability_status=("available" if (cat.branch_numbers and row.default_branch_number in [str(b) for b in cat.branch_numbers]) else None),
            meta={"family_id": cat.family_id, "brand": cat.brand, "manufacturer": cat.manufacturer})
        await db.commit()
        return AbcAddToInventoryOut(material_id=str(existing.id), material_name=existing.name, created=False,
                                    already_linked=True, abc_item_number=item_number)

    # Create a new material. Resolve a unique name (avoid clashing with an existing manually-created name).
    base_name = (payload.name_override or cat.description or item_number).strip()[:240]
    name = base_name
    clash = (await db.execute(select(Material).where(func.lower(Material.name) == name.lower()))).scalars().first()
    if clash:
        name = f"{base_name} (ABC {item_number})"[:250]
    mat = Material(
        name=name, sku=item_number, category=cat.category, unit=(cat.unit_of_measure or "each"),
        description=cat.description, active=True, quantity_on_hand=0, reorder_threshold=0,
        manufacturer=cat.manufacturer, brand=cat.brand,
        vendor="ABC Supply", abc_item_number=item_number, abc_catalog_item_id=cat.id,
        abc_uom=cat.unit_of_measure,
        abc_metadata={"family_id": cat.family_id, "family_name": cat.family_name, "manufacturer": cat.manufacturer,
                      "brand": cat.brand, "is_dimensional": cat.is_dimensional, "uoms": cat.uoms,
                      "branch_numbers": cat.branch_numbers, "image_url": cat.image_url},
        created_by=user.email,
    )
    db.add(mat)
    await db.commit()
    await db.refresh(mat)
    cat.material_id = mat.id
    # Create the generic ABC supplier↔material mapping (source of truth going forward; preferred if first).
    sup = await inv_core.ensure_supplier(db, "ABC Supply", integration_provider="abc_supply")
    await inv_core.upsert_supplier_material(
        db, material_id=mat.id, supplier_id=sup.id, integration_provider="abc_supply",
        external_item_id=item_number, supplier_item_number=item_number,
        supplier_description=cat.description, supplier_uom=cat.unit_of_measure,
        availability_status=("available" if (cat.branch_numbers and row.default_branch_number in [str(b) for b in cat.branch_numbers]) else None),
        meta={"family_id": cat.family_id, "family_name": cat.family_name, "manufacturer": cat.manufacturer,
              "brand": cat.brand, "is_dimensional": cat.is_dimensional})
    await db.commit()
    await log_action(db, user=user, action="abc.catalog.add_to_inventory", entity_type="material", entity_id=mat.id,
                     detail={"abc_item_number": item_number}, request=request)
    return AbcAddToInventoryOut(material_id=str(mat.id), material_name=mat.name, created=True,
                                already_linked=False, abc_item_number=item_number)
