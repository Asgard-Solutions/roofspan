import os
import glob
from datetime import datetime
from typing import Optional

import jwt
from sqlalchemy import select
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core import require_roles, SENSITIVE_ROLES, log_action, JWT_ALGORITHM
from db import engine, SessionLocal
from models import User
from services import backup as backup_svc

router = APIRouter(prefix="/api/admin", tags=["admin-ops"])

# Reuse the service's OS-aware backup directory (Windows: ProgramData\RoofSpan\backups; POSIX: data volume).
BACKUP_DIR = backup_svc.BACKUP_DIR


def _iso(ts: str):
    try:
        return datetime.strptime(ts, "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _read(name: str) -> dict:
    path = os.path.join(BACKUP_DIR, name)
    if not os.path.exists(path):
        return {"status": "NONE", "ok": False, "timestamp": None}
    with open(path) as f:
        parts = f.read().strip().split()
    word = parts[0] if parts else "NONE"
    ts = _iso(parts[1]) if len(parts) > 1 else None
    return {"status": word, "ok": word in ("OK", "PASS"), "timestamp": ts}


@router.get("/backup-status")
async def backup_status(user: User = Depends(require_roles(*SENSITIVE_ROLES))):
    """Read-only operational backup health (admin only). Reads status files written by the backup/restore tooling."""
    return {
        "local_backup": _read("LAST_BACKUP_STATUS"),
        "offsite_copy": _read("LAST_OFFSITE_STATUS"),
        "offsite_restore_drill": _read("LAST_OFFSITE_RESTORE_STATUS"),
        "local_backup_count": len(glob.glob(os.path.join(BACKUP_DIR, "roofspan_*.dump"))),
        "backup_dir": BACKUP_DIR,
    }


# ---- Full backup create / list / download / upload / restore (admin only) ----

class RestoreIn(BaseModel):
    filename: str


class ScheduleIn(BaseModel):
    enabled: bool
    time: str
    offsite: bool = False
    offsite_dir: Optional[str] = None


class OffsiteLocationIn(BaseModel):
    offsite_dir: str = ""


async def _auth_admin(request: Request) -> User:
    """Authenticate an admin using a short-lived DB session (closed immediately).

    Used by the restore endpoint so no connection is held for the request lifetime.
    """
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    async with SessionLocal() as s:
        res = await s.execute(select(User).where(User.id == payload["sub"]))
        user = res.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    if user.role not in SENSITIVE_ROLES:
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
    return user


@router.get("/backups")
async def list_backups(user: User = Depends(require_roles(*SENSITIVE_ROLES))):
    return {"backups": backup_svc.list_backups(), "backup_dir": BACKUP_DIR}


@router.post("/backups/create")
async def create_backup(request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES))):
    try:
        info = await backup_svc.create_backup()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backup failed: {e}")
    async with SessionLocal() as db:
        await log_action(db, user=user, action="backup.create", entity_type="backup",
                         entity_id=info["filename"], detail={"size_bytes": info["size_bytes"]}, request=request)
    return info


