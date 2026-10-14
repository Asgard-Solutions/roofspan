"""roofspan-update-broker.exe build -> stage -> WiX packaging chain, and the broker entry's fixed configuration."""
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from winbuild.targets import SERVICE_EXES, SERVICE_TARGETS, SERVICES_BUILD_MANIFEST, WINDOWS_SERVICES

WINDOWS = Path(__file__).resolve().parents[1]
WINBUILD, INSTALLER = WINDOWS / "winbuild", WINDOWS / "installer"
REPO = WINDOWS.parent
PWSH = shutil.which("pwsh")
MODULE = INSTALLER / "ServicesBuild.psm1"
needs_pwsh = pytest.mark.skipif(not PWSH, reason="ENV: pwsh is not installed (CI validate job has it)")


def _read(p):
    return Path(p).read_text(encoding="utf-8")


def _ps_list(text, var):
    m = re.search(rf'\${var}\s*=\s*@\(([^)]*)\)', text)
    assert m, f"${var} list not found"
    return re.findall(r'"([\w.-]+)"', m.group(1))


# ---- one service list everywhere ---------------------------------------------------------------------------------

def test_broker_is_a_first_class_build_target():
    assert SERVICE_TARGETS["roofspan-update-broker"] == "update_broker_entry.py"
    assert "roofspan-update-broker.exe" in SERVICE_EXES and "RoofSpanUpdateBroker" in WINDOWS_SERVICES
    assert SERVICES_BUILD_MANIFEST == "services-build-manifest.json"


def test_every_pipeline_service_list_equals_targets():
    expected = list(SERVICE_TARGETS)
    assert _ps_list(_read(MODULE), "script:RequiredServices") == expected
    build_exes = _read(WINBUILD / "build_exes.ps1")
    assert "$requiredServices = Get-RoofSpanRequiredServices" in build_exes
    assert '$specs = @($requiredServices | ForEach-Object { "$_.spec" })' in build_exes
    assert "$requiredServices = Get-RoofSpanRequiredServices" in _read(INSTALLER / "build.ps1")
    tia = _read(INSTALLER / "Test-InstallerArtifact.ps1")
    assert re.findall(r'"([\w.-]+)"', re.search(r'foreach \(\$svcName in @\(([^)]*)\)\)', tia).group(1)) == expected
    stage = _read(INSTALLER / "stage.ps1")
    for name in expected:
        assert f'"{name}\\{name}.exe"' in stage, f"stage.ps1 must require {name}.exe"
    assert '(Join-Path $services "services-build-manifest.json")' in stage


def test_broker_spec_builds_the_broker_entry_from_source():
    spec = _read(WINBUILD / "roofspan-update-broker.spec")
    assert 'os.path.join(SPECPATH, "update_broker_entry.py")' in spec
    assert 'name="roofspan-update-broker"' in spec and "COLLECT(" in spec and "exclude_binaries=True" in spec
    assert 'BUILD_INFO_HOOK = os.environ.get("ROOFSPAN_BUILD_INFO_HOOK", "")' in spec and '"_roofspan_build_identity"' in spec
    for mod in ("win32serviceutil", "win32service", "servicemanager", "pywintypes", "win32event",
                "updater.autoupdate", "updater.winupdate", "updater.authenticode", "updater.policy", "updater.states"):
        assert f'"{mod}"' in spec, mod


def test_build_exes_fails_before_packaging_when_an_exe_is_missing():
    s = _read(WINBUILD / "build_exes.ps1")
    assert 'if (-not (Test-Path $exe)) { throw "PyInstaller did not produce $exe" }' in s
    assert '$builtExes[$name] = Get-ServiceExeSha256 $exe' in s
    i_loop_end, i_write, i_upgrade = s.index("$builtExes[$name]"), s.index("Write-ServicesBuildManifest"), s.index("if ($UpgradeOutDir)")
    assert i_loop_end < i_write < i_upgrade
    assert s.index("Remove-Item (Get-ServicesBuildManifestPath $OutDir)") < s.index("foreach ($spec in $specs)"), \
        "a manifest from an older build must be removed before building"


def test_build_ps1_verifies_staged_exes_before_wix_and_records_them():
    s = _read(INSTALLER / "build.ps1")
    assert "Assert-ServicesBuildManifest -ServicesDir (Join-Path $StageDir \"services\") -Version $Version -GitSha $gitSha" in s
    assert s.index("Assert-ServicesBuildManifest") < s.index("wix build .\\RoofSpan.wxs")
    assert "service_executables = $servicesManifest.executables" in s


def test_installer_artifact_check_compares_packaged_exe_hashes():
    s = _read(INSTALLER / "Test-InstallerArtifact.ps1")
    assert "$packagedHash = (Get-FileHash $exe.FullName -Algorithm SHA256).Hash.ToLowerInvariant()" in s
    assert "$builtHash = $meta.service_executables.$svcName.sha256" in s
    assert "is not the executable the build produced" in s


