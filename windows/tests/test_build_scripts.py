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
    assert "migrations" not in spec, "spec must NOT reference backend/migrations"
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
