"""RoofSpanUpdateBroker logic: caller authorization, independent re-verification, fixed paths/arguments and
FAILED_SUPPORT_REQUIRED on ambiguous outcomes. Pure Python over injected ops (the Windows ops have their own
Windows-only tests in test_update_broker_windows.py)."""
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

import pytest

from release import publish
from updater import signing as S
from updater.autoupdate import Broker, Checker, Paths
from updater.manifest import parse_manifest
from updater.policy import (INSTALLER_FIXED_ARGS, REQUEST_WRITER_SIDS, Rejected, TrustPolicy, assert_fixed_argv,
                            authorize_request_provenance, service_sid)
from updater.states import UpdateStateStore

WINDOWS = Path(__file__).resolve().parents[1]
INSTALLED, NEW = "1.0.0", "1.1.0"
PAYLOAD = b"MZ-signed-RoofSpanSetup-1.1.0"
SUBJECT, THUMB = "CN=RoofSpan Inc., O=RoofSpan Inc., C=US", "A" * 40
SVC = service_sid("RoofSpanUpdateService")
GOOD_ACL = {"owner": SVC, "writers": ["S-1-5-18", "S-1-5-32-544", SVC]}
GOOD_PROV = {"file": dict(GOOD_ACL), "dir": {"owner": "S-1-5-18", "writers": ["S-1-5-18", "S-1-5-32-544", SVC]}}
GOOD_SIG = {"signed": True, "trusted": True, "revocation": "good", "timestamped": True, "subject": SUBJECT,
            "thumbprint": THUMB.lower()}


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module")
def keys():
    return S.generate_keypair()


@pytest.fixture
def policy(keys):
    return TrustPolicy.load(json.dumps({"channel": "stable", "publisher_subject": SUBJECT,
                                        "publisher_thumbprints": [THUMB]}), [keys[1]])


def _manifest(keys, version=NEW, payload=PAYLOAD, **over):
    m = publish.build_manifest(version=version, installer_bytes=payload, minimum_supported_version="1.0.0",
                               required=False, signing_private_pem=keys[0])
    if over:  # re-sign a deliberately bad (but correctly signed) manifest
        m.update(over)
        pm = parse_manifest(m)
        m["signature"] = S.sign_manifest(pm, keys[0])
    return m


class _Locked:
    def __init__(self, ops, path):
        self.ops, self.path = ops, path

    def sha256(self):
        return hashlib.sha256(self.ops.files[self.path]).hexdigest()


class FakeOps:
    """In-memory stand-in for WinUpdateOps (checker + broker)."""

    def __init__(self, root, manifest=None):
        self.paths = Paths(root)
        self.files, self.request, self.manifest = {}, None, manifest
        self.sig, self.coord, self.running = dict(GOOD_SIG), None, False
        self.identity = {"exe_version": NEW, "api_version": NEW, "exe_sha": "abc", "api_sha": "abc"}
        self.installer_runs, self.locked_now, self.resumed, self.staged_deleted = [], set(), 0, []
        self.on_install = lambda: {"attempt_id": "new-attempt", "target_version": NEW, "state": "COMPLETE"}
        self.install_raises = None
        self.stage_raises = None

    # checker side
    def fetch_manifest(self):
        return json.dumps(self.manifest)

    def bits_exists(self, job):
        return False

    def bits_start(self, url, dest):
        self.files[dest] = PAYLOAD
        return "job-1"

    def bits_status(self, job):
        return "transferred", len(PAYLOAD), len(PAYLOAD)

    def bits_complete(self, job, partial, dest):
        self.files[dest] = self.files.pop(partial)

    def write_request(self, path, data):
        assert path == self.paths.request
        self.request = (data, GOOD_PROV)

    def start_broker(self):
        pass

    # shared
    @contextlib.contextmanager
    def open_locked(self, path):
        if path not in self.files:
            raise Rejected("PACKAGE_MISSING_OR_NOT_REGULAR")
        self.locked_now.add(path)
        try:
            yield _Locked(self, path)
        finally:
            self.locked_now.discard(path)

    def inspect(self, f, cache_only):
        return dict(self.sig)

    def delete_download(self, version):
        self.files.pop(self.paths.download(version), None)

    # broker side
    def take_request(self, path):
        assert path == self.paths.request
        req, self.request = self.request, None
        return req

    def stage(self, src, dst):
        if self.stage_raises:
            raise self.stage_raises
        if src not in self.files:
            raise Rejected("PACKAGE_MISSING_OR_NOT_REGULAR")
        self.files[dst] = self.files[src]

    def run_installer(self, f, argv):
        assert_fixed_argv(argv, f.path, self.paths.broker_log)
        assert f.path in self.locked_now, "installer must start while the write-denying handle is held"
        self.installer_runs.append(list(argv))
        if self.install_raises:
            raise self.install_raises
        self.coord = self.on_install()
        return 0

    def delete_staging(self, version):
        self.staged_deleted.append(version)
        self.files.pop(self.paths.staging(version), None)

    def coordinator_state(self):
        return self.coord

    def coordinator_resume(self):
        self.resumed += 1

    def installer_running(self):
        return self.running

    def installed_identity(self):
        return dict(self.identity)