def test_wix_packages_the_staged_broker_as_localsystem_demand_start_without_network():
    wxs = _read(INSTALLER / "RoofSpan.wxs")
    comp = re.search(r'<Component Id="Svc_Broker".*?</Component>', wxs, re.DOTALL).group(0)
    assert 'Source="$(var.StageDir)\\services\\roofspan-update-broker\\roofspan-update-broker.exe"' in comp
    assert 'Account="LocalSystem"' in comp and 'Start="demand"' in comp
    assert re.search(r'FirewallException[^>]*Outbound="yes"[^>]*Action="block"', comp)
    perms = re.findall(r'<util:PermissionEx User="(\w+)" Domain="NT SERVICE"([^>]*)/>', comp)
    assert perms == [("RoofSpanUpdateService", ' ServiceStart="yes" ServiceQueryStatus="yes" ')]
    assert '$(var.StageDir)\\services\\roofspan-update-broker\\_internal\\**' in wxs


# ---- fixed configuration of the broker process -------------------------------------------------------------------

def test_broker_entry_uses_fixed_roots_and_no_writable_configuration():
    src = _read(WINBUILD / "update_broker_entry.py")
    assert "os.environ" not in src and "load_runtime_config" not in src and "ROOFSPAN_DATA_ROOT" not in src
    assert "load_trust(INSTALL_ROOT)" in src and "WinUpdateOps(DATA_ROOT, INSTALL_ROOT)" in src
    assert "Broker(ops, policy, build_identity.VERSION, DATA_ROOT, logger, auto)" in src
    win = _read(WINDOWS / "updater" / "winupdate.py")
    assert 'DATA_ROOT = r"C:\\ProgramData\\RoofSpan"' in win and 'INSTALL_ROOT = r"C:\\Program Files\\RoofSpan Office"' in win
    run = win[win.index("def run_installer"):win.index("def delete_staging")]
    assert "assert_fixed_argv(argv, f.path, Paths(self.data_root).broker_log)" in run
    assert "shell=False" in run and "subprocess.run(argv," in run
    take = win[win.index("def take_request"):win.index("def stage")]
    assert "GetSecurityInfo(h," in take and "ReadFile(h," in take, "provenance and bytes must come from one handle"


# ---- real PowerShell behaviour of the provenance gate ------------------------------------------------------------

def _fake_services(root: Path, names, content=b"MZ"):
    hashes = {}
    for n in names:
        d = root / n
        d.mkdir(parents=True, exist_ok=True)
        data = content + n.encode()
        (d / f"{n}.exe").write_bytes(data)
        hashes[n] = hashlib.sha256(data).hexdigest()
    return hashes


class _Run:
    def __init__(self, p):
        plain = re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + " " + p.stderr)
        self.returncode, self.text = p.returncode, " ".join(plain.split())


def _pwsh(script):
    return _Run(subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command",
                                "$PSStyle.OutputRendering='PlainText'; $ErrorActionPreference='Stop'; "
                                f"Import-Module '{MODULE}' -Force; {script}"],
                               capture_output=True, text=True, timeout=60, env={**os.environ, "NO_COLOR": "1"}))


def _ht(hashes):
    return "([ordered]@{" + "; ".join(f"'{k}'='{v}'" for k, v in hashes.items()) + "})"


@needs_pwsh
def test_manifest_written_only_when_every_exe_was_built(tmp_path):
    svc = tmp_path / "services"
    hashes = _fake_services(svc, SERVICE_TARGETS)
    ok = _pwsh(f"Write-ServicesBuildManifest -OutDir '{svc}' -Version 1.2.3 -GitSha abc -BuiltHashes {_ht(hashes)}")
    assert ok.returncode == 0, ok.text
    m = json.loads((svc / SERVICES_BUILD_MANIFEST).read_text(encoding="utf-8-sig"))
    assert m["executables"]["roofspan-update-broker"]["sha256"] == hashes["roofspan-update-broker"]

    (svc / "roofspan-update-broker" / "roofspan-update-broker.exe").unlink()
    r = _pwsh(f"Write-ServicesBuildManifest -OutDir '{svc}' -Version 1.2.3 -GitSha abc -BuiltHashes {_ht(hashes)}")
    assert r.returncode != 0 and "Required service executable missing after build" in r.text

    hashes2 = _fake_services(svc, SERVICE_TARGETS)
    del hashes2["roofspan-update-broker"]  # present on disk but not built in this run
    r = _pwsh(f"Write-ServicesBuildManifest -OutDir '{svc}' -Version 1.2.3 -GitSha abc -BuiltHashes {_ht(hashes2)}")
    assert r.returncode != 0 and "Required service executable missing after build" in r.text


