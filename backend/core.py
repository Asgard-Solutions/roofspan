import os
import base64
import secrets
from datetime import datetime, timezone, timedelta

import jwt
import bcrypt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User, AuditLog

# ---- Roles ----
ROLES = ["owner", "administrator", "office", "sales"]
SENSITIVE_ROLES = ["owner", "administrator"]  # manage users, settings, integrations, audit
MANAGE_ROLES = ["owner", "administrator", "office"]  # manage territories, run imports
FIELD_ROLES = ["owner", "administrator", "office", "sales"]  # field work: visits, DNK, leads

JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))

_bearer = HTTPBearer(auto_error=False)


# ---- Passwords ----
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


# ---- JWT ----
def _secret() -> str:
    return os.environ["JWT_SECRET"]


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


# ---- Refresh tokens (long-lived; rotated with reuse detection) ----
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "60"))


def new_token_id() -> str:
    """Opaque, unguessable id used for a refresh token's jti / rotation family."""
    return secrets.token_hex(16)


def create_refresh_token(user_id: str, jti: str, family_id: str):
    """Return (signed_refresh_jwt, expires_at). The jti is tracked server-side so the token is
    revocable and rotated with reuse detection."""
    expires = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "family": family_id,
        "type": "refresh",
        "exp": expires,
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM), expires


def decode_refresh_token(token: str) -> dict:
    """Decode + verify a refresh token JWT. Raises jwt.InvalidTokenError / ExpiredSignatureError."""
    payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("not a refresh token")
    return payload


# ---- Secret encryption (AES-GCM) ----
def _enc_key() -> bytes:
    return base64.urlsafe_b64decode(os.environ["SECRETS_ENCRYPTION_KEY"])


def encrypt_secret(plaintext: str) -> str:
    aes = AESGCM(_enc_key())
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("utf-8")


def decrypt_secret(token: str) -> str:
    raw = base64.b64decode(token)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(_enc_key()).decrypt(nonce, ct, None).decode("utf-8")


# ---- Current user dependency ----
async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = creds.credentials if creds else None
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def require_roles(*roles: str):
    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
        return user

    return checker


# ---- Audit ----
async def log_action(
    db: AsyncSession,
    *,
    user: User | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    detail: dict | None = None,
    request: Request | None = None,
):
    ip = None
    if request is not None:
        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
        if ip and "," in ip:
            ip = ip.split(",")[0].strip()
    entry = AuditLog(
        user_id=user.id if user else None,
        user_email=user.email if user else "",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        detail=detail,
        ip_address=ip,
    )
    db.add(entry)
    await db.commit()
