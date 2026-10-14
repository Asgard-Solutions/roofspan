"""Durable automatic-update state machine (single source of truth for transitions and per-state policy).

The state file is replaced atomically (write tmp -> fsync -> os.replace) and every transition is compare-and-set
against the recorded state while holding an exclusive lock file, so restarts, crashes and concurrent callers can
neither skip a state nor run two installs at once.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os

S = dict  # readability for the table below

SPEC = {
    "IDLE": S(next=("CHECKING",), durable=(), retry="next scheduled check", reboot="stay", cleanup="none",
              user="Up to date", admin=("check_now",), log="state only"),
    "CHECKING": S(next=("IDLE", "UPDATE_AVAILABLE", "BLOCKED"), durable=("checked_utc",),
                  retry="next interval; transient network errors return to IDLE", reboot="restart check (-> IDLE)",
                  cleanup="none", user="Checking for updates", admin=(), log="reason code only"),
    "UPDATE_AVAILABLE": S(next=("DOWNLOADING", "IDLE", "BLOCKED"), durable=("manifest", "version", "required"),
                          retry="n/a", reboot="stay", cleanup="none", user="Update {version} available",
                          admin=("download_now", "defer"), log="version, required flag"),
    "DOWNLOADING": S(next=("DOWNLOAD_PAUSED", "DOWNLOADED", "BLOCKED", "IDLE"), durable=("manifest", "bits_job_id", "bytes"),
                     retry="BITS retries transient errors", reboot="resume BITS job by id", cleanup="cancel job on BLOCKED",
                     user="Downloading {version} ({percent}%)", admin=("pause",), log="bytes/total"),
    "DOWNLOAD_PAUSED": S(next=("DOWNLOADING", "IDLE", "BLOCKED"), durable=("manifest", "bits_job_id", "bytes"),
                         retry="resume at next check", reboot="resume BITS job by id", cleanup="none",
                         user="Download paused ({percent}%)", admin=("resume",), log="BITS error code"),
    "DOWNLOADED": S(next=("VERIFYING",), durable=("manifest", "download_path"), retry="n/a",
                    reboot="go to VERIFYING", cleanup="none", user="Downloaded {version}", admin=(), log="size"),
    "VERIFYING": S(next=("VERIFIED", "BLOCKED", "DOWNLOADED"), durable=("manifest", "download_path"),
                   retry="re-run verification from scratch after restart", reboot="re-verify from scratch",
                   cleanup="delete the download on BLOCKED", user="Verifying {version}", admin=(), log="reason code"),
    "VERIFIED": S(next=("SCHEDULED", "BLOCKED"), durable=("manifest", "download_path", "sha256"),
                  retry="n/a", reboot="stay (broker re-verifies anyway)", cleanup="none",
                  user="Ready to install {version}", admin=("install_now", "defer"), log="sha256"),
    "SCHEDULED": S(next=("PREFLIGHT", "BLOCKED", "VERIFIED"), durable=("manifest", "request_id", "scheduled_utc"),
                   retry="broker is started again at the next check", reboot="broker re-reads the request",
                   cleanup="the request is deleted when the broker accepts or rejects it",
                   user="Installation scheduled for {scheduled}", admin=("install_now", "cancel"), log="request id"),
    "PREFLIGHT": S(next=("BACKING_UP", "ROLLED_BACK", "BLOCKED", "FAILED_SUPPORT_REQUIRED"),
                   durable=("manifest", "request_id", "staged_sha256"), retry="none (coordinator owns it)",
                   reboot="reconcile with coordinator state.json", cleanup="none",
                   user="Preparing installation", admin=(), log="coordinator state"),
    "BACKING_UP": S(next=("INSTALLING", "ROLLED_BACK", "FAILED_SUPPORT_REQUIRED"), durable=("coordinator_attempt",),
                    retry="none", reboot="reconcile with coordinator", cleanup="none", user="Backing up your data",
                    admin=(), log="coordinator state"),
    "INSTALLING": S(next=("MIGRATING", "RECOVERING", "FAILED_SUPPORT_REQUIRED"), durable=("coordinator_attempt",),
                    retry="none", reboot="coordinator boot recovery; reconcile", cleanup="none",
                    user="Installing {version}", admin=(), log="coordinator state"),
    "MIGRATING": S(next=("HEALTH_CHECKING", "RECOVERING", "FAILED_SUPPORT_REQUIRED"), durable=("coordinator_attempt",),
                   retry="none", reboot="coordinator boot recovery; reconcile", cleanup="none",
                   user="Updating the database", admin=(), log="coordinator state"),
    "HEALTH_CHECKING": S(next=("SUCCEEDED", "RECOVERING", "FAILED_SUPPORT_REQUIRED"), durable=("coordinator_attempt",),
                         retry="none", reboot="reconcile", cleanup="none", user="Checking the new version",
                         admin=(), log="failed check name"),
    "SUCCEEDED": S(next=("IDLE",), durable=("version", "build_sha", "completed_utc"), retry="n/a", reboot="stay",
                   cleanup="delete the download and staging copy; keep rollback material for the retention period",
                   user="Updated to {version}", admin=(), log="version, build sha"),
    "RECOVERING": S(next=("ROLLED_BACK", "FAILED_SUPPORT_REQUIRED"), durable=("coordinator_attempt",),
                    retry="none", reboot="coordinator resume; reconcile", cleanup="none",
                    user="Restoring the previous version", admin=(), log="coordinator state"),
    "ROLLED_BACK": S(next=("IDLE",), durable=("version", "reason"), retry="this version is never retried automatically",
                     reboot="stay", cleanup="delete the staging copy", user="Update failed; previous version {previous} restored",
                     admin=("clear_failure",), log="reason code"),
    "BLOCKED": S(next=("IDLE",), durable=("reason",), retry="next check (a newer manifest may supersede)",
                 reboot="stay", cleanup="delete rejected downloads and requests", user="Update blocked ({reason})",
                 admin=("check_now",), log="stable reason code"),
    "FAILED_SUPPORT_REQUIRED": S(next=("IDLE",), durable=("reason", "evidence"), retry="NEVER automatic",
                                 reboot="stay", cleanup="keep everything for support",
                                 user="Update needs support: {reason}", admin=("clear_failure",), log="reason code"),
}
STATES = tuple(SPEC)
INSTALL_STATES = ("PREFLIGHT", "BACKING_UP", "INSTALLING", "MIGRATING", "HEALTH_CHECKING", "RECOVERING")
COORD_TO_UPDATE = {"PREFLIGHT": "PREFLIGHT", "BACKING_UP": "BACKING_UP", "BACKUP_VERIFIED": "BACKING_UP",
                   "SERVICES_STOPPED": "BACKING_UP", "INSTALLING": "INSTALLING", "MIGRATING": "MIGRATING",
                   "STARTING": "HEALTH_CHECKING", "HEALTH_CHECKING": "HEALTH_CHECKING", "RESTORING": "RECOVERING",
                   "COMPLETE": "SUCCEEDED", "ROLLED_BACK": "ROLLED_BACK", "FAILED": "FAILED_SUPPORT_REQUIRED"}


class StateError(RuntimeError):
    pass


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextlib.contextmanager
def exclusive_lock(path: str):
    """Process-wide exclusive lock (msvcrt on Windows, fcntl elsewhere). Blocks until acquired."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    continue
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            with contextlib.suppress(OSError):
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()