@needs_pwsh
def test_packaging_gate_accepts_only_the_exact_built_executables(tmp_path):
    svc = tmp_path / "services"
    hashes = _fake_services(svc, SERVICE_TARGETS)
    assert _pwsh(f"Write-ServicesBuildManifest -OutDir '{svc}' -Version 1.2.3 -GitSha abc -BuiltHashes {_ht(hashes)}").returncode == 0
    ok = _pwsh(f"$null = Assert-ServicesBuildManifest -ServicesDir '{svc}' -Version 1.2.3 -GitSha abc")
    assert ok.returncode == 0, ok.text

    stale = _pwsh(f"Assert-ServicesBuildManifest -ServicesDir '{svc}' -Version 1.2.3 -GitSha def")
    assert stale.returncode != 0 and "stale" in stale.text

    (svc / "roofspan-update-broker" / "roofspan-update-broker.exe").write_bytes(b"MZ-replaced")
    swapped = _pwsh(f"Assert-ServicesBuildManifest -ServicesDir '{svc}' -Version 1.2.3 -GitSha abc")
    assert swapped.returncode != 0 and "is not the executable built by build_exes.ps1" in swapped.text

    (svc / "roofspan-update-broker" / "roofspan-update-broker.exe").unlink()
    missing = _pwsh(f"Assert-ServicesBuildManifest -ServicesDir '{svc}' -Version 1.2.3 -GitSha abc")
    assert missing.returncode != 0 and "missing" in missing.text


@needs_pwsh
def test_packaging_gate_rejects_manifest_without_broker(tmp_path):
    svc = tmp_path / "services"
    hashes = _fake_services(svc, SERVICE_TARGETS)
    m = {"schema": "roofspan-services-build-v1", "version": "1.2.3", "git_sha": "abc",
         "executables": {k: {"sha256": v} for k, v in hashes.items() if k != "roofspan-update-broker"}}
    (svc / SERVICES_BUILD_MANIFEST).write_text(json.dumps(m), encoding="utf-8")
    r = _pwsh(f"Assert-ServicesBuildManifest -ServicesDir '{svc}' -Version 1.2.3 -GitSha abc")
    assert r.returncode != 0 and "expected [" in r.text


# ---- Win32 prototypes (a missing restype truncates 64-bit HANDLEs: DuplicateHandle -> ERROR_INVALID_HANDLE) ----

class _Fn:
    pass


class _FakeDLL:
    def __init__(self, name, use_last_error=False):
        self.fns = {}

    def __getattr__(self, name):
        return self.__dict__["fns"].setdefault(name, _Fn())


def test_every_win32_call_declares_pointer_sized_prototypes(monkeypatch):
    import ctypes
    from ctypes import wintypes

    from updater import authenticode as A
    monkeypatch.setattr(ctypes, "WinDLL", _FakeDLL, raising=False)
    k32, wt = A._kernel32(), A._wintrust()
    H = wintypes.HANDLE
    expect = {
        "GetFileAttributesW": ([wintypes.LPCWSTR], wintypes.DWORD),
        "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                         wintypes.DWORD, H], H),
        "GetCurrentProcess": ([], H),
        "DuplicateHandle": ([H, H, H, ctypes.POINTER(H), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.BOOL),
        "CloseHandle": ([H], wintypes.BOOL),
    }
    assert set(k32.fns) == set(expect)
    for name, (args, res) in expect.items():
        assert (k32.fns[name].argtypes, k32.fns[name].restype) == (args, res), name
    assert wt.fns["WinVerifyTrust"].restype is wintypes.LONG
    assert wt.fns["WinVerifyTrust"].argtypes[0] is wintypes.HWND
    assert dict(A._FILE_INFO._fields_)["hFile"] is H and dict(A._TRUST_DATA._fields_)["hWVTStateData"] is H
    src = (WINDOWS / "updater" / "authenticode.py").read_text(encoding="utf-8")
    assert 'ctypes.WinDLL("kernel32"' in src and src.count("ctypes.WinDLL(") == 2, "all DLL access goes through the typed loaders"
    assert "f.seek(0)" in src, "the duplicated handle shares the file pointer; hashing must rewind"


def test_broker_staging_acl_is_the_msi_acl_applied_as_a_whole_dacl():
    from updater.winupdate import BROKER_SDDL
    wxs = _read(INSTALLER / "RoofSpan.wxs")
    assert f'<CreateFolder Directory="UpdateBrokerDir"><PermissionEx Sddl="{BROKER_SDDL}" />' in wxs
    win = _read(WINDOWS / "updater" / "winupdate.py")
    assert "PROTECTED_DACL_SECURITY_INFORMATION" in win and "/grant:r" not in win.split("BROKER_SDDL =")[1]
