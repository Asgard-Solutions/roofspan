"""Production operator (RoofSpan-internal) authentication for Control Plane admin endpoints.

Dev keeps the isolated X-RoofSpan-Admin header (handled in router). Production requires a Cognito
operator JWT (Bearer). Verification uses PyJWT + the Cognito JWKS; misconfiguration fails clearly and
NEVER silently allows access. This is internal operator auth, not customer SSO.
"""
from __future__ import annotations

from fastapi import HTTPException

from control_plane import config

_jwks_client = None


def _issuer_jwks_url() -> str:
    return f"{config.CP_OPERATOR_ISSUER}/.well-known/jwks.json"


def verify_operator(authorization: str | None) -> bool:
    if not (config.CP_OPERATOR_ISSUER and config.CP_OPERATOR_AUDIENCE):
        raise HTTPException(status_code=500, detail="Operator auth not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Operator bearer token required")
    token = authorization.split(" ", 1)[1].strip()
    try:
        import jwt
        from jwt import PyJWKClient

        global _jwks_client
        if _jwks_client is None:
            _jwks_client = PyJWKClient(_issuer_jwks_url())
        key = _jwks_client.get_signing_key_from_jwt(token).key
        jwt.decode(token, key, algorithms=["RS256"], audience=config.CP_OPERATOR_AUDIENCE,
                   issuer=config.CP_OPERATOR_ISSUER)
        return True
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Invalid operator token") from e
