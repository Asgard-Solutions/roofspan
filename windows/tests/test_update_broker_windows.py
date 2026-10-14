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

import re
from pathlib import Path

SYSTEM, ADMINS, USERS = "S-1-5-18", "S-1-5-32-544", "S-1-5-32-545"
WXS = Path(__file__).resolve().parents[1] / "installer" / "RoofSpan.wxs"


def production_sddl(directory_id: str) -> str:
    """The exact protected DACL the MSI applies to that update folder (read from RoofSpan.wxs, not restated)."""
    m = re.search(rf'<CreateFolder Directory="{directory_id}"><PermissionEx Sddl="([^"]+)"', WXS.read_text(encoding="utf-8"))
    assert m, f"no SDDL for {directory_id} in RoofSpan.wxs"
    return m.group(1)


def _icacls(path, *args):
    subprocess.run(["icacls", str(path), *args], check=True, capture_output=True)


@pytest.fixture(scope="module", autouse=True)
def _owner_privileges():
    """An elevated admin (the CI runner) may assign SYSTEM as owner only with SeRestorePrivilege enabled; the
    LocalSystem broker can always do it."""
    import win32api
    import win32security
    tok = win32security.OpenProcessToken(win32api.GetCurrentProcess(),
                                         win32security.TOKEN_ADJUST_PRIVILEGES | win32security.TOKEN_QUERY)
    privs = [(win32security.LookupPrivilegeValue(None, n), win32security.SE_PRIVILEGE_ENABLED)
             for n in ("SeRestorePrivilege", "SeTakeOwnershipPrivilege")]
    win32security.AdjustTokenPrivileges(tok, False, privs)


def apply_production_acl(path, directory_id="UpdateRequestsDir"):
    """The product's own ACL routine with the MSI's SDDL for that folder: the WHOLE DACL is replaced (dropping
    any explicit ACE, e.g. the per-user ACE Python puts on temp folders) and the owner becomes SYSTEM."""
    from updater.winupdate import apply_protected_acl
    apply_protected_acl(str(path), production_sddl(directory_id))


@pytest.fixture
def ops(tmp_path):
    from updater.winupdate import WinUpdateOps
    data = tmp_path / "RoofSpan"
    (data / "update" / "requests").mkdir(parents=True)
    return WinUpdateOps(str(data), str(tmp_path / "Program Files" / "RoofSpan Office"))


def _write_request(ops, body=b'{"x":1}'):
    """Like the checker: the request is created INSIDE the protected folder, so it only inherits that ACL."""
    req_dir = os.path.join(ops.update_root, "requests")
    apply_production_acl(req_dir)
    path = os.path.join(req_dir, "request.json")
    with open(path, "wb") as f:
        f.write(body)
    _icacls(path, "/setowner", f"*{SYSTEM}")  # production owner is the checker's service SID; SYSTEM is equally allowed
    return path


def test_production_request_acl_is_exactly_system_admins_and_checker():
    from updater.policy import REQUEST_WRITER_SIDS, service_sid
    sddl = production_sddl("UpdateRequestsDir")
    assert sddl.startswith("D:PAI"), "the request folder DACL must be protected (no inheritance from ProgramData)"
    sids = set(re.findall(r";;;([^)]+)\)", sddl))
    assert sids == {"SY", "BA", service_sid("RoofSpanUpdateService")}
    assert {"S-1-5-18", "S-1-5-32-544", service_sid("RoofSpanUpdateService")} == REQUEST_WRITER_SIDS


def test_service_sid_matches_windows_sc_showsid():
    from updater.policy import service_sid
    out = subprocess.run(["sc", "showsid", "RoofSpanUpdateService"], capture_output=True, text=True).stdout
    assert service_sid("RoofSpanUpdateService") in out


def test_take_request_reports_real_owner_and_writers_and_consumes_file(ops):
    from updater.policy import authorize_request_provenance, service_sid
    path = _write_request(ops)
    raw, prov = ops.take_request(path)
    assert raw == b'{"x":1}' and not os.path.exists(path)
    assert prov["file"]["owner"] == SYSTEM and prov["dir"]["owner"] == SYSTEM
    assert set(prov["file"]["writers"]) == set(prov["dir"]["writers"]) == {SYSTEM, ADMINS, service_sid("RoofSpanUpdateService")}
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
    import hashlib
    path = os.path.join(ops.update_root, "broker", "staging", "1.1.0", "RoofSpanSetup.exe")
    os.makedirs(os.path.dirname(path))
    data = b"MZ" + os.urandom(3 * (1 << 20))
    with open(path, "wb") as f:
        f.write(data)
    with ops.open_locked(path) as locked:
        with pytest.raises(PermissionError):
            open(path, "ab").close()
        with pytest.raises(PermissionError):
            os.remove(path)
        assert locked.sha256() == hashlib.sha256(data).hexdigest()  # read through a duplicated 64-bit HANDLE
        assert locked.sha256() == hashlib.sha256(data).hexdigest()  # repeatable: the hash rewinds, never drifts
    open(path, "ab").close()  # released once the broker closes its handle


def test_run_installer_refuses_any_non_fixed_command_line(ops):
    from updater.autoupdate import Paths
    from updater.policy import Rejected

    class _F:
        path = Paths(ops.data_root).staging("1.1.0")

    log = Paths(ops.data_root).broker_log
    for argv in ([_F.path, "/quiet", "/norestart", "/log", log, "/x"], [r"C:\Windows\System32\cmd.exe", "/c", "x"]):
        with pytest.raises(Rejected):
            ops.run_installer(_F(), argv)


def test_stage_replaces_any_preexisting_broker_acl_with_the_product_acl(ops):
    from updater.winupdate import BROKER_SDDL, path_security_facts
    assert BROKER_SDDL == production_sddl("UpdateBrokerDir")
    broker = os.path.join(ops.update_root, "broker")
    os.makedirs(broker)
    _icacls(broker, "/grant", f"*{USERS}:(OI)(CI)F")  # a stray explicit grant must not survive staging
    src_dir = os.path.join(ops.update_root, "downloads", "1.1.0")
    os.makedirs(src_dir)
    apply_production_acl(src_dir, "UpdateDownloadsDir")
    src = os.path.join(src_dir, "RoofSpanSetup.exe")
    with open(src, "wb") as f:
        f.write(b"MZ" + os.urandom(4096))
    dst = os.path.join(broker, "staging", "1.1.0", "RoofSpanSetup.exe")
    ops.stage(src, dst)
    with open(src, "rb") as a, open(dst, "rb") as b:
        assert a.read() == b.read()
    assert path_security_facts(broker)["owner"] == SYSTEM
    for p in (broker, dst):  # dst is owned by its creator (SYSTEM in production); nobody else can write it
        assert set(path_security_facts(p)["writers"]) == {SYSTEM, ADMINS}, (p, path_security_facts(p))
