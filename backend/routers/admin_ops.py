import os
import glob
from datetime import datetime

from fastapi import APIRouter, Depends

from core import require_roles, SENSITIVE_ROLES
from models import User

router = APIRouter(prefix="/api/admin", tags=["admin-ops"])

BACKUP_DIR = os.environ.get("ROOFSPAN_BACKUP_DIR", "/data/db/roofspan_backups")


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
