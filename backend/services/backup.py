"""Full-database backup & restore for RoofSpan Office.

Creates portable PostgreSQL custom-format dumps (pg_dump -Fc) on the persistent
volume that the user can download and store anywhere, and restores the entire
database from any such dump (pg_restore --clean). All data lives in PostgreSQL,
so a single dump is a complete, self-contained backup of the app's data.
"""
import os
import re
import glob
import json
import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote

from services import pg_tools
from services import object_storage


def _default_backup_dir() -> str:
    """Windows customer installs store backups under ProgramData; POSIX/dev uses the data volume.
    The Windows installer sets ROOFSPAN_BACKUP_DIR=C:\\ProgramData\\RoofSpan\\backups explicitly."""
    if os.name == "nt":
        base = os.environ.get("ProgramData", r"C:\ProgramData")
        return os.path.join(base, "RoofSpan", "backups")
    return "/data/db/roofspan_backups"


BACKUP_DIR = os.environ.get("ROOFSPAN_BACKUP_DIR") or _default_backup_dir()
SCHEDULE_FILE = os.path.join(BACKUP_DIR, "schedule.json")
SCHED_STATE_FILE = os.path.join(BACKUP_DIR, "schedule_state.json")
# Only files matching this pattern are ever listed / downloaded / restored.
SAFE_NAME = re.compile(r"^roofspan_[A-Za-z0-9_\-]+\.dump$")
# pg custom-format dumps begin with this magic marker.
PG_DUMP_MAGIC = b"PGDMP"
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _conn():
    """Parse DATABASE_URL into pg connection parts (strips the +asyncpg driver)."""
    raw = os.environ["DATABASE_URL"]
    p = urlparse(raw)
    return {
        "host": p.hostname or "127.0.0.1",
        "port": str(p.port or 5432),
        "user": unquote(p.username) if p.username else "postgres",
        "password": unquote(p.password) if p.password else "",
        "dbname": (p.path or "/postgres").lstrip("/"),
    }


def _env(c):
    e = dict(os.environ)
    e["PGPASSWORD"] = c["password"]
    return e


def resolve_path(filename: str) -> str:
    """Validate a user-supplied backup filename and return its absolute path inside BACKUP_DIR."""
    if not filename or not SAFE_NAME.match(filename):
        raise ValueError("Invalid backup filename.")
    path = os.path.realpath(os.path.join(BACKUP_DIR, filename))
    if os.path.dirname(path) != os.path.realpath(BACKUP_DIR):
        raise ValueError("Invalid backup path.")
    return path


def list_backups() -> list[dict]:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    out = []
    for path in glob.glob(os.path.join(BACKUP_DIR, "roofspan_*.dump")):
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append({
            "filename": os.path.basename(path),
            "size_bytes": st.st_size,
            "created_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "offsite": os.path.exists(path + ".offsite"),
        })
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return out