@router.get("/backups/download/{filename}")
async def download_backup(filename: str, user: User = Depends(require_roles(*SENSITIVE_ROLES))):
    try:
        path = backup_svc.resolve_path(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Backup not found.")
    return FileResponse(path, media_type="application/octet-stream", filename=filename)


@router.post("/backups/upload")
async def upload_backup(request: Request, file: UploadFile = File(...),
                        user: User = Depends(require_roles(*SENSITIVE_ROLES))):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    try:
        info = backup_svc.save_upload(file.filename or "upload.dump", data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    async with SessionLocal() as db:
        await log_action(db, user=user, action="backup.upload", entity_type="backup",
                         entity_id=info["filename"], detail={"size_bytes": info["size_bytes"]}, request=request)
    return info


@router.post("/backups/offsite")
async def offsite_backup_copy(payload: RestoreIn, request: Request,
                             user: User = Depends(require_roles(*SENSITIVE_ROLES))):
    try:
        path = backup_svc.resolve_path(payload.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Backup not found.")
    try:
        object_path = await backup_svc.copy_offsite(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Off-site copy failed: {e}")
    async with SessionLocal() as db:
        await log_action(db, user=user, action="backup.offsite", entity_type="backup",
                         entity_id=payload.filename, detail={"object_path": object_path}, request=request)
    return {"ok": True, "filename": payload.filename, "object_path": object_path}



@router.post("/backups/restore")
async def restore_backup(payload: RestoreIn, request: Request):
    # NOTE: authenticate with a SHORT-LIVED session (not require_roles) so that no DB
    # connection is held open for the request lifetime — the restore recreates the database
    # and terminates all connections, which would otherwise break dependency teardown.
    user = await _auth_admin(request)
    try:
        path = backup_svc.resolve_path(payload.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Backup not found.")
    import traceback, logging
    # Auto safety backup FIRST — captures the current state so a mistaken restore can be undone.
    # Abort the restore if it cannot be created, so the user is never left without an undo point.
    try:
        safety = await backup_svc.create_backup(suffix="_safety")
    except Exception as e:
        logging.getLogger("roofspan").error("safety backup failed: %s", e)
        raise HTTPException(status_code=500,
                            detail=f"Could not create a safety backup before restoring, so the restore was aborted: {e}")
    try:
        await engine.dispose()
        try:
            await backup_svc.restore_backup(path)
        finally:
            await engine.dispose()
        # Audit AFTER the restore so the record persists in the restored database (an entry
        # written before the restore would be reverted by the restore itself).
        async with SessionLocal() as db:
            await log_action(db, user=user, action="backup.restore", entity_type="backup",
                             entity_id=payload.filename, detail={"safety_backup": safety["filename"]}, request=request)
    except HTTPException:
        raise
    except Exception as e:
        logging.getLogger("roofspan").error("restore failed: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Restore failed: {type(e).__name__}: {e}")
    return {"ok": True, "filename": payload.filename, "safety_backup": safety["filename"],
            "message": "Database restored. Please reload the app and sign in again."}


@router.get("/backups/schedule")
async def get_backup_schedule(user: User = Depends(require_roles(*SENSITIVE_ROLES))):
    return {"schedule": backup_svc.get_schedule(), "state": backup_svc.get_schedule_state()}


@router.get("/backups/health")
async def backup_health(user: User = Depends(require_roles(*SENSITIVE_ROLES))):
    """Compact backup-health summary for the Dashboard badge."""
    from datetime import datetime, timezone
    backups = backup_svc.list_backups()
    state = backup_svc.get_schedule_state()
    sched = backup_svc.get_schedule()
    newest = backups[0]["created_at"] if backups else None
    age_days = None
    if newest:
        try:
            dt = datetime.fromisoformat(newest)
            age_days = (datetime.now(timezone.utc) - dt).days
        except Exception:
            age_days = None
    stale = newest is None or (age_days is not None and age_days > 7)
    if newest is None:
        level, label = "error", "No backups yet"
    elif state.get("last_status") == "FAIL":
        level, label = "error", "Automatic backup failed"
    elif stale:
        level, label = "warn", f"Last backup {age_days}d ago"
    elif sched.get("offsite") and state.get("offsite_status") == "FAIL":
        level, label = "warn", "Off-site copy failed"
    else:
        label = "Backed up today" if (age_days == 0) else f"Backed up {age_days}d ago"
        level = "ok"
    return {
        "level": level, "label": label, "last_backup_at": newest, "age_days": age_days,
        "count": len(backups), "scheduled_enabled": sched.get("enabled"),
        "scheduled_status": state.get("last_status"), "offsite_status": state.get("offsite_status"),
    }


@router.put("/backups/schedule")
async def set_backup_schedule(payload: ScheduleIn, request: Request,
                              user: User = Depends(require_roles(*SENSITIVE_ROLES))):
    try:
        sched = backup_svc.set_schedule(payload.enabled, payload.time, payload.offsite, payload.offsite_dir)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    async with SessionLocal() as db:
        await log_action(db, user=user, action="backup.schedule.update", entity_type="config",
                         entity_id="backup_schedule", detail=sched, request=request)
    return {"schedule": sched, "state": backup_svc.get_schedule_state()}


@router.put("/backups/offsite-location")
async def set_offsite_location(payload: OffsiteLocationIn, request: Request,
                               user: User = Depends(require_roles(*SENSITIVE_ROLES))):
    """Save the customer-selected secondary (off-site) backup directory to machine-level config."""
    sched = backup_svc.set_offsite_dir(payload.offsite_dir)
    async with SessionLocal() as db:
        await log_action(db, user=user, action="backup.offsite.location", entity_type="config",
                         entity_id="offsite_dir", detail={"offsite_dir": sched.get("offsite_dir")}, request=request)
    return {"schedule": backup_svc.get_schedule()}


@router.post("/backups/offsite-location/test")
async def test_offsite_location(payload: OffsiteLocationIn,
                                user: User = Depends(require_roles(*SENSITIVE_ROLES))):
    """Validate a secondary backup directory (write/read/delete a temp file) from the service context."""
    dest = payload.offsite_dir or backup_svc.get_offsite_dir()
    return backup_svc.validate_offsite_location(dest)


@router.post("/backups/schedule/run-now")
async def run_scheduled_now(request: Request, user: User = Depends(require_roles(*SENSITIVE_ROLES))):
    """Run the automatic backup immediately and update its status (used to retry a failed one)."""
    state = await backup_svc.run_scheduled_backup()
    async with SessionLocal() as db:
        await log_action(db, user=user, action="backup.schedule.run", entity_type="backup",
                         entity_id=state.get("last_file"), detail={"status": state.get("last_status")}, request=request)
    return {"schedule": backup_svc.get_schedule(), "state": state}
