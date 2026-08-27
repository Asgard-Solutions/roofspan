import os
from datetime import datetime, timezone, timedelta

import jwt
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User, RefreshToken
from core import (
    verify_password, create_access_token, get_current_user, log_action,
    create_refresh_token, decode_refresh_token, new_token_id,
)
from schemas import LoginRequest, TokenResponse, UserOut, RefreshRequest, LogoutRequest
from schemas_phase2 import ChangePasswordIn
from core import hash_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Simple in-memory brute-force tracking (local single-instance app)
_attempts: dict[str, list] = {}
MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _client_ip(request: Request) -> str:
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    return ip.split(",")[0].strip() if ip else "unknown"


def _to_user_out(u: User) -> UserOut:
    return UserOut(
        id=str(u.id), email=u.email, full_name=u.full_name,
        role=u.role, is_active=u.is_active, created_at=u.created_at,
    )


async def _issue_refresh_token(db: AsyncSession, user: User, request: Request, family_id: str | None = None) -> str:
    """Mint + persist a refresh token (new family unless rotating an existing one)."""
    family = family_id or new_token_id()
    jti = new_token_id()
    token, expires = create_refresh_token(user.id, jti, family)
    ua = (request.headers.get("user-agent") or "")[:255] if request else None
    db.add(RefreshToken(jti=jti, user_id=user.id, family_id=family, expires_at=expires, user_agent=ua))
    return token


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    email = payload.email.lower().strip()
    key = f"{_client_ip(request)}:{email}"
    now = datetime.now(timezone.utc)

    recent = [t for t in _attempts.get(key, []) if now - t < timedelta(minutes=LOCKOUT_MINUTES)]
    if len(recent) >= MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in a few minutes.")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        recent.append(now)
        _attempts[key] = recent
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled")

    _attempts.pop(key, None)
    token = create_access_token(user.id, user.email, user.role)
    refresh = await _issue_refresh_token(db, user, request)
    await log_action(db, user=user, action="auth.login", entity_type="user", entity_id=user.id, request=request)
    return TokenResponse(access_token=token, refresh_token=refresh, user=_to_user_out(user))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for a fresh access token, rotating the refresh token.

    Deliberately does NOT require a valid access token (the whole point is to run after the access
    token has expired). Enforces server-side revocation, expiry, and reuse detection."""
    try:
        claims = decode_refresh_token(payload.refresh_token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    jti = claims.get("jti")
    row = await db.get(RefreshToken, jti) if jti else None
    if not row:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if row.revoked:
        # A previously-rotated token was replayed → treat the whole family as compromised.
        await db.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id).values(revoked=True))
        await db.commit()
        raise HTTPException(status_code=401, detail="Refresh token reuse detected")

    if row.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = await db.get(User, claims.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Rotate: revoke the presented token and mint a successor in the same family.
    new_refresh = await _issue_refresh_token(db, user, request, family_id=row.family_id)
    row.revoked = True
    access = create_access_token(user.id, user.email, user.role)
    await db.commit()
    return TokenResponse(access_token=access, refresh_token=new_refresh, user=_to_user_out(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return _to_user_out(user)


@router.post("/logout")
async def logout(request: Request, payload: LogoutRequest | None = Body(default=None),
                 user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Revoke the presented refresh token's family if supplied, else all of the user's refresh tokens.
    if payload and payload.refresh_token:
        try:
            claims = decode_refresh_token(payload.refresh_token)
            row = await db.get(RefreshToken, claims.get("jti"))
            if row:
                await db.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id).values(revoked=True))
        except jwt.InvalidTokenError:
            pass
    else:
        await db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked == False).values(revoked=True))  # noqa: E712
    await log_action(db, user=user, action="auth.logout", entity_type="user", entity_id=user.id, request=request)
    return {"ok": True}


@router.post("/change-password")
async def change_password(payload: ChangePasswordIn, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    await db.commit()
    await log_action(db, user=user, action="auth.change_password", entity_type="user", entity_id=user.id, request=request)
    return {"ok": True}