async def copy_offsite(path: str) -> str:
    """Copy a completed local backup to the customer-configured SECONDARY location (a normal
    Windows-accessible directory: local/USB/external drive, NAS, UNC share, or a locally-synced
    cloud folder). This is a COPY — the original local backup is never moved or modified. Writes to
    a '.partial' file first then atomically renames. Records a local '<file>.offsite' marker on success.
    """
    dest_dir = get_offsite_dir()
    if not dest_dir:
        raise ValueError("No secondary backup location is configured.")
    basename = os.path.basename(path)

    def _do():
        os.makedirs(dest_dir, exist_ok=True)
        final = os.path.join(dest_dir, basename)
        tmp = final + ".partial"
        try:
            with open(path, "rb") as src, open(tmp, "wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
            os.replace(tmp, final)  # atomic on same filesystem
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise
        return final

    obj = await asyncio.to_thread(_do)
    with open(path + ".offsite", "w") as f:
        f.write(obj)
    # Enforce copy-location retention (keep newest N), if configured.
    retention = get_offsite_retention()
    if retention > 0:
        await asyncio.to_thread(prune_offsite, dest_dir, retention)
    return obj


def validate_offsite_location(dest_dir: str) -> dict:
    """Validate the SECONDARY backup location from the service context that performs the copy:
    the directory exists (or can be created) and RoofSpan can write, read, then delete a temp file.
    Returns a user-friendly {ok, message}. Raw exceptions are logged, never surfaced verbatim."""
    dest_dir = (dest_dir or "").strip()
    if not dest_dir:
        return {"ok": False, "message": "Enter a backup copy location."}
    probe = os.path.join(dest_dir, ".roofspan_write_test")
    try:
        os.makedirs(dest_dir, exist_ok=True)
        with open(probe, "wb") as f:
            f.write(b"roofspan-write-test")
        with open(probe, "rb") as f:
            f.read()
        os.remove(probe)
        return {"ok": True, "message": "Backup location is accessible and writable."}
    except Exception as e:
        logging.getLogger("roofspan").warning("off-site location validation failed for %r: %s", dest_dir, e)
        try:
            if os.path.exists(probe):
                os.remove(probe)
        except OSError:
            pass
        return {"ok": False, "message": (
            f"RoofSpan cannot write to this backup location:\n{dest_dir}\n\n"
            "Verify that the folder exists and that the RoofSpan service account has permission to access it. "
            "For network shares, use a UNC path (\\\\Server\\Share\\RoofSpan) rather than a mapped drive letter."
        )}


async def create_backup(suffix: str = "") -> dict:
    """Run pg_dump (custom format) into a fresh timestamped file. Atomic (.partial->mv).

    `suffix` tags special backups (e.g. "_safety" taken automatically before a restore).
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    c = _conn()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join(BACKUP_DIR, f"roofspan_{ts}{suffix}.dump")
    tmp = out + ".partial"
    proc = await asyncio.create_subprocess_exec(
        pg_tools.resolve_executable("pg_dump"), "-h", c["host"], "-p", c["port"], "-U", c["user"],
        "-d", c["dbname"], "-Fc", "-f", tmp,
        env=_env(c),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RuntimeError(f"pg_dump failed: {stderr.decode(errors='replace')[-500:]}")
    os.replace(tmp, out)
    st = os.stat(out)
    # Local retention: cap the number of local backups kept in BACKUP_DIR (never prune while
    # creating a pre-restore safety backup; the newest safety point is always preserved).
    if not suffix:
        keep = get_local_retention()
        if keep > 0:
            try:
                prune_local(keep)
            except Exception:
                logging.getLogger("roofspan").exception("local retention prune failed")
    return {
        "filename": os.path.basename(out),
        "size_bytes": st.st_size,
        "created_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    }


async def _run(args: list[str], env: dict) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {(err or out).decode(errors='replace')[-800:]}")
    return (err or b"").decode(errors="replace")


async def restore_backup(path: str) -> str:
    """Restore the entire database from a custom-format dump.

    Recreates the database from scratch (DROP ... WITH FORCE terminates any lingering
    connections) then restores into the clean database. This avoids lock contention and
    stale-connection issues that occur when restoring in-place over a live database. The
    caller MUST have disposed the app's connection pool first.
    """
    c = _conn()
    db = c["dbname"]
    if not db.replace("_", "").isalnum():
        raise ValueError("Unsafe database name.")
    base = ["-h", c["host"], "-p", c["port"], "-U", c["user"]]
    env = _env(c)
    psql = pg_tools.resolve_executable("psql")
    pg_restore = pg_tools.resolve_executable("pg_restore")
    # 1. Drop + recreate the target DB from the 'postgres' maintenance database.
    await _run([psql, *base, "-d", "postgres", "-v", "ON_ERROR_STOP=1",
                "-c", f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE);',
                "-c", f'CREATE DATABASE "{db}" OWNER "{c["user"]}";'], env)
    # 2. Restore the dump into the fresh database.
    msg = await _run([pg_restore, "--no-owner", "--no-privileges", *base, "-d", db, path], env)
    return msg[-800:]


def save_upload(raw_name: str, data: bytes) -> dict:
    """Store an externally-provided dump so it can be restored. Validates the pg magic header.

    The write goes through the shared dual-mode object storage: self-hosted installs land the dump
    in the local backup directory (where list/download/restore read it), while hosted installs use
    the managed object store instead of ephemeral pod disk.
    """
    if data[:5] != PG_DUMP_MAGIC:
        raise ValueError("File is not a valid RoofSpan backup (expected a PostgreSQL custom-format dump).")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"roofspan_{ts}_import.dump"
    res = object_storage.put_upload(name, data, local_base=BACKUP_DIR,
                                    content_type="application/octet-stream")
    full = res.get("full")
    if full and os.path.exists(full):
        st = os.stat(full)
        created_at = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
        size_bytes = st.st_size
    else:
        created_at = datetime.now(timezone.utc).isoformat()
        size_bytes = res.get("bytes", len(data))
    return {
        "filename": name,
        "size_bytes": size_bytes,
        "created_at": created_at,
    }


# ---- Scheduled auto-backup (file-based so it survives DB restores) ----
DEFAULT_SCHEDULE = {"enabled": False, "time": "02:00", "offsite": False, "offsite_dir": "",
                    "offsite_retention": 0, "local_retention": 0}
OFFSITE_DIR_ENV = os.environ.get("ROOFSPAN_OFFSITE_BACKUP_DIR", "")
_SAFETY_TAG = "_safety"


def _read_json(path: str, default: dict) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return dict(default)


def _write_json(path: str, data: dict):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    tmp = path + ".partial"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def get_schedule() -> dict:
    s = _read_json(SCHEDULE_FILE, DEFAULT_SCHEDULE)
    def _int(v):
        try:
            return max(0, int(v or 0))
        except (TypeError, ValueError):
            return 0
    return {"enabled": bool(s.get("enabled", False)), "time": s.get("time", "02:00"),
            "offsite": bool(s.get("offsite", False)),
            "offsite_dir": s.get("offsite_dir") or OFFSITE_DIR_ENV or "",
            "offsite_retention": _int(s.get("offsite_retention", 0)),
            "local_retention": _int(s.get("local_retention", 0))}


def set_schedule(enabled: bool, time_str: str, offsite: bool = False, offsite_dir: str | None = None,
                 local_retention: int | None = None) -> dict:
    if not _TIME_RE.match(time_str or ""):
        raise ValueError("Time must be in 24-hour HH:MM format.")
    current = get_schedule()
    dest = current.get("offsite_dir", "") if offsite_dir is None else (offsite_dir or "").strip()
    if offsite and not dest:
        raise ValueError("Choose a backup copy location before enabling secondary backups.")
    lr = current.get("local_retention", 0) if local_retention is None else max(0, int(local_retention))
    sched = {"enabled": bool(enabled), "time": time_str, "offsite": bool(offsite), "offsite_dir": dest,
             "offsite_retention": current.get("offsite_retention", 0), "local_retention": lr}
    _write_json(SCHEDULE_FILE, sched)
    return get_schedule()


def get_offsite_dir() -> str:
    return get_schedule().get("offsite_dir") or ""


def get_offsite_retention() -> int:
    return get_schedule().get("offsite_retention", 0)


def get_local_retention() -> int:
    return get_schedule().get("local_retention", 0)


def set_offsite_dir(dest_dir: str, retention: int | None = None) -> dict:
    """Persist the customer-selected secondary backup directory (and optional retention count) to
    machine-level RoofSpan config (schedule.json), NOT browser storage. Stores no credentials."""
    s = get_schedule()
    s["offsite_dir"] = (dest_dir or "").strip()
    if retention is not None:
        try:
            s["offsite_retention"] = max(0, int(retention))
        except (TypeError, ValueError):
            s["offsite_retention"] = 0
    _write_json(SCHEDULE_FILE, s)
    return get_schedule()


def prune_offsite(dest_dir: str, keep: int) -> list[str]:
    """Keep only the newest `keep` RoofSpan backups at the copy location; delete older ones.
    keep<=0 disables pruning. Only RoofSpan-generated 'roofspan_*.dump' files are ever removed."""
    if keep <= 0 or not dest_dir:
        return []
    files = sorted(glob.glob(os.path.join(dest_dir, "roofspan_*.dump")), reverse=True)  # newest first (ts name)
    removed = []
    for old in files[keep:]:
        try:
            os.remove(old)
            removed.append(os.path.basename(old))
        except OSError as e:
            logging.getLogger("roofspan").warning("could not prune old off-site backup %r: %s", old, e)
    return removed


def prune_local(keep: int) -> list[str]:
    """Keep only the newest `keep` local RoofSpan backups in BACKUP_DIR so the disk doesn't fill up.
    keep<=0 disables pruning. The single most-recent '_safety' backup is always preserved (undo point),
    and only RoofSpan-generated files (+ their .offsite markers) are ever removed."""
    if keep <= 0:
        return []
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "roofspan_*.dump")),
                   key=lambda p: os.stat(p).st_mtime, reverse=True)  # newest first
    protected = set()
    newest_safety = next((p for p in files if _SAFETY_TAG in os.path.basename(p)), None)
    if newest_safety:
        protected.add(newest_safety)
    removed = []
    for old in files[keep:]:
        if old in protected:
            continue
        try:
            os.remove(old)
            for marker in (old + ".offsite",):
                if os.path.exists(marker):
                    os.remove(marker)
            removed.append(os.path.basename(old))
        except OSError as e:
            logging.getLogger("roofspan").warning("could not prune old local backup %r: %s", old, e)
    return removed


def list_offsite_backups() -> dict:
    """List RoofSpan backups available at the configured copy location (for Restore From Copy)."""
    dest = get_offsite_dir()
    if not dest:
        return {"offsite_dir": "", "available": False, "backups": []}
    try:
        names = glob.glob(os.path.join(dest, "roofspan_*.dump"))
    except OSError:
        return {"offsite_dir": dest, "available": False, "backups": []}
    out = []
    for path in names:
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append({"filename": os.path.basename(path), "size_bytes": st.st_size,
                    "created_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()})
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return {"offsite_dir": dest, "available": True, "backups": out}


async def stage_offsite_for_restore(filename: str) -> str:
    """Copy a backup FROM the configured copy location back into BACKUP_DIR so it can be restored.
    The source is restricted to the configured copy directory and RoofSpan-named files only."""
    if not filename or not SAFE_NAME.match(filename):
        raise ValueError("Invalid backup filename.")
    dest = get_offsite_dir()
    if not dest:
        raise ValueError("No secondary backup location is configured.")
    src = os.path.realpath(os.path.join(dest, filename))
    if os.path.dirname(src) != os.path.realpath(dest):
        raise ValueError("Invalid backup path.")
    if not os.path.exists(src):
        raise ValueError("That backup was not found at the configured copy location.")
    local = resolve_path(filename)

    def _copy():
        tmp = local + ".partial"
        try:
            with open(src, "rb") as s, open(tmp, "wb") as d:
                while True:
                    chunk = s.read(1024 * 1024)
                    if not chunk:
                        break
                    d.write(chunk)
            os.replace(tmp, local)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise
        return local

    return await asyncio.to_thread(_copy)


def record_offsite_result(ok: bool, error: str | None = None):
    """Persist the latest secondary-copy outcome so the Dashboard can warn when the copy location has
    been unreachable for several days. Local backup status is tracked separately and is unaffected."""
    state = get_schedule_state()
    now = datetime.now(timezone.utc).isoformat()
    state["offsite_status"] = "OK" if ok else "FAIL"
    state["offsite_error"] = None if ok else (error or "")[:300]
    state["offsite_last_attempt_at"] = now
    if ok:
        state["offsite_last_ok_at"] = now
    _write_json(SCHED_STATE_FILE, state)
    return state


def get_schedule_state() -> dict:
    return _read_json(SCHED_STATE_FILE, {})


async def run_scheduled_backup(attempt_date: str | None = None) -> dict:
    ad = attempt_date or datetime.now().date().isoformat()
    try:
        info = await create_backup()
        state = {"last_status": "OK", "last_run_at": info["created_at"],
                 "last_file": info["filename"], "last_error": None, "last_attempt_date": ad}
        # Auto off-site copy (when enabled) so the daily backup survives a machine failure.
        if get_schedule().get("offsite"):
            try:
                await copy_offsite(resolve_path(info["filename"]))
                state["offsite_status"] = "OK"
                state["offsite_error"] = None
                state["offsite_last_ok_at"] = datetime.now(timezone.utc).isoformat()
                state["offsite_last_attempt_at"] = state["offsite_last_ok_at"]
            except Exception as e:
                state["offsite_status"] = "FAIL"
                state["offsite_error"] = str(e)[:300]
                state["offsite_last_attempt_at"] = datetime.now(timezone.utc).isoformat()
                state["offsite_last_ok_at"] = get_schedule_state().get("offsite_last_ok_at")
                logging.getLogger("roofspan").error("scheduled off-site copy FAILED: %s", e)
        else:
            state["offsite_status"] = None
            state["offsite_last_ok_at"] = get_schedule_state().get("offsite_last_ok_at")
    except Exception as e:
        state = {"last_status": "FAIL", "last_run_at": datetime.now(timezone.utc).isoformat(),
                 "last_file": None, "last_error": str(e)[:300], "last_attempt_date": ad,
                 "offsite_status": None}
        logging.getLogger("roofspan").error("scheduled backup FAILED: %s", e)
    _write_json(SCHED_STATE_FILE, state)
    return state


async def _scheduler_tick():
    sched = get_schedule()
    if not sched.get("enabled"):
        return
    m = _TIME_RE.match(sched.get("time", ""))
    if not m:
        return
    hh, mm = int(m.group(1)), int(m.group(2))
    now = datetime.now()  # local machine time (== user's time on a desktop install)
    scheduled = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    today = now.date().isoformat()
    # Run once per day, at or after the scheduled time (catch-up if the app was off at that minute).
    if now >= scheduled and get_schedule_state().get("last_attempt_date") != today:
        await run_scheduled_backup(attempt_date=today)


async def scheduler_loop():
    await asyncio.sleep(20)  # let startup settle
    while True:
        try:
            await _scheduler_tick()
        except Exception:
            logging.getLogger("roofspan").exception("backup scheduler tick error")
        await asyncio.sleep(60)
