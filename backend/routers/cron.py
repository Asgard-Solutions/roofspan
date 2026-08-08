import os
import hmac
import subprocess

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

router = APIRouter(prefix="/api/cron", tags=["cron"])

_BACKUP_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "backup_db.sh")


def _run_backup():
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    subprocess.run(["bash", _BACKUP_SCRIPT], capture_output=True, text=True)


def _authorize(authorization: str | None):
    secret = os.environ.get("WEBHOOK_CRON_SECRET", "")
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not secret or not token or not hmac.compare_digest(token, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/backup")
async def cron_backup(background_tasks: BackgroundTasks, authorization: str | None = Header(None), x_webhook_id: str | None = Header(None)):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _authorize(authorization)
    background_tasks.add_task(_run_backup)
    return {"status": "accepted", "task": "db-backup"}
