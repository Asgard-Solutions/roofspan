"""ABC Supply OAuth 2.0 helpers (Authorization Code + PKCE, refresh, client credentials).

Pure HTTP/crypto helpers with NO database access. Token persistence is handled by the
router against local PostgreSQL (encrypted). Follows the documented ABC/Okta flow:
- authorize: GET {oauth_base}/v1/authorize?response_type=code&client_id&redirect_uri&state&code_challenge&code_challenge_method=S256&scope
- token:     POST {oauth_base}/v1/token   (HTTP Basic clientId:clientSecret, x-www-form-urlencoded)

Never log tokens, codes, verifiers, or client secrets.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets

import httpx

from .config import AbcConfig
from .exceptions import AbcAuthError, AbcTransportError


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256."""
    verifier = _b64url(os.urandom(48))  # 43-128 chars, URL-safe
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def verify_pkce(verifier: str, challenge: str) -> bool:
    expected = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return secrets.compare_digest(expected, challenge or "")


def build_authorize_params(*, client_id: str, redirect_uri: str, state: str, code_challenge: str, scope: str) -> dict:
    return {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "scope": scope,
    }


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


async def _post_token(cfg: AbcConfig, data: dict, transport=None) -> dict:
    if not cfg.client_id or not cfg.client_secret:
        raise AbcAuthError("ABC Supply client credentials are not configured.")
    headers = {
        "Authorization": _basic_auth_header(cfg.client_id, cfg.client_secret),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20, transport=transport) as client:
            resp = await client.post(cfg.token_url, data=data, headers=headers)
    except httpx.HTTPError as exc:  # transport failure
        raise AbcTransportError("Could not reach ABC Supply to obtain a token.") from exc
    if resp.status_code != 200:
        # Do not echo the raw body (may contain sensitive hints); keep a short sanitized detail.
        raise AbcAuthError(
            "ABC Supply rejected the authorization request.",
            status=resp.status_code,
            detail=f"token endpoint returned {resp.status_code}",
        )
    return resp.json()


async def exchange_code(cfg: AbcConfig, *, code: str, code_verifier: str, transport=None) -> dict:
    data = {
        "grant_type": "authorization_code",
        "redirect_uri": cfg.redirect_uri or "",
        "code": code,
        "code_verifier": code_verifier,
    }
    return await _post_token(cfg, data, transport=transport)


async def refresh_token(cfg: AbcConfig, *, refresh: str, scope: str, transport=None) -> dict:
    data = {"grant_type": "refresh_token", "refresh_token": refresh, "scope": scope}
    return await _post_token(cfg, data, transport=transport)


async def client_credentials_token(cfg: AbcConfig, *, scope: str, transport=None) -> dict:
    data = {"grant_type": "client_credentials", "scope": scope}
    return await _post_token(cfg, data, transport=transport)
