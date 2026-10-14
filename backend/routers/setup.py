"""First-run onboarding — create the very first Owner account + company profile on a clean install.

Public (unauthenticated) by necessity: on a fresh database nobody can sign in yet. Every route is
guarded by a strict "zero users" check and FAILS CLOSED the moment any user exists, so it can never
be used to create a second privileged account or overwrite an existing install.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core import (
    create_access_token,
    create_refresh_token,
    hash_password,
    log_action,
    new_token_id,
)
from db import get_db
from models import AppConfig, RefreshToken, User
from schemas import (
    CompanyProfile,
    SetupInitializeRequest,
    SetupStatus,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/api/setup", tags=["setup"])


async def _user_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count(User.id)))).scalar_one()


@router.get("/status", response_model=SetupStatus)
async def setup_status(db: AsyncSession = Depends(get_db)):
    """True only while the database has zero users (i.e. the app has never been set up)."""
    return SetupStatus(needs_setup=(await _user_count(db)) == 0)


@router.post("/initialize", response_model=TokenResponse)
async def initialize(payload: SetupInitializeRequest, request: Request, db: AsyncSession = Depends(get_db)):
    if (await _user_count(db)) > 0:
        raise HTTPException(status_code=409, detail="Setup has already been completed on this installation.")

    email = payload.owner_email.lower().strip()
    owner = User(
        email=email,
        full_name=payload.owner_full_name.strip(),
        password_hash=hash_password(payload.owner_password),
        role="owner",
        is_active=True,
    )
    db.add(owner)

    company = CompanyProfile(**{**CompanyProfile().model_dump(), **payload.company.model_dump()})
    row = (await db.execute(select(AppConfig).where(AppConfig.key == "company_profile"))).scalar_one_or_none()
    if row:
        row.value = company.model_dump()
    else:
        db.add(AppConfig(key="company_profile", value=company.model_dump()))

    await db.flush()  # populate owner.id + created_at before minting tokens

    token = create_access_token(owner.id, owner.email, owner.role)
    jti, family = new_token_id(), new_token_id()
    refresh, expires = create_refresh_token(owner.id, jti, family)
    ua = (request.headers.get("user-agent") or "")[:255] if request else None
    db.add(RefreshToken(jti=jti, user_id=owner.id, family_id=family, expires_at=expires, user_agent=ua))

    await log_action(db, user=owner, action="setup.initialize", entity_type="user", entity_id=owner.id, request=request)
    await db.commit()

    return TokenResponse(
        access_token=token,
        refresh_token=refresh,
        user=UserOut(
            id=str(owner.id), email=owner.email, full_name=owner.full_name,
            role=owner.role, is_active=owner.is_active, created_at=owner.created_at,
        ),
    )
