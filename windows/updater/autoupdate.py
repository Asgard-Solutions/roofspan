"""Automatic-update checker (RoofSpanUpdateService, unprivileged) and privileged broker (RoofSpanUpdateBroker).

Both are pure orchestration over injected `ops`, so the same logic is unit-tested on Linux and wired to
Windows-native operations in winupdate.py. The broker re-verifies EVERYTHING; it trusts nothing the checker did.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import secrets

from .policy import (INSTALLER_FIXED_ARGS, SEMVER, Rejected, assert_fixed_argv, authorize_request_provenance,
                     evaluate_signature, validate_manifest, validate_request, verify_signed_manifest)
from .states import COORD_TO_UPDATE, INSTALL_STATES, UpdateStateStore

TERMINAL_COORD = ("COMPLETE", "ROLLED_BACK", "FAILED")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Paths:
    """Every location is derived here from the fixed data root and a validated MAJOR.MINOR.PATCH version."""

    def __init__(self, data_root: str):
        self.root = os.path.join(data_root, "update")
        self.state = os.path.join(self.root, "state")
        self.request = os.path.join(self.root, "requests", "request.json")
        self.broker_log = os.path.join(data_root, "logs", "update-broker-setup.log")

    def _v(self, version: str) -> str:
        if not SEMVER.match(version or ""):
            raise Rejected("VERSION_INVALID")
        return version

    def download(self, version: str) -> str:
        return os.path.join(self.root, "downloads", self._v(version), "RoofSpanSetup.exe")

    def staging(self, version: str) -> str:
        return os.path.join(self.root, "broker", "staging", self._v(version), "RoofSpanSetup.exe")

    def installer_argv(self, version: str) -> list:
        return [self.staging(version), *INSTALLER_FIXED_ARGS, self.broker_log]


class Checker:
    def __init__(self, ops, policy, installed_version: str, data_root: str, log, auto_install: bool):
        self.ops, self.policy, self.installed, self.log, self.auto = ops, policy, installed_version, log, auto_install
        self.paths = Paths(data_root)
        self.store = UpdateStateStore(self.paths.state)

    def _to(self, frm, to, data=None, note=""):
        st = self.store.transition(frm, to, data, note)
        self.log.info("update state %s %s", to, note)
        return st

    def tick(self) -> str:
        st = self.store.load()
        s = st["state"]
        if s == "FAILED_SUPPORT_REQUIRED":
            self.log.warning("update: FAILED_SUPPORT_REQUIRED (%s); automatic retries stopped", st["data"].get("reason"))
            return s
        if s in INSTALL_STATES:
            return s
        if s == "SCHEDULED":
            self.ops.start_broker()
            return s
        if s in ("SUCCEEDED", "ROLLED_BACK", "BLOCKED"):
            self._to(s, "IDLE", note="ready for next check")
            s = "IDLE"
        if s == "IDLE":
            s = self._check()
        if s in ("UPDATE_AVAILABLE", "DOWNLOADING", "DOWNLOAD_PAUSED"):
            s = self._download()
        if s in ("DOWNLOADED", "VERIFYING"):
            s = self._verify()
        if s == "VERIFIED" and self.auto:
            s = self._schedule()
        return s

    def _check(self) -> str:
        self._to("IDLE", "CHECKING", {"checked_utc": _now()})
        try:
            raw = self.ops.fetch_manifest()
        except Exception:  # noqa: BLE001 - transient network error
            self._to("CHECKING", "IDLE", note="reason=NETWORK_UNAVAILABLE")
            return "IDLE"
        try:
            m = verify_signed_manifest(raw, self.policy)
            kind = validate_manifest(m, self.policy, self.installed, self.store.failed_versions())
        except Rejected as r:
            if r.code == "NO_UPDATE":
                self._to("CHECKING", "IDLE", note="reason=NO_UPDATE")
                return "IDLE"
            self._to("CHECKING", "BLOCKED", {"reason": r.code}, f"reason={r.code}")
            return "BLOCKED"
        manifest = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        self._to("CHECKING", "UPDATE_AVAILABLE", {"manifest": manifest, "version": m.version, "required": kind == "required"},
                 f"version={m.version} kind={kind}")
        return "UPDATE_AVAILABLE"

    def _download(self) -> str:
        st = self.store.load()
        m = verify_signed_manifest(st["data"]["manifest"], self.policy)
        dest = self.paths.download(m.version)
        job = st["data"].get("bits_job_id")
        if not job or not self.ops.bits_exists(job):
            job = self.ops.bits_start(m.installer_url, dest + ".partial")
        if st["state"] != "DOWNLOADING":
            self._to(st["state"], "DOWNLOADING", {"bits_job_id": job}, f"job={job}")
        status, done, total = self.ops.bits_status(job)
        if status == "transferred":
            self.ops.bits_complete(job, dest + ".partial", dest)
            self._to("DOWNLOADING", "DOWNLOADED", {"download_path": dest, "bytes": done}, f"bytes={done}")
            return "DOWNLOADED"
        if status in ("error", "transient_error", "suspended"):
            self._to("DOWNLOADING", "DOWNLOAD_PAUSED", {"bytes": done}, f"bits={status}")
            return "DOWNLOAD_PAUSED"
        self.store.transition("DOWNLOADING", "DOWNLOADING", {"bytes": done, "total": total})
        return "DOWNLOADING"

    def _verify(self) -> str:
        st = self.store.load()
        if st["state"] == "DOWNLOADED":
            self._to("DOWNLOADED", "VERIFYING")
        m = verify_signed_manifest(st["data"]["manifest"], self.policy)
        path = self.paths.download(m.version)
        try:
            validate_manifest(m, self.policy, self.installed, self.store.failed_versions())
            with self.ops.open_locked(path) as f:
                if f.sha256() != m.sha256:
                    raise Rejected("PACKAGE_HASH_MISMATCH")
                evaluate_signature(self.ops.inspect(f, cache_only=False), self.policy)
        except Rejected as r:
            self.ops.delete_download(m.version)
            self._to("VERIFYING", "BLOCKED", {"reason": r.code}, f"reason={r.code}")
            return "BLOCKED"
        self._to("VERIFYING", "VERIFIED", {"sha256": m.sha256}, f"sha256={m.sha256}")
        return "VERIFIED"

    def _schedule(self) -> str:
        st = self.store.load()
        req = {"request_version": 1, "operation": "install", "request_id": secrets.token_hex(16),
               "manifest": st["data"]["manifest"], "expected_version": st["data"]["version"], "created_utc": _now()}
        self.ops.write_request(self.paths.request, json.dumps(req, sort_keys=True).encode("utf-8"))
        self._to("VERIFIED", "SCHEDULED", {"request_id": req["request_id"], "scheduled_utc": _now()},
                 f"request={req['request_id']}")
        self.ops.start_broker()
        return "SCHEDULED"


class Broker:
    def __init__(self, ops, policy, installed_version: str, data_root: str, log, auto_install: bool):
        self.ops, self.policy, self.installed, self.log, self.auto = ops, policy, installed_version, log, auto_install
        self.paths = Paths(data_root)
        self.store = UpdateStateStore(self.paths.state)

    def _support(self, reason: str, version: str | None = None) -> str:
        cur = self.store.load()["state"]
        if cur != "FAILED_SUPPORT_REQUIRED":
            self.store.transition(cur, "FAILED_SUPPORT_REQUIRED", {"reason": reason}, f"reason={reason}")
        if version:
            self.store.mark_failed(version)
        self.log.error("update broker: FAILED_SUPPORT_REQUIRED reason=%s", reason)
        return "FAILED_SUPPORT_REQUIRED"

    def _block(self, code: str, version: str | None = None) -> str:
        if version:
            self.ops.delete_staging(version)
        self.store.transition("SCHEDULED", "BLOCKED", {"reason": code}, f"reason={code}")
        self.log.warning("update broker: blocked reason=%s", code)
        return "BLOCKED"

    def run(self) -> str:
        st = self.store.load()
        if st["state"] in INSTALL_STATES:
            return self.reconcile(None)
        try:
            taken = self.ops.take_request(self.paths.request)  # (raw, provenance) and deleted; None when absent
        except Rejected as r:
            self.log.warning("update broker: rejected request reason=%s", r.code)
            return self._block(r.code) if st["state"] == "SCHEDULED" else st["state"]
        if st["state"] != "SCHEDULED":
            if taken is not None:
                self.log.warning("update broker: rejected request reason=REQUEST_NOT_AUTHORIZED (state %s)", st["state"])
            return st["state"]
        if taken is None:
            return self._block("REQUEST_MISSING")
        raw, provenance = taken
        version, launched = None, False
        try:
            authorize_request_provenance(provenance)
            if not self.auto:
                raise Rejected("AUTO_UPDATE_DISABLED")
            req, m = validate_request(raw, self.policy, self.installed, self.store.failed_versions())
            version = m.version
            if req["request_id"] != st["data"].get("request_id"):
                raise Rejected("REQUEST_NOT_AUTHORIZED")
            staged, argv = self.paths.staging(version), self.paths.installer_argv(version)
            assert_fixed_argv(argv, staged, self.paths.broker_log)
            self.ops.stage(self.paths.download(version), staged)  # reparse/owner checks + copy into SYSTEM-only dir
            with self.ops.open_locked(staged) as f:
                if os.path.normcase(f.path) != os.path.normcase(staged):
                    raise Rejected("STAGED_PATH_MISMATCH")
                if f.sha256() != m.sha256:
                    raise Rejected("PACKAGE_HASH_MISMATCH")
                evaluate_signature(self.ops.inspect(f, cache_only=True), self.policy)
                prior = (self.ops.coordinator_state() or {}).get("attempt_id")
                self.store.transition("SCHEDULED", "PREFLIGHT", {"staged_sha256": m.sha256, "expected_version": version,
                                                                 "prior_coordinator_attempt": prior}, f"version={version}")
                launched = True
                code = self.ops.run_installer(f, argv)  # started while the write-denying handle is held
        except Rejected as r:
            if not launched:
                return self._block(r.code, version)
            self.log.error("update broker: installer launch outcome unknown (%s); reconciling", r.code)
            return self.reconcile(None)
        except Exception as e:  # noqa: BLE001
            if not launched:
                self.log.error("update broker: preflight error %s", type(e).__name__)
                return self._block("BROKER_PREFLIGHT_ERROR", version)
            self.log.error("update broker: installer launch outcome unknown (%s); reconciling", type(e).__name__)
            return self.reconcile(None)
        self.log.info("update broker: installer exit %s (not trusted on its own)", code)
        return self.reconcile(code)

    def _identity_is(self, version: str) -> bool:
        """Installed exe --build-info AND the running /api/version must both report `version` and the same build SHA."""
        i = self.ops.installed_identity()
        return (i.get("exe_version") == version and i.get("api_version") == version
                and bool(i.get("exe_sha")) and i.get("exe_sha") == i.get("api_sha"))

    def reconcile(self, exit_code) -> str:
        st = self.store.load()
        expected = st["data"].get("expected_version")
        if not expected:
            return self._support("STATE_WITHOUT_EXPECTED_VERSION")
        coord = self.ops.coordinator_state()
        if exit_code is None and coord and coord.get("state") not in TERMINAL_COORD and not self.ops.installer_running():
            self.ops.coordinator_resume()  # the existing transactional recovery; it never moves forward
            coord = self.ops.coordinator_state()
        stale = bool(coord) and coord.get("attempt_id") == st["data"].get("prior_coordinator_attempt")
        if not coord or coord.get("target_version") != expected or stale:
            if exit_code is None and self.ops.installer_running():
                return st["state"]  # setup is still running; wait for its evidence
            return self._support("COORDINATOR_EVIDENCE_STALE" if stale else "COORDINATOR_EVIDENCE_MISSING", expected)
        rec = st["data"].get("coordinator_attempt")
        if rec and rec != coord.get("attempt_id"):
            return self._support("COORDINATOR_ATTEMPT_MISMATCH", expected)
        target = COORD_TO_UPDATE.get(coord.get("state"))
        if not target:
            return self._support("COORDINATOR_STATE_UNKNOWN", expected)
        if target == "FAILED_SUPPORT_REQUIRED":
            return self._support("RECOVERY_FAILED", expected)
        mirror = {"SUCCEEDED": "HEALTH_CHECKING", "ROLLED_BACK": "RECOVERING"}.get(target, target)
        self.store.reconcile(mirror, {"coordinator_attempt": coord.get("attempt_id")})
        if target == "SUCCEEDED":
            if not self._identity_is(expected):
                return self._support("BUILD_IDENTITY_MISMATCH", expected)
            self.store.transition("HEALTH_CHECKING", "SUCCEEDED", {"version": expected, "completed_utc": _now()},
                                  f"version={expected}")
            self.ops.delete_staging(expected)
            self.ops.delete_download(expected)
            return "SUCCEEDED"
        if target == "ROLLED_BACK":
            self.store.mark_failed(expected)
            if not self._identity_is(self.installed):
                return self._support("ROLLBACK_IDENTITY_MISMATCH")
            self.store.transition("RECOVERING", "ROLLED_BACK", {"reason": "UPDATE_FAILED_PREVIOUS_RESTORED",
                                                                "previous": self.installed}, "previous restored")
            self.ops.delete_staging(expected)
            return "ROLLED_BACK"
        if exit_code is not None or not self.ops.installer_running():
            return self._support("COORDINATOR_NOT_TERMINAL", expected)
        return target
