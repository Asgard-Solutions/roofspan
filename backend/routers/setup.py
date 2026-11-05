"""First-run onboarding — create the very first Owner account + company profile on a clean install.

Public (unauthenticated) by necessity: on a fresh database nobody can sign in yet. Every route is
guarded by a strict "zero users" check and FAILS CLOSED the moment any user exists, so it can never
be used to create a second privileged account or overwrite an existing install.
"""
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
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
async def initialize(payload: SetupInitializeRequest, request: Request, background: BackgroundTasks,
                     db: AsyncSession = Depends(get_db)):
    if (await _user_count(db)) > 0:
        raise HTTPException(status_code=409, detail="Setup has already been completed on this installation.")
    from licensing import pairing_client
    if await pairing_client.company_already_registered(
            {"name": payload.company.name, "phone": payload.company.phone, "address": payload.company.address}):
        raise HTTPException(status_code=409, detail={
            "code": "company_exists",
            "message": "This company is already registered with RoofSpan. Choose 'Restore my company' and "
                       "enter your company recovery code."})

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
    background.add_task(pairing_client.sync_company_profile_in_background, True)  # register with the details just entered

    return TokenResponse(
        access_token=token,
        refresh_token=refresh,
        user=UserOut(
            id=str(owner.id), email=owner.email, full_name=owner.full_name,
            role=owner.role, is_active=owner.is_active, created_at=owner.created_at,
        ),
    )


# ---------------- Restore an existing company on a new / reinstalled PC ----------------
# Same zero-users guard as /initialize. The recovery code proves the company; the Control Plane moves the
# company to THIS PC (its previous PC is disconnected) and the owner then imports their last backup.
from pydantic import BaseModel, Field  # noqa: E402
from fastapi import File, UploadFile  # noqa: E402

RECOVERY_KEY = "setup_recovery"


class RecoverVerifyIn(BaseModel):
    recovery_code: str = Field(min_length=8, max_length=64)


class RecoverFolderIn(BaseModel):
    folder: str = Field(min_length=1, max_length=1024)


class RecoverRestoreIn(RecoverFolderIn):
    filename: str = Field(min_length=1, max_length=255)


async def _require_fresh(db: AsyncSession) -> None:
    if (await _user_count(db)) > 0:
        raise HTTPException(status_code=409, detail="Setup has already been completed on this installation.")


async def _verified_recovery() -> dict:
    from db import SessionLocal
    async with SessionLocal() as db:
        await _require_fresh(db)
        row = (await db.execute(select(AppConfig).where(AppConfig.key == RECOVERY_KEY))).scalar_one_or_none()
        if not (row and isinstance(row.value, dict) and row.value.get("installation_id")):
            raise HTTPException(status_code=403, detail="Enter your company recovery code first.")
        return dict(row.value)


@router.post("/recover/verify")
async def recover_verify(payload: RecoverVerifyIn, db: AsyncSession = Depends(get_db)):
    from licensing import pairing_client
    await _require_fresh(db)
    try:
        data = await pairing_client.recover_company(db, payload.recovery_code)
    except pairing_client.ControlPlaneError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keep = {k: data.get(k) for k in ("installation_id", "company_id", "company_name", "company_phone", "company_address")}
    keep["base"] = pairing_client.control_plane_base()
    row = (await db.execute(select(AppConfig).where(AppConfig.key == RECOVERY_KEY))).scalar_one_or_none()
    if row:
        row.value = keep
    else:
        db.add(AppConfig(key=RECOVERY_KEY, value=keep))
    await db.commit()
    return {"company_name": keep["company_name"], "company_phone": keep["company_phone"],
            "company_address": keep["company_address"]}


@router.post("/recover/backups")
async def recover_list_backups(payload: RecoverFolderIn):
    from services import backup as backup_svc
    await _verified_recovery()
    listing = backup_svc.list_offsite_backups(payload.folder.strip())
    if not listing["available"]:
        raise HTTPException(status_code=400, detail="That folder could not be opened from this computer.")
    return listing


async def _restore_and_reconnect(path: str, rec: dict) -> dict:
    import logging
    import traceback
    from db import SessionLocal, engine
    from licensing import pairing_client
    from services import backup as backup_svc
    try:
        await engine.dispose()
        try:
            await backup_svc.restore_backup(path)
        finally:
            await engine.dispose()
    except Exception as e:  # noqa: BLE001
        logging.getLogger("roofspan").error("setup restore failed: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Restore failed: {type(e).__name__}: {e}")
    async with SessionLocal() as db:  # the backup carries the OLD PC's Control Plane ids: re-point to this PC
        await pairing_client.save_registration(db, rec, rec["base"])
        if (await _user_count(db)) == 0:
            raise HTTPException(status_code=422, detail="That backup has no user accounts, so it cannot be signed in to.")
        await log_action(db, user=None, action="setup.restore_company", entity_type="company",
                         entity_id=rec.get("company_id"), detail={"backup": os.path.basename(path)})
    return {"ok": True, "company_name": rec.get("company_name"),
            "message": "Your company has been restored. Sign in with your usual RoofSpan email and password."}


@router.post("/recover/restore-folder")
async def recover_restore_folder(payload: RecoverRestoreIn):
    from services import backup as backup_svc
    rec = await _verified_recovery()
    try:
        path = await backup_svc.stage_offsite_for_restore(payload.filename, payload.folder.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _restore_and_reconnect(path, rec)


@router.post("/recover/restore-upload")
async def recover_restore_upload(file: UploadFile = File(...)):
    from services import backup as backup_svc
    rec = await _verified_recovery()
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    try:
        info = backup_svc.save_upload(file.filename or "upload.dump", data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _restore_and_reconnect(backup_svc.resolve_path(info["filename"]), rec)
