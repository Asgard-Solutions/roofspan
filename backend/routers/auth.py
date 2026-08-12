import os
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User
from core import verify_password, create_access_token, get_current_user, log_action
from schemas import LoginRequest, TokenResponse, UserOut
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
    token = create_access_token(user.id, user.email, user.role, user.token_version)
    await log_action(db, user=user, action="auth.login", entity_type="user", entity_id=user.id, request=request)
    return TokenResponse(access_token=token, user=_to_user_out(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return _to_user_out(user)


@router.post("/logout")
async def logout(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await log_action(db, user=user, action="auth.logout", entity_type="user", entity_id=user.id, request=request)
    return {"ok": True}


@router.post("/change-password")
async def change_password(payload: ChangePasswordIn, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1  # invalidate all prior tokens for this user
    await db.commit()
    await log_action(db, user=user, action="auth.change_password", entity_type="user", entity_id=user.id, request=request)
    # Return a fresh token carrying the new version so the caller's current session stays valid.
    token = create_access_token(user.id, user.email, user.role, user.token_version)
    return {"ok": True, "access_token": token}
