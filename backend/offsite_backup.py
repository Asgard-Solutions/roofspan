#!/usr/bin/env python3
"""Off-site (secondary) backup copy for RoofSpan — LOCAL FILESYSTEM ONLY.

RoofSpan copies a completed local PostgreSQL backup to a customer-selected, Windows-accessible
directory: another local/USB/external drive, a NAS, a UNC network share, or a locally-synchronised
cloud folder (OneDrive/Dropbox/Google Drive). There is NO cloud API, NO AWS/S3, NO pre-signed URLs,
NO Emergent object storage, and NO credentials involved — it is a plain file copy performed by the
same service that creates the backup.

CLI:
  python3 offsite_backup.py copy <local_dump_path>   # copy to the configured secondary location
  python3 offsite_backup.py validate <dest_dir>      # write/read/delete test on a destination
  python3 offsite_backup.py latest-name
Exit code 0 on success, non-zero on failure.
"""
import asyncio
import glob
import os
import sys

from services import backup as backup_svc

BACKUP_DIR = backup_svc.BACKUP_DIR


def _latest_local():
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "roofspan_*.dump")), reverse=True)
    return files[0] if files else None


def main() -> int:
    if len(sys.argv) < 2:
        print("FAIL: missing command", file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    try:
        if cmd == "copy":
            local = sys.argv[2]
            dest = asyncio.run(backup_svc.copy_offsite(local))
            print(f"OK {dest}")
            return 0
        if cmd == "validate":
            res = backup_svc.validate_offsite_location(sys.argv[2])
            print(("OK " if res["ok"] else "FAIL ") + res["message"])
            return 0 if res["ok"] else 1
        if cmd == "retrieve":
            name, dest = sys.argv[2], sys.argv[3]
            src_dir = backup_svc.get_offsite_dir()
            if not src_dir:
                print("FAIL: no secondary backup location configured", file=sys.stderr)
                return 1
            src = os.path.join(src_dir, os.path.basename(name))
            import shutil
            shutil.copyfile(src, dest)
            print(f"OK {dest}")
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
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