class _Log:
    def __init__(self):
        self.lines = []

    def _rec(self, level, msg, *a):
        self.lines.append((level, msg % a if a else msg))

    def info(self, msg, *a):
        self._rec("info", msg, *a)

    def warning(self, msg, *a):
        self._rec("warning", msg, *a)

    def error(self, msg, *a):
        self._rec("error", msg, *a)


def _request(manifest, request_id="ab" * 16, **over):
    req = {"request_version": 1, "operation": "install", "request_id": request_id, "manifest": manifest,
           "expected_version": manifest["version"], "created_utc": _now()}
    req.update(over)
    return json.dumps(req, sort_keys=True).encode("utf-8")


def _scheduled(tmp_path, keys, manifest=None, request=None, prov=GOOD_PROV, request_id="ab" * 16):
    manifest = manifest or _manifest(keys)
    ops = FakeOps(str(tmp_path), manifest)
    ops.files[ops.paths.download(manifest["version"])] = PAYLOAD
    store = UpdateStateStore(ops.paths.state)
    store._write({"state": "SCHEDULED", "seq": 7, "updated_utc": _now(),
                  "data": {"manifest": manifest, "version": manifest["version"], "request_id": request_id}}, "test")
    ops.request = (request if request is not None else _request(manifest), prov)
    return ops, store


def _broker(ops, policy, tmp_path, auto=True, log=None):
    return Broker(ops, policy, INSTALLED, str(tmp_path), log or _Log(), auto)


# ---- happy path + fixed command line -----------------------------------------------------------------------------

def test_broker_installs_verified_request_with_fixed_arguments(tmp_path, policy, keys):
    ops, store = _scheduled(tmp_path, keys)
    assert _broker(ops, policy, tmp_path).run() == "SUCCEEDED"
    staged = os.path.join(str(tmp_path), "update", "broker", "staging", NEW, "RoofSpanSetup.exe")
    log = os.path.join(str(tmp_path), "logs", "update-broker-setup.log")
    assert ops.installer_runs == [[staged, "/quiet", "/norestart", "/log", log]]
    assert store.load()["data"]["coordinator_attempt"] == "new-attempt"
    assert ops.request is None, "the request is consumed exactly once"


def test_fixed_argv_rejects_any_variation():
    staged, log = r"C:\ProgramData\RoofSpan\update\broker\staging\1.1.0\RoofSpanSetup.exe", r"C:\l.log"
    assert_fixed_argv([staged, *INSTALLER_FIXED_ARGS, log], staged, log)
    for bad in ([staged, "/quiet", "/norestart", "/log", log, "/extra"], [staged, "/passive", "/norestart", "/log", log],
                [r"C:\Users\x\evil.exe", *INSTALLER_FIXED_ARGS, log], [staged, *INSTALLER_FIXED_ARGS, r"C:\other.log"]):
        with pytest.raises(Rejected) as e:
            assert_fixed_argv(bad, staged, log)
        assert e.value.code == "INSTALLER_ARGV_NOT_FIXED"


def test_paths_are_derived_only_from_fixed_root_and_semver():
    p = Paths(r"/fixed")
    assert p.staging("1.2.3") == os.path.join("/fixed", "update", "broker", "staging", "1.2.3", "RoofSpanSetup.exe")
    for evil in ("../../Windows", "1.2.3/../../x", "1.2.3\\..\\x", "", None, "1.2"):
        with pytest.raises(Rejected):
            p.staging(evil)