class UpdateStateStore:
    def __init__(self, root: str):
        self.root = root
        self.path = os.path.join(root, "update-state.json")
        self.journal = os.path.join(root, "journal.log")
        self.failed_path = os.path.join(root, "failed-versions.json")
        self.lock_path = os.path.join(root, "update.lock")

    def load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                st = json.load(f)
        except FileNotFoundError:
            return {"state": "IDLE", "seq": 0, "data": {}}
        except ValueError:
            return {"state": "FAILED_SUPPORT_REQUIRED", "seq": -1, "data": {"reason": "STATE_FILE_CORRUPT"}}
        if st.get("state") not in SPEC:
            return {"state": "FAILED_SUPPORT_REQUIRED", "seq": -1, "data": {"reason": "STATE_UNKNOWN"}}
        return st

    def _write(self, st: dict, note: str) -> None:
        os.makedirs(self.root, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        with open(self.journal, "a", encoding="utf-8") as f:
            f.write(json.dumps({"utc": st["updated_utc"], "seq": st["seq"], "state": st["state"], "note": note}) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def transition(self, expected: tuple | str, to: str, data: dict | None = None, note: str = "") -> dict:
        """Compare-and-set. Same-state re-entry with identical target is idempotent (no-op)."""
        expected = (expected,) if isinstance(expected, str) else tuple(expected)
        with exclusive_lock(self.lock_path):
            st = self.load()
            cur = st["state"]
            if cur == to and cur not in expected:
                return st
            if cur not in expected:
                raise StateError(f"transition {to} requires {expected}, recorded state is {cur}")
            if to not in SPEC[cur]["next"] and to != cur:
                raise StateError(f"illegal transition {cur} -> {to}")
            new = {"state": to, "seq": st.get("seq", 0) + 1, "updated_utc": _now(),
                   "data": {**(st.get("data") or {}), **(data or {})} if to not in ("IDLE",) else dict(data or {})}
            self._write(new, note)
            return new

    # failed-version list: prevents automatic reinstall of a version that already failed here
    def failed_versions(self) -> set:
        try:
            with open(self.failed_path, encoding="utf-8") as f:
                return set(json.load(f).get("versions", []))
        except (FileNotFoundError, ValueError):
            return set()

    def mark_failed(self, version: str) -> None:
        with exclusive_lock(self.lock_path):
            v = sorted(self.failed_versions() | {version})
            tmp = self.failed_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"versions": v}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.failed_path)


def _reconcile(self, to: str, data: dict) -> dict:
    """Mirror the coordinator's recorded progress (evidence-driven); only within the install phase."""
    if to not in INSTALL_STATES:
        raise StateError(f"reconcile target {to} is not an install state")
    with exclusive_lock(self.lock_path):
        st = self.load()
        if st["state"] not in INSTALL_STATES:
            raise StateError(f"reconcile from {st['state']} is not allowed")
        if st["state"] == to and all(st["data"].get(k) == v for k, v in data.items()):
            return st
        new = {"state": to, "seq": st.get("seq", 0) + 1, "updated_utc": _now(), "data": {**st["data"], **data}}
        self._write(new, "reconciled from coordinator evidence")
        return new


UpdateStateStore.reconcile = _reconcile
