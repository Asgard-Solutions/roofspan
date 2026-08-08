#!/usr/bin/env python3
"""Off-site backup copy for RoofSpan using Emergent managed object storage (pod-independent).

CLI:
  python3 offsite_backup.py upload <local_dump_path>   -> uploads to roofspan/backups/<basename>; prints OK <object_path> or FAIL
  python3 offsite_backup.py download <object_path> <dest_path>
  python3 offsite_backup.py latest-name               -> prints the basename of the newest local dump (helper)

Exit code 0 on success, non-zero on failure (so callers can detect off-site failure).
"""
import os
import sys
import glob

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_NAME = "roofspan"
BACKUP_DIR = os.environ.get("ROOFSPAN_BACKUP_DIR", "/data/db/roofspan_backups")

_storage_key = None


def init_storage(force: bool = False) -> str:
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


def put_object(path: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
    key = init_storage()
    resp = requests.put(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=180)
    if resp.status_code == 404:  # stale/inactive storage key -> mint a fresh one and retry once
        key = init_storage(force=True)
        resp = requests.put(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=180)
    resp.raise_for_status()
    return resp.json()


def get_object(path: str) -> bytes:
    key = init_storage()
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=120)
    if resp.status_code == 404:
        key = init_storage(force=True)
        resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=120)
    resp.raise_for_status()
    return resp.content


def _object_path(basename: str) -> str:
    return f"{APP_NAME}/backups/{basename}"


def _latest_local() -> str | None:
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "roofspan_*.dump")), reverse=True)
    return files[0] if files else None


def main() -> int:
    if len(sys.argv) < 2:
        print("FAIL: missing command", file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    try:
        if cmd == "upload":
            local = sys.argv[2]
            with open(local, "rb") as f:
                data = f.read()
            res = put_object(_object_path(os.path.basename(local)), data)
            print(f"OK {res.get('path')}")
            return 0
        if cmd == "download":
            obj, dest = sys.argv[2], sys.argv[3]
            data = get_object(obj)
            with open(dest, "wb") as f:
                f.write(data)
            print(f"OK {dest} ({len(data)} bytes)")
            return 0
        if cmd == "latest-name":
            latest = _latest_local()
            if not latest:
                print("FAIL: no local backups", file=sys.stderr)
                return 1
            print(os.path.basename(latest))
            return 0
        print(f"FAIL: unknown command {cmd}", file=sys.stderr)
        return 2
    except Exception as e:  # loud failure for callers/logs
        print(f"FAIL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