@pytest.mark.parametrize("field,value", [("installer_path", r"C:\evil.exe"), ("arguments", ["/x"]),
                                          ("staging_dir", r"C:\Users\Public"), ("command", "cmd /c calc")])
def test_request_with_path_argument_or_command_fields_is_rejected(tmp_path, policy, keys, field, value):
    m = _manifest(keys)
    req = json.loads(_request(m))
    req[field] = value
    ops, store = _scheduled(tmp_path, keys, m, json.dumps(req).encode())
    assert _broker(ops, policy, tmp_path).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == "REQUEST_UNEXPECTED_FIELDS"
    assert ops.installer_runs == []


def test_request_operation_and_size_are_constrained(tmp_path, policy, keys):
    m = _manifest(keys)
    ops, store = _scheduled(tmp_path, keys, m, _request(m, operation="uninstall"))
    assert _broker(ops, policy, tmp_path).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == "REQUEST_OPERATION_NOT_ALLOWED"
    ops2, store2 = _scheduled(tmp_path / "b", keys, m, b"{" + b" " * (300 * 1024) + b"}")
    assert _broker(ops2, policy, tmp_path / "b").run() == "BLOCKED"
    assert store2.load()["data"]["reason"] == "REQUEST_MALFORMED"


# ---- caller authorization ----------------------------------------------------------------------------------------

def test_service_sid_matches_windows_and_wix_acl():
    assert service_sid("TrustedInstaller") == "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
    wxs = (WINDOWS / "installer" / "RoofSpan.wxs").read_text(encoding="utf-8")
    assert service_sid("RoofSpanUpdateService") in wxs
    assert REQUEST_WRITER_SIDS == {"S-1-5-18", "S-1-5-32-544", service_sid("RoofSpanUpdateService")}


@pytest.mark.parametrize("prov,code", [
    (None, "REQUEST_NOT_AUTHORIZED"),
    ({}, "REQUEST_NOT_AUTHORIZED"),
    ({"file": {"owner": "S-1-5-21-1-2-3-1001", "writers": ["S-1-5-18"]}, "dir": GOOD_PROV["dir"]}, "REQUEST_NOT_AUTHORIZED"),
    ({"file": GOOD_ACL, "dir": {"owner": "S-1-5-32-545", "writers": ["S-1-5-18"]}}, "REQUEST_NOT_AUTHORIZED"),
    ({"file": {"owner": SVC, "writers": ["S-1-5-18", "S-1-5-32-545"]}, "dir": GOOD_PROV["dir"]}, "REQUEST_ACL_TOO_BROAD"),
    ({"file": GOOD_ACL, "dir": {"owner": "S-1-5-18", "writers": ["S-1-1-0"]}}, "REQUEST_ACL_TOO_BROAD"),
    ({"file": {"owner": SVC}, "dir": GOOD_PROV["dir"]}, "REQUEST_NOT_AUTHORIZED"),
])
def test_unauthorized_request_writer_is_rejected_before_anything_runs(tmp_path, policy, keys, prov, code):
    ops, store = _scheduled(tmp_path, keys, prov=prov)
    assert _broker(ops, policy, tmp_path).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == code
    assert ops.installer_runs == [] and ops.paths.staging(NEW) not in ops.files


def test_authorize_provenance_accepts_only_checker_system_admins():
    authorize_request_provenance(GOOD_PROV)
    for owner in ("S-1-5-18", "S-1-5-32-544", SVC):
        authorize_request_provenance({"file": {"owner": owner, "writers": [owner]}, "dir": GOOD_PROV["dir"]})


def test_request_id_must_match_the_scheduled_state(tmp_path, policy, keys):
    m = _manifest(keys)
    ops, store = _scheduled(tmp_path, keys, m, _request(m, request_id="cd" * 16))
    assert _broker(ops, policy, tmp_path).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == "REQUEST_NOT_AUTHORIZED" and ops.installer_runs == []


