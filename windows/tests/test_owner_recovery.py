"""Static validation of the RoofSpan Owner Recovery packaging + local-only trust boundary (in-container).
DB-backed recovery logic is covered by backend/tests/test_token_recovery.py.
"""
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # windows/
INSTALLER = os.path.join(HERE, "installer")
WINBUILD = os.path.join(HERE, "winbuild")

from winbuild.targets import TOOL_TARGETS, TOOL_EXES, SERVICE_EXES  # noqa: E402


def _read(p):
    with open(p) as f:
        return f.read()


def test_recovery_tool_registered_but_not_a_service():
    assert TOOL_TARGETS["RoofSpanOwnerRecovery"] == "owner_recovery.py"
    assert "RoofSpanOwnerRecovery.exe" in TOOL_EXES
    assert "RoofSpanOwnerRecovery.exe" not in SERVICE_EXES  # NOT a Windows service


def test_recovery_spec_exists_and_names_exe():
    spec = os.path.join(WINBUILD, "roofspan-owner-recovery.spec")
    assert os.path.isfile(spec)
    assert 'name="RoofSpanOwnerRecovery"' in _read(spec)


def test_recovery_is_local_only_no_network_listener():
    src = _read(os.path.join(WINBUILD, "owner_recovery.py"))
    for bad in ("FastAPI", "uvicorn", "app.add_middleware", ".listen(", "bind(", "0.0.0.0",
                "boto3", "stripe", "relay", "control_plane", "requests.get", "httpx"):
        assert bad not in src, f"recovery tool must be local-only; found {bad}"


def test_recovery_reuses_hashing_and_bumps_token_version_and_audits():
    src = _read(os.path.join(WINBUILD, "owner_recovery.py"))
    assert "from core import hash_password" in src   # reuse app hashing, no separate crypto
    assert "token_version" in src and "+ 1" in src   # invalidate sessions
    assert 'action="owner.recovery"' in src          # audit event
    assert "getpass" in src                           # never echo password
    assert 'role != "owner"' in src                   # only Owner resettable


def test_recovery_requires_admin_elevation_check():
    src = _read(os.path.join(WINBUILD, "owner_recovery.py"))
    assert "IsUserAnAdmin" in src                      # proper Windows elevation check
    assert "def is_elevated" in src


def test_wix_installs_tool_and_startmenu_shortcut_admin_hint():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    assert r"tools\RoofSpanOwnerRecovery.exe" in wxs        # staged under tools\ (not services\)
    assert "RoofSpan Owner Recovery (Administrator)" in wxs  # shortcut name states admin requirement
    assert "Run as administrator" in wxs
    assert '<ComponentGroupRef Id="Tools" />' in wxs         # wired into the feature
    # must NOT be registered as a Windows service
    assert 'Name="RoofSpanOwnerRecovery"' not in wxs.replace("(Administrator)", "")


def test_build_stages_tool_separately():
    ps = _read(os.path.join(WINBUILD, "build_exes.ps1"))
    assert "roofspan-owner-recovery.spec" in ps
    assert "$ToolsDir" in ps
