"""Regression checks so Emergent/CI cannot silently break the Windows build scripts again.

Run: pytest windows/tests/test_build_scripts.py   (pure-Python; no Windows required).
A companion GitHub Actions job (.github/workflows/windows-build-scripts.yml) also runs the real
PowerShell parser (pwsh) over every .ps1 on every push/PR.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WIN = REPO / "windows"
INSTALLER = WIN / "installer"
WINBUILD = WIN / "winbuild"

PS1_FILES = sorted(p for p in WIN.rglob("*.ps1") if "node_modules" not in p.parts)


def test_ps1_files_discovered():
    assert PS1_FILES, "no .ps1 build scripts found"


def test_ps1_are_ascii_only():
    """Windows PowerShell 5.1 mis-decodes non-ASCII punctuation (em dash, smart quotes) -> parser errors."""
    offenders = []
    for f in PS1_FILES:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            bad = [(c, hex(ord(c))) for c in line if ord(c) > 127]
            if bad:
                offenders.append(f"{f.relative_to(REPO)}:{i}: {bad}")
    assert not offenders, "non-ASCII characters in .ps1 build scripts:\n" + "\n".join(offenders)


def test_ps1_parse_with_powershell_if_available():
    """Authoritative parse check. Runs the real PowerShell parser when pwsh is present (always in CI);
    skips locally when pwsh is unavailable (CI enforces it via the windows-build-scripts workflow)."""
    import shutil
    import subprocess
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        import pytest
        pytest.skip("pwsh/powershell not available locally; enforced in CI")
    failures = []
    for f in PS1_FILES:
        script = (
            "$t=$null;$e=$null;"
            f"[System.Management.Automation.Language.Parser]::ParseFile('{f}',[ref]$t,[ref]$e)|Out-Null;"
            "if($e){$e|ForEach-Object{Write-Output $_.Message};exit 1}"
        )
        r = subprocess.run([pwsh, "-NoProfile", "-Command", script], capture_output=True, text=True)
        if r.returncode != 0:
            failures.append(f"{f.relative_to(REPO)}: {r.stdout} {r.stderr}")
    assert not failures, "PowerShell parse errors:\n" + "\n".join(failures)


def test_spec_datas_reference_real_backend_alembic():
    """PyInstaller spec must package the REAL backend/alembic (not the removed backend/migrations)."""
    spec = (WINBUILD / "roofspan-backend.spec").read_text(encoding="utf-8")
    assert '"alembic"), "alembic"' in spec, "spec must package backend/alembic"
    # Must NOT package the removed backend/migrations DIRECTORY. The migrations_runner MODULE
    # (packaged as a hiddenimport) is legitimate and intentionally allowed.
    assert 'BACKEND, "migrations")' not in spec, "spec must NOT reference the removed backend/migrations dir"
    assert (REPO / "backend" / "alembic").is_dir(), "backend/alembic dir must exist"
    assert (REPO / "backend" / "alembic.ini").is_file(), "backend/alembic.ini must exist"


def test_build_exes_uses_repo_venv_without_activation():
    txt = (WINBUILD / "build_exes.ps1").read_text(encoding="utf-8")
    assert ".venv\\Scripts\\pyinstaller.exe" in txt, "build_exes must prefer repo-local .venv PyInstaller"
    assert "Get-Command pyinstaller" in txt, "build_exes must fall back to PATH pyinstaller"
    # Fail-fast on the backend assets the spec packages.
    assert 'alembic.ini' in txt and 'alembic' in txt


def test_stage_always_syncs_yarn():
    txt = (INSTALLER / "stage.ps1").read_text(encoding="utf-8")
    assert "yarn install --frozen-lockfile" in txt
    # Must NOT gate the install solely on node_modules existing.
    assert 'Test-Path ".\\node_modules"' not in txt, "stage must not skip yarn install when node_modules exists"
    assert "yarn.lock" in txt and "package.json" in txt, "stage must fail-fast on missing frontend lockfiles"


def test_stage_normalizes_paths_before_directory_changes():
    """Regression: a relative -StageDir must be resolved to ABSOLUTE before any Push-Location, so staged
    output cannot escape to a stray parent-directory _stage (D:\\AsgardSolutions\\_stage)."""
    lines = (INSTALLER / "stage.ps1").read_text(encoding="utf-8").splitlines()
    txt = "\n".join(lines)

    def lineno(substr, code_only=False):
        for i, l in enumerate(lines):
            s = l.strip()
            if code_only and s.startswith("#"):
                continue
            if code_only:
                if s.startswith(substr):
                    return i
            elif substr in l:
                return i
        return 10**9

    assert "IsPathRooted" in txt and "GetFullPath" in txt, "stage.ps1 must normalize paths to absolute"
    assert "$stageRoot" in txt, "stage.ps1 must use an absolute $stageRoot"
    push = lineno("Push-Location", code_only=True)
    assert lineno("$stageRoot = ", code_only=True) < push, "stageRoot must be resolved before Push-Location"
    assert lineno("$feDirResolved = ", code_only=True) < push, "FrontendDir must be resolved before Push-Location"
    # Destinations derive from the absolute root, NOT the raw relative $StageDir.
    assert 'Join-Path $StageDir' not in txt, "must not build stage paths from the raw relative $StageDir"
    assert "$services = Join-Path $stageRoot" in txt
    assert "$frontend = Join-Path $stageRoot" in txt
    assert 'Copy-Item ".\\build\\*" $frontend' in txt, "frontend copy must target the absolute $frontend"
    # Completeness must be validated BEFORE the success message, which prints the resolved absolute root.
    assert 'Write-Host "==> Stage assembled at $stageRoot"' in txt
    assert lineno("Stage incomplete") < lineno("Stage assembled at $stageRoot"), \
        "stage must validate the complete payload before printing success"




def test_stage_validates_full_payload_before_success():
    txt = (INSTALLER / "stage.ps1").read_text(encoding="utf-8")
    for needed in ("roofspan-backend.exe", "roofspan-relay-connector.exe",
                   "roofspan-update-service.exe", "index.html"):
        assert needed in txt, f"stage completeness check must assert {needed}"

    txt = (INSTALLER / "build.ps1").read_text(encoding="utf-8")
    for param in ("$Version", "$StageDir", "$PostgresInstaller", "$WebView2Bootstrapper"):
        assert param in txt, f"build.ps1 must accept {param}"
    # Prerequisites are validated (fail-fast) before the expensive wix build.
    assert "WebView2 bootstrapper not found" in txt
    assert "PostgreSQL prerequisite installer not found" in txt
    assert "Staging incomplete" in txt


def test_bundle_prereqs_match_build_params():
    """Every prerequisite the bundle expects must be passed by build.ps1, and vice-versa."""
    bundle = (INSTALLER / "bundle.wxs").read_text(encoding="utf-8")
    build = (INSTALLER / "build.ps1").read_text(encoding="utf-8")
    for var in ("PostgresInstaller", "WebView2Bootstrapper"):
        assert f'Name="{var}"' in bundle, f"bundle.wxs must declare Variable {var}"
        assert f'-d "{var}=' in build, f"build.ps1 must pass -d {var}= to the bundle"
    # WebView2 must be detected (skip if present) and installed before the Office MSI.
    assert "WebView2Present" in bundle and "WebView2Runtime" in bundle
    assert bundle.index("WebView2Runtime") < bundle.index("RoofSpanOfficeMsi")


def test_build_uses_renamed_wix5_bootstrapper_extension():
    """WiX 5 renamed WixToolset.Bal.wixext -> WixToolset.BootstrapperApplications.wixext for CLI builds.
    The old 'Bal' CLI package installs as 'damaged'; it must never be used on the command line again."""
    build = (INSTALLER / "build.ps1").read_text(encoding="utf-8")
    assert "-ext WixToolset.Bal.wixext" not in build, \
        "build.ps1 must NOT use the deprecated WixToolset.Bal.wixext CLI extension"
    assert "-ext WixToolset.BootstrapperApplications.wixext" in build, \
        "build.ps1 must use the renamed WixToolset.BootstrapperApplications.wixext CLI extension"


def test_every_wix_ext_flag_is_restored_by_bootstrap():
    """Determinism: every '-ext <Name>' the build passes to `wix build` must also be covered by the
    extension-restore block, so a fresh host builds without manual `wix extension add`, and no new -ext
    can be added without wiring its restore."""
    build = (INSTALLER / "build.ps1").read_text(encoding="utf-8")

    # Extensions restored via `wix extension add -g <Name>/<Version>` (declared in $RequiredWixExtensions).
    required_block = build[build.index("$RequiredWixExtensions"):build.index("$installedExtensions")]
    restored = set(re.findall(r'"(WixToolset\.[A-Za-z0-9.]+\.wixext)"', required_block))

    # Extensions actually consumed by the two `wix build` invocations.
    used = set(re.findall(r'-ext\s+(WixToolset\.[A-Za-z0-9.]+\.wixext)', build))

    assert used, "no '-ext' flags found in build.ps1"
    missing = used - restored
    assert not missing, f"these -ext extensions are not restored by the bootstrap block: {sorted(missing)}"

    # The exact WiX 5.0.2 extension set the build pipeline depends on.
    assert restored == {
        "WixToolset.BootstrapperApplications.wixext",
        "WixToolset.Util.wixext",
        "WixToolset.Firewall.wixext",
    }, f"unexpected restore set: {sorted(restored)}"
    # Pinned to match the WiX tool version.
    assert '$WixExtVersion = "5.0.2"' in build, "WiX extensions must be pinned to 5.0.2"
    assert "wix extension add -g" in build, "restore must use the global CLI extension cache"


ONEDIR_SERVICE_PATHS = [
    r"roofspan-backend\roofspan-backend.exe",
    r"roofspan-relay-connector\roofspan-relay-connector.exe",
    r"roofspan-update-service\roofspan-update-service.exe",
]


def test_build_stage_and_wxs_agree_on_onedir_service_paths():
    """build.ps1 validation, stage.ps1 validation, and RoofSpan.wxs must all reference the SAME
    PyInstaller ONEDIR service layout (services\\<name>\\<name>.exe) - never the obsolete ONEFILE paths.
    (stage.ps1 builds the 'services' segment via a variable, so we match the ONEDIR-distinguishing
    per-service subfolder+exe token that must appear identically in all three.)"""
    build = (INSTALLER / "build.ps1").read_text(encoding="utf-8")
    stage = (INSTALLER / "stage.ps1").read_text(encoding="utf-8")
    wxs = (INSTALLER / "RoofSpan.wxs").read_text(encoding="utf-8")

    for onedir in ONEDIR_SERVICE_PATHS:
        assert onedir in build, f"build.ps1 must validate ONEDIR path ...\\{onedir}"
        assert onedir in stage, f"stage.ps1 must validate ONEDIR path ...\\{onedir}"
        assert onedir in wxs, f"RoofSpan.wxs must reference ONEDIR path ...\\{onedir}"

    # build.ps1 and RoofSpan.wxs use the full 'services\<name>\<name>.exe' form.
    for onedir in ONEDIR_SERVICE_PATHS:
        assert f"services\\{onedir}" in build
        assert f"services\\{onedir}" in wxs

    # The obsolete ONEFILE paths (services\<name>.exe with no per-service subfolder) must be gone.
    for name in ("roofspan-backend", "roofspan-relay-connector", "roofspan-update-service"):
        onefile = f"services\\{name}.exe"
        for label, text in (("build.ps1", build), ("RoofSpan.wxs", wxs)):
            assert onefile not in text, f"{label} still references obsolete ONEFILE path {onefile}"