@pytest.mark.parametrize("state", ["IDLE", "VERIFIED", "BLOCKED", "SUCCEEDED", "FAILED_SUPPORT_REQUIRED"])
def test_request_outside_scheduled_state_is_consumed_and_ignored(tmp_path, policy, keys, state):
    ops, store = _scheduled(tmp_path, keys)
    st = store.load()
    st["state"] = state
    store._write(st, "test")
    assert _broker(ops, policy, tmp_path).run() == state
    assert ops.request is None and ops.installer_runs == [] and store.load()["state"] == state


def test_scheduled_without_request_does_not_loop(tmp_path, policy, keys):
    ops, store = _scheduled(tmp_path, keys)
    ops.request = None
    assert _broker(ops, policy, tmp_path).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == "REQUEST_MISSING"


# ---- the broker repeats every security check itself -------------------------------------------------------------

def test_broker_rejects_tampered_manifest_even_if_checker_verified(tmp_path, policy, keys):
    m = _manifest(keys)
    m["sha256"] = hashlib.sha256(b"something else").hexdigest()  # signature no longer covers it
    ops, store = _scheduled(tmp_path, keys, m)
    assert _broker(ops, policy, tmp_path).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == "MANIFEST_SIGNATURE_INVALID" and ops.installer_runs == []


def test_broker_rejects_manifest_signed_by_unknown_key(tmp_path, policy, keys):
    other = S.generate_keypair()
    m = _manifest(other)
    ops, store = _scheduled(tmp_path, keys, m)
    assert _broker(ops, policy, tmp_path).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == "MANIFEST_SIGNATURE_INVALID"


def test_broker_hashes_its_own_staged_copy(tmp_path, policy, keys):
    ops, store = _scheduled(tmp_path, keys)
    ops.files[ops.paths.download(NEW)] = b"MZ-swapped-after-checker-verified"
    assert _broker(ops, policy, tmp_path).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == "PACKAGE_HASH_MISMATCH"
    assert ops.installer_runs == [] and NEW in ops.staged_deleted


@pytest.mark.parametrize("sig,code", [
    ({"signed": False}, "AUTHENTICODE_UNSIGNED"),
    ({"revocation": "revoked"}, "AUTHENTICODE_REVOKED"),
    ({"revocation": "unknown"}, "AUTHENTICODE_REVOCATION_UNKNOWN"),
    ({"trusted": False}, "AUTHENTICODE_UNTRUSTED"),
    ({"timestamped": False}, "AUTHENTICODE_NO_TIMESTAMP"),
    ({"subject": "CN=Someone Else"}, "PUBLISHER_MISMATCH"),
    ({"thumbprint": "B" * 40}, "PUBLISHER_THUMBPRINT_NOT_APPROVED"),
])
def test_broker_enforces_authenticode_policy(tmp_path, policy, keys, sig, code):
    ops, store = _scheduled(tmp_path, keys)
    ops.sig.update(sig)
    assert _broker(ops, policy, tmp_path).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == code and ops.installer_runs == []


@pytest.mark.parametrize("over,code", [
    ({"installer_url": "https://downloads.roofspan.io/releases/RoofSpanSetup-9.9.9.exe"}, "URL_NOT_ALLOWED"),
    ({"installer_url": "https://downloads.roofspan.io.evil.example/releases/RoofSpanSetup-1.1.0.exe"}, "MANIFEST_MALFORMED"),
    ({"installer_url": "https://downloads.roofspan.io/releases/RoofSpanSetup-1.1.0.exe?redirect=evil"}, "URL_NOT_ALLOWED"),
    ({"installer_url": "https://downloads.roofspan.io/windows/RoofSpanSetup-1.1.0.exe"}, "URL_NOT_ALLOWED"),
    ({"channel": "beta"}, "CHANNEL_MISMATCH"),
    ({"expires_at": "2020-01-01T00:00:00Z"}, "MANIFEST_EXPIRED"),
])
def test_broker_revalidates_signed_manifest_contents(tmp_path, policy, keys, over, code):
    m = _manifest(keys, **over) if code != "MANIFEST_MALFORMED" else None
    if m is None:  # parse_manifest refuses foreign hosts, so the broker reports the manifest as malformed
        m = _manifest(keys)
        m["installer_url"] = over["installer_url"]
    ops, store = _scheduled(tmp_path, keys, m)
    assert _broker(ops, policy, tmp_path).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == code and ops.installer_runs == []


