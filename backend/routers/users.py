from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User
from core import (
    require_roles, get_current_user, hash_password, log_action, ROLES, SENSITIVE_ROLES, MANAGE_ROLES,
)
from licensing import service as licensing_service
from schemas import UserOut, UserCreate, UserUpdate, PasswordResetRequest, RoleInfo

router = APIRouter(prefix="/api/users", tags=["users"])

ROLE_META = [
    RoleInfo(key="owner", label="Owner", description="Full control including company settings, users, and integrations.", sensitive=True),
    RoleInfo(key="administrator", label="Administrator", description="Manages users, settings, and integrations.", sensitive=True),
    RoleInfo(key="office", label="Office", description="Runs day-to-day office workflows. No access to system settings.", sensitive=False),
    RoleInfo(key="sales", label="Sales", description="Field sales access to leads, properties, and jobs.", sensitive=False),
]


def _out(u: User) -> UserOut:
    return UserOut(id=str(u.id), email=u.email, full_name=u.full_name, role=u.role, is_active=u.is_active, created_at=u.created_at)


@router.get("/roles", response_model=list[RoleInfo])
async def list_roles(user: User = Depends(get_current_user)):
    return ROLE_META


@router.get("/assignable", response_model=list[UserOut])
async def list_assignable(user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    """Active users available for lead/job assignment. Accessible to owner/admin/office (not sales)."""
    result = await db.execute(select(User).where(User.is_active == True).order_by(User.full_name))
    return [_out(u) for u in result.scalars().all()]


@router.get("", response_model=list[UserOut])
async def list_users(user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return [_out(u) for u in result.scalars().all()]


@router.post("", response_model=UserOut, status_code=201)
async def create_user(payload: UserCreate, request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    if payload.role not in ROLES:
        raise HTTPException(status_code=422, detail="Invalid role")
    if payload.role == "owner" and user.role != "owner":
        raise HTTPException(status_code=403, detail="Only an Owner can create another Owner")
    email = payload.email.lower().strip()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    # New users are active and consume a licensed seat — enforce server-side, race-safe.
    await licensing_service.ensure_seat_available(db)
    new_user = User(email=email, full_name=payload.full_name, password_hash=hash_password(payload.password), role=payload.role)
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    await log_action(db, user=user, action="user.create", entity_type="user", entity_id=new_user.id, detail={"email": email, "role": payload.role}, request=request)
    return _out(new_user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: str, payload: UserUpdate, request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.role is not None and payload.role not in ROLES:
        raise HTTPException(status_code=422, detail="Invalid role")
    if target.role == "owner" and user.role != "owner":
        raise HTTPException(status_code=403, detail="Only an Owner can modify an Owner account")
    if payload.role == "owner" and user.role != "owner":
        raise HTTPException(status_code=403, detail="Only an Owner can assign the Owner role")
    if payload.is_active is False and str(target.id) == str(user.id):
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    # Reactivating a disabled user consumes a seat — enforce before flipping active.
    if payload.is_active is True and target.is_active is False:
        await licensing_service.ensure_seat_available(db)

    if payload.full_name is not None:
        target.full_name = payload.full_name
    if payload.role is not None:
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active
    await db.commit()
    await db.refresh(target)
    await log_action(db, user=user, action="user.update", entity_type="user", entity_id=target.id, detail=payload.model_dump(exclude_none=True), request=request)
    return _out(target)


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: str, payload: PasswordResetRequest, request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES)), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role == "owner" and user.role != "owner":
        raise HTTPException(status_code=403, detail="Only an Owner can reset an Owner's password")
    target.password_hash = hash_password(payload.new_password)
    await db.commit()
    await log_action(db, user=user, action="user.reset_password", entity_type="user", entity_id=target.id, request=request)
    return {"ok": True}
