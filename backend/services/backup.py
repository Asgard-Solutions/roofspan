"""Full-database backup & restore for RoofSpan Office.

Creates portable PostgreSQL custom-format dumps (pg_dump -Fc) on the persistent
volume that the user can download and store anywhere, and restores the entire
database from any such dump (pg_restore --clean). All data lives in PostgreSQL,
so a single dump is a complete, self-contained backup of the app's data.
"""
import os
import re
import glob
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote

BACKUP_DIR = os.environ.get("ROOFSPAN_BACKUP_DIR", "/data/db/roofspan_backups")
# Only files matching this pattern are ever listed / downloaded / restored.
SAFE_NAME = re.compile(r"^roofspan_[A-Za-z0-9_\-]+\.dump$")
# pg custom-format dumps begin with this magic marker.
PG_DUMP_MAGIC = b"PGDMP"


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
    """Push a local backup file to off-pod object storage. Returns the stored object path.

    Reuses the same off-site transport as the nightly backup. Runs the blocking upload in a
    worker thread and records a local '<file>.offsite' marker on success.
    """
    import offsite_backup
    basename = os.path.basename(path)
    with open(path, "rb") as f:
        data = f.read()

    def _do():
        res = offsite_backup.put_object(offsite_backup._object_path(basename), data)
        return res.get("path") or offsite_backup._object_path(basename)

    obj = await asyncio.to_thread(_do)
    with open(path + ".offsite", "w") as f:
        f.write(obj)
    return obj


async def create_backup() -> dict:
    """Run pg_dump (custom format) into a fresh timestamped file. Atomic (.partial -> mv)."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    c = _conn()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join(BACKUP_DIR, f"roofspan_{ts}.dump")
    tmp = out + ".partial"
    proc = await asyncio.create_subprocess_exec(
        "pg_dump", "-h", c["host"], "-p", c["port"], "-U", c["user"],
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
    # 1. Drop + recreate the target DB from the 'postgres' maintenance database.
    await _run(["psql", *base, "-d", "postgres", "-v", "ON_ERROR_STOP=1",
                "-c", f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE);',
                "-c", f'CREATE DATABASE "{db}" OWNER "{c["user"]}";'], env)
    # 2. Restore the dump into the fresh database.
    msg = await _run(["pg_restore", "--no-owner", "--no-privileges", *base, "-d", db, path], env)
    return msg[-800:]


def save_upload(raw_name: str, data: bytes) -> dict:
    """Store an externally-provided dump so it can be restored. Validates the pg magic header."""
    if data[:5] != PG_DUMP_MAGIC:
        raise ValueError("File is not a valid RoofSpan backup (expected a PostgreSQL custom-format dump).")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join(BACKUP_DIR, f"roofspan_{ts}_import.dump")
    tmp = out + ".partial"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, out)
    st = os.stat(out)
    return {
        "filename": os.path.basename(out),
        "size_bytes": st.st_size,
        "created_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    }