def test_broker_rejects_downgrade_and_previously_failed_versions(tmp_path, policy, keys):
    old = _manifest(keys, version="0.9.0")
    ops, store = _scheduled(tmp_path, keys, old)
    assert _broker(ops, policy, tmp_path).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == "DOWNGRADE_REJECTED"

    ops2, store2 = _scheduled(tmp_path / "f", keys)
    store2.mark_failed(NEW)
    assert _broker(ops2, policy, tmp_path / "f").run() == "BLOCKED"
    assert store2.load()["data"]["reason"] == "VERSION_PREVIOUSLY_FAILED" and ops2.installer_runs == []


def test_broker_refuses_when_auto_install_disabled(tmp_path, policy, keys):
    ops, store = _scheduled(tmp_path, keys)
    assert _broker(ops, policy, tmp_path, auto=False).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == "AUTO_UPDATE_DISABLED" and ops.installer_runs == []


def test_unexpected_preflight_error_blocks_without_running(tmp_path, policy, keys):
    ops, store = _scheduled(tmp_path, keys)
    ops.stage_raises = PermissionError("icacls failed")
    assert _broker(ops, policy, tmp_path).run() == "BLOCKED"
    assert store.load()["data"]["reason"] == "BROKER_PREFLIGHT_ERROR" and ops.installer_runs == []


# ---- ambiguous / unrecoverable outcomes -> FAILED_SUPPORT_REQUIRED ---------------------------------------------

def _support_case(tmp_path, policy, keys, **ops_over):
    ops, store = _scheduled(tmp_path, keys)
    for k, v in ops_over.items():
        setattr(ops, k, v)
    state = _broker(ops, policy, tmp_path).run()
    return state, store.load()["data"].get("reason"), store, ops


@pytest.mark.parametrize("coord,reason", [
    (None, "COORDINATOR_EVIDENCE_MISSING"),
    ({"attempt_id": "new-attempt", "target_version": "2.0.0", "state": "COMPLETE"}, "COORDINATOR_EVIDENCE_MISSING"),
    ({"attempt_id": "new-attempt", "target_version": NEW, "state": "FAILED"}, "RECOVERY_FAILED"),
    ({"attempt_id": "new-attempt", "target_version": NEW, "state": "SOMETHING_NEW"}, "COORDINATOR_STATE_UNKNOWN"),
    ({"attempt_id": "new-attempt", "target_version": NEW, "state": "MIGRATING"}, "COORDINATOR_NOT_TERMINAL"),
])
def test_installer_exit_without_conclusive_evidence_requires_support(tmp_path, policy, keys, coord, reason):
    state, got, store, _ = _support_case(tmp_path, policy, keys, on_install=lambda: coord)
    assert (state, got) == ("FAILED_SUPPORT_REQUIRED", reason)
    assert NEW in store.failed_versions(), "an ambiguous version is never retried automatically"


def test_stale_coordinator_evidence_from_previous_attempt_requires_support(tmp_path, policy, keys):
    ops, store = _scheduled(tmp_path, keys)
    prior = {"attempt_id": "old-attempt", "target_version": NEW, "state": "ROLLED_BACK"}
    ops.coord, ops.on_install = prior, (lambda: prior)  # setup exited without writing new evidence
    assert _broker(ops, policy, tmp_path).run() == "FAILED_SUPPORT_REQUIRED"
    assert store.load()["data"]["reason"] == "COORDINATOR_EVIDENCE_STALE"


def test_success_with_wrong_build_identity_requires_support(tmp_path, policy, keys):
    ops, store = _scheduled(tmp_path, keys)
    ops.identity = {"exe_version": NEW, "api_version": INSTALLED, "exe_sha": "abc", "api_sha": "zzz"}
    assert _broker(ops, policy, tmp_path).run() == "FAILED_SUPPORT_REQUIRED"
    assert store.load()["data"]["reason"] == "BUILD_IDENTITY_MISMATCH"


