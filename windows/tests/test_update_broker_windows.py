"""Windows-only half of the RoofSpanUpdateBroker security tests: real owners/DACLs, junctions and share modes.

These exercise Win32 APIs (GetSecurityInfo, CreateFile share modes, NTFS junctions, `sc showsid`) that do not
exist on Linux, so they are skipped there. They run - with skips treated as failures - in the
`bundle-compile` job (windows-latest) of .github/workflows/windows-build-scripts.yml.
"""
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="WINDOWS-ONLY: Win32 security descriptors, share modes and junctions; runs in windows-build-scripts.yml "
           "bundle-compile 'Update broker Windows security tests' (skips fail there)")

SYSTEM, ADMINS, USERS = "S-1-5-18", "S-1-5-32-544", "S-1-5-32-545"


def _icacls(path, *args):
    subprocess.run(["icacls", str(path), *args], check=True, capture_output=True)


def _protect(path):
    """The MSI's update-folder ACL: SYSTEM + Administrators only, no inheritance, owned by SYSTEM."""
    _icacls(path, "/inheritance:r", "/grant:r", f"*{SYSTEM}:(OI)(CI)F", f"*{ADMINS}:(OI)(CI)F")
    _icacls(path, "/setowner", f"*{SYSTEM}", "/T")


@pytest.fixture
def ops(tmp_path):
    from updater.winupdate import WinUpdateOps
    data = tmp_path / "RoofSpan"
    (data / "update" / "requests").mkdir(parents=True)
    return WinUpdateOps(str(data), str(tmp_path / "Program Files" / "RoofSpan Office"))


def _write_request(ops, body=b'{"x":1}'):
    path = os.path.join(ops.update_root, "requests", "request.json")
    with open(path, "wb") as f:
        f.write(body)
    _protect(os.path.dirname(path))
    _icacls(path, "/reset")
    _icacls(path, "/setowner", f"*{SYSTEM}")
    return path


def test_service_sid_matches_windows_sc_showsid():
    from updater.policy import service_sid
    out = subprocess.run(["sc", "showsid", "RoofSpanUpdateService"], capture_output=True, text=True).stdout
    assert service_sid("RoofSpanUpdateService") in out


def test_take_request_reports_real_owner_and_writers_and_consumes_file(ops):
    from updater.policy import authorize_request_provenance
    path = _write_request(ops)
    raw, prov = ops.take_request(path)
    assert raw == b'{"x":1}' and not os.path.exists(path)
    assert prov["file"]["owner"] == SYSTEM and set(prov["file"]["writers"]) <= {SYSTEM, ADMINS}
    authorize_request_provenance(prov)


def test_request_writable_by_users_is_rejected(ops):
    from updater.policy import Rejected, authorize_request_provenance
    path = _write_request(ops)
    _icacls(path, "/grant", f"*{USERS}:(W)")
    _, prov = ops.take_request(path)
    assert USERS in prov["file"]["writers"]
    with pytest.raises(Rejected) as e:
        authorize_request_provenance(prov)
    assert e.value.code == "REQUEST_ACL_TOO_BROAD"


def test_request_owned_by_interactive_user_is_rejected(ops):
    import win32api
    import win32security
    from updater.policy import Rejected, authorize_request_provenance
    path = _write_request(ops)
    user_sid = win32security.ConvertSidToStringSid(
        win32security.LookupAccountName(None, win32api.GetUserNameEx(win32api.NameSamCompatible))[0])
    _icacls(path, "/setowner", f"*{user_sid}")
    _, prov = ops.take_request(path)
    with pytest.raises(Rejected) as e:
        authorize_request_provenance(prov)
    assert e.value.code == "REQUEST_NOT_AUTHORIZED"


def test_junctioned_request_folder_is_refused(ops, tmp_path):
    from updater.policy import Rejected
    target = tmp_path / "attacker"
    target.mkdir()
    req_dir = os.path.join(ops.update_root, "requests")
    os.rmdir(req_dir)
    subprocess.run(["cmd", "/c", "mklink", "/J", req_dir, str(target)], check=True, capture_output=True)
    (target / "request.json").write_bytes(b"{}")
    with pytest.raises(Rejected) as e:
        ops.take_request(os.path.join(req_dir, "request.json"))
    assert e.value.code == "PATH_REPARSE_POINT"


def test_locked_installer_cannot_be_modified_or_deleted_while_open(ops):
    path = os.path.join(ops.update_root, "broker", "staging", "1.1.0", "RoofSpanSetup.exe")
    os.makedirs(os.path.dirname(path))
    with open(path, "wb") as f:
        f.write(b"MZ" + b"\0" * 64)
    with ops.open_locked(path) as locked:
        with pytest.raises(PermissionError):
            open(path, "ab").close()
        with pytest.raises(PermissionError):
            os.remove(path)
        assert len(locked.sha256()) == 64


def test_run_installer_refuses_any_non_fixed_command_line(ops):
    from updater.autoupdate import Paths
    from updater.policy import Rejected

    class _F:
        path = Paths(ops.data_root).staging("1.1.0")

    log = Paths(ops.data_root).broker_log
    for argv in ([_F.path, "/quiet", "/norestart", "/log", log, "/x"], [r"C:\Windows\System32\cmd.exe", "/c", "x"]):
        with pytest.raises(Rejected):
            ops.run_installer(_F(), argv)
