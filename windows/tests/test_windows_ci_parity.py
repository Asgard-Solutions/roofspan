"""Static safeguards for local Office build vs GitHub CI parity and fail-closed checks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = (ROOT / ".github/workflows/windows-build-scripts.yml").read_text(encoding="utf-8")
MATRIX = (ROOT / ".github/workflows/windows-installer-matrix.yml").read_text(encoding="utf-8")
STAGE = (ROOT / "windows/installer/stage.ps1").read_text(encoding="utf-8")
VERIFY = (ROOT / "windows/installer/Test-InstallerArtifact.ps1").read_text(encoding="utf-8")
EDB = (ROOT / "windows/installer/Get-CIPostgreSQLInstaller.ps1").read_text(encoding="utf-8")
REFERENCE = json.loads((ROOT / "windows/installer/local-prerequisites-reference.json").read_text(encoding="utf-8"))


def test_ci_uses_one_pinned_edb_downloader_for_all_office_builds():
    assert BUILD.count("Get-CIPostgreSQLInstaller.ps1") == 2
    assert MATRIX.count("Get-CIPostgreSQLInstaller.ps1") == 1
    for workflow in (BUILD, MATRIX):
        assert "ROOFSPAN_CI_EDB_URL" in workflow
        assert "ROOFSPAN_CI_EDB_SHA256" in workflow
        assert "Invoke-WebRequest \"https://get.enterprisedb.com" not in workflow
    assert "6d3919bc23cfb45e79c6e391de8b689c32101f2c1b73377aa26e4ce593c0ef28" in EDB
    assert "Configure BOTH ROOFSPAN_CI_EDB_URL and ROOFSPAN_CI_EDB_SHA256" in EDB
    assert "Get-FileHash" in EDB and "Get-AuthenticodeSignature" in EDB
    assert "get.enterprisedb.com" in EDB and "$uri.Scheme -ne 'https'" in EDB


def test_yarn_stage_retries_only_transient_network_errors():
    assert "yarn.cmd install --frozen-lockfile" in STAGE
    assert "& $env:ComSpec /d /s /c 'yarn.cmd install" in STAGE
    assert "& $env:ComSpec /d /s /c 'yarn.cmd build 2>&1'" in STAGE
    assert "Tee-Object -FilePath $yarnLog" in STAGE
    assert "--network-timeout 180000" in STAGE
    assert "for ($attempt = 1; $attempt -le 3; $attempt++)" in STAGE
    assert "if (-not $transient -or $attempt -eq 3)" in STAGE
    assert 'throw "yarn install failed' in STAGE


def test_wix_extract_retry_preserves_strict_hash_verification():
    assert "for ($attempt = 1; $attempt -le 2; $attempt++)" in VERIFY
    assert "$extractRc -ne -2147024664" in VERIFY
    assert "$extractRc -ne -2147024664" in BUILD
    assert "burn manifest extraction failed (wix exit $extractRc)" in BUILD
    assert 'Assert-That $extractOk "wix burn extract failed' in VERIFY
    assert 'Assert-That ($embedded.ContainsKey($msiSha))' in VERIFY
    assert 'Assert-That ($embedded.ContainsKey($p.sha256))' in VERIFY


def test_transactional_upgrade_build_respects_version_file_contract():
    assert "CI-only version bump did not persist before staging N" in BUILD
    assert "Staging N unexpectedly changed windows/VERSION" in BUILD
    assert ".\\build.ps1 -Version $next" in BUILD


def test_local_prerequisite_reference_is_unambiguous():
    pg = REFERENCE["postgresql"]
    standalone = REFERENCE["webview2_standalone"]
    bootstrapper = REFERENCE["webview2_bootstrapper"]
    assert pg["sha256"] in EDB
    assert pg["filename"] in EDB
    assert standalone["size_bytes"] > 100 * 1024 * 1024
    assert len(standalone["sha256"]) == 64
    assert not bootstrapper["use_in_offline_bundle"]
    assert bootstrapper["size_bytes"] < 10 * 1024 * 1024