def test_rollback_is_recorded_and_unverified_rollback_requires_support(tmp_path, policy, keys):
    rb = lambda: {"attempt_id": "new-attempt", "target_version": NEW, "state": "ROLLED_BACK"}  # noqa: E731
    ops, store = _scheduled(tmp_path, keys)
    ops.on_install = rb
    ops.identity = {"exe_version": INSTALLED, "api_version": INSTALLED, "exe_sha": "old", "api_sha": "old"}
    assert _broker(ops, policy, tmp_path).run() == "ROLLED_BACK"
    assert NEW in store.failed_versions()

    ops2, store2 = _scheduled(tmp_path / "b", keys)
    ops2.on_install = rb
    ops2.identity = {"exe_version": NEW, "api_version": None, "exe_sha": "x", "api_sha": None}
    assert _broker(ops2, policy, tmp_path / "b").run() == "FAILED_SUPPORT_REQUIRED"
    assert store2.load()["data"]["reason"] == "ROLLBACK_IDENTITY_MISMATCH"


def test_installer_launch_error_is_reconciled_not_guessed(tmp_path, policy, keys):
    state, reason, _, ops = _support_case(tmp_path, policy, keys, install_raises=OSError("timeout"))
    assert (state, reason) == ("FAILED_SUPPORT_REQUIRED", "COORDINATOR_EVIDENCE_MISSING")


def test_restart_mid_install_waits_while_setup_runs_then_resumes_coordinator(tmp_path, policy, keys):
    ops, store = _scheduled(tmp_path, keys)
    st = store.load()
    st["state"], st["data"]["expected_version"], st["data"]["prior_coordinator_attempt"] = "PREFLIGHT", NEW, None
    store._write(st, "test")
    ops.running = True
    assert _broker(ops, policy, tmp_path).run() == "PREFLIGHT"  # no evidence yet, setup still running: wait
    ops.running, ops.coord = False, {"attempt_id": "a1", "target_version": NEW, "state": "INSTALLING"}
    assert _broker(ops, policy, tmp_path).run() == "FAILED_SUPPORT_REQUIRED"  # resume did not reach a terminal state
    assert ops.resumed == 1 and store.load()["data"]["reason"] == "COORDINATOR_NOT_TERMINAL"


def test_install_state_without_expected_version_requires_support(tmp_path, policy, keys):
    ops, store = _scheduled(tmp_path, keys)
    store._write({"state": "INSTALLING", "seq": 9, "updated_utc": _now(), "data": {}}, "test")
    assert _broker(ops, policy, tmp_path).run() == "FAILED_SUPPORT_REQUIRED"
    assert store.load()["data"]["reason"] == "STATE_WITHOUT_EXPECTED_VERSION"


def test_corrupt_state_file_is_support_required_and_nothing_runs(tmp_path, policy, keys):
    ops, store = _scheduled(tmp_path, keys)
    Path(store.path).write_text("{not json", encoding="utf-8")
    assert _broker(ops, policy, tmp_path).run() == "FAILED_SUPPORT_REQUIRED"
    assert ops.installer_runs == [] and ops.request is None


def test_failed_support_required_stops_checker_retries(tmp_path, policy, keys):
    ops, store = _scheduled(tmp_path, keys)
    store._write({"state": "FAILED_SUPPORT_REQUIRED", "seq": 3, "updated_utc": _now(), "data": {"reason": "X"}}, "t")
    assert Checker(ops, policy, INSTALLED, str(tmp_path), _Log(), True).tick() == "FAILED_SUPPORT_REQUIRED"


# ---- checker -> broker handoff with real signed manifests --------------------------------------------------------

def test_checker_schedules_and_broker_installs_end_to_end(tmp_path, policy, keys):
    ops = FakeOps(str(tmp_path), _manifest(keys))
    checker = Checker(ops, policy, INSTALLED, str(tmp_path), _Log(), True)
    assert checker.tick() == "SCHEDULED"
    assert set(json.loads(ops.request[0])) == {"request_version", "operation", "request_id", "manifest",
                                               "expected_version", "created_utc"}
    assert _broker(ops, policy, tmp_path).run() == "SUCCEEDED"
    assert ops.paths.download(NEW) not in ops.files and ops.paths.staging(NEW) not in ops.files


def test_publisher_manifest_is_accepted_by_update_policy(keys, policy):
    from updater.policy import validate_manifest, verify_signed_manifest
    m = verify_signed_manifest(_manifest(keys), policy)
    assert validate_manifest(m, policy, INSTALLED, set()) == "optional"
    assert m.installer_url == publish.versioned_url(NEW)
