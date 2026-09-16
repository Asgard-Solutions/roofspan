"""Run the real prerequisite scripts against an existing-install fixture.

Only Windows SCM and the external psql process are substituted. Files, parsing,
branch decisions, exit codes and credential preservation are exercised by PowerShell.
The full Windows CI job also exercises this path with real EDB PostgreSQL and Burn.
"""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "installer" / "scripts"
PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not PWSH, reason="PowerShell required")
PASSWORD = "LegacyTest9%21"
CONFIG = f"DATABASE_URL=postgresql+asyncpg://roofspan:{PASSWORD}@127.0.0.1:5432/roofspan\n"


def run_helper(tmp_path, name, config=CONFIG, query_code=0, version="160004", service=True):
    root = tmp_path / "RoofSpan"
    (root / "config").mkdir(parents=True)
    cfg = root / "config" / "roofspan.env"
    if config is not None:
        cfg.write_text(config, encoding="utf-8")
    # Relocate only the fixed ProgramData root to avoid touching the host install.
    script = tmp_path / name
    script.write_text(SCRIPTS.joinpath(name).read_text().replace(
        "C:\\ProgramData\\RoofSpan", str(root).replace("'", "''")), encoding="utf-8")
    fake = tmp_path / "query.ps1"
    fake.write_text(r'''
$args | ConvertTo-Json -Compress | Set-Content $env:QUERY_ARGS
if ($env:PGPASSWORD -cne 'LegacyTest9!') { $global:LASTEXITCODE = 2; return }
$global:LASTEXITCODE = [int]$env:QUERY_CODE
if ($global:LASTEXITCODE -eq 0) { Write-Output $env:QUERY_VERSION }
''')
    wrapper = tmp_path / "run.ps1"
    wrapper.write_text(r'''
function Get-Service { if ($env:HAS_SERVICE -eq '1') { [pscustomobject]@{ Name='RoofSpanPostgreSQL'; Status='Running' } } }
function Get-CimInstance { if ($env:HAS_SERVICE -eq '1') { [pscustomobject]@{ Name='RoofSpanPostgreSQL'; State='Running'; PathName='"C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe" runservice -N "RoofSpanPostgreSQL" -D "C:\Program Files\PostgreSQL\16\data" -w' } } }
function Get-NetTCPConnection { }
function Join-Path($Path, $ChildPath) {
    if ($ChildPath -eq 'psql.exe') { return $env:QUERY_SCRIPT }
    Microsoft.PowerShell.Management\Join-Path $Path $ChildPath
}
& $env:HELPER_SCRIPT
exit $LASTEXITCODE
''')
    env = dict(os.environ, HELPER_SCRIPT=str(script), QUERY_SCRIPT=str(fake),
               QUERY_ARGS=str(tmp_path / "query-args.json"), QUERY_CODE=str(query_code),
               QUERY_VERSION=version, HAS_SERVICE="1" if service else "0")
    result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(wrapper)],
                            env=env, capture_output=True, text=True, timeout=30)
    # These helpers must never rotate a legacy credential or synthesize a superuser secret.
    assert not (root / "identity" / "pg_super.bin").exists()
    assert not (root / "identity" / "pg_install.optionfile").exists()
    if config is not None:
        assert cfg.read_text(encoding="utf-8") == config
    output = result.stdout + result.stderr
    diag = root / "prereq-diag.log"
    if diag.exists():
        output += diag.read_text()
    assert PASSWORD not in output and "LegacyTest9!" not in output
    return result, output


def test_prep_preserves_existing_service_with_legacy_config(tmp_path):
    result, output = run_helper(tmp_path, "Prepare-PostgreSQL.ps1")
    assert result.returncode == 0, output
    assert "PREP-END-SKIP-LEGACY" in output


def test_verify_authenticates_legacy_application_connection(tmp_path):
    import json
    result, output = run_helper(tmp_path, "Verify-PostgreSQL.ps1")
    assert result.returncode == 0, output
    args = json.loads((tmp_path / "query-args.json").read_text(encoding="utf-8-sig"))
    for flag, value in (("-h", "127.0.0.1"), ("-p", "5432"), ("-U", "roofspan"), ("-d", "roofspan")):
        assert str(args[args.index(flag) + 1]) == value
    assert "-X" in args and "-w" in args
    query = args[args.index("-tAc") + 1]
    assert "public.users LIMIT 0" in query and "public.leads LIMIT 0" in query
    assert "VERIFY-END-OK" in output


@pytest.mark.parametrize("config", [None, "", CONFIG.replace("127.0.0.1", "example.com"),
    CONFIG.replace(":5432/", ":5433/"), CONFIG.replace("/roofspan\n", "/other\n"),
    CONFIG.replace("//roofspan:", "//postgres:"), CONFIG.replace(PASSWORD, "__GENERATED_AT_FIRST_RUN__"),
    CONFIG + CONFIG, CONFIG.replace("/roofspan\n", "/roofspan?host=example.com\n")])
def test_verify_rejects_missing_or_noncanonical_legacy_credentials(tmp_path, config):
    result, output = run_helper(tmp_path, "Verify-PostgreSQL.ps1", config=config)
    assert result.returncode != 0
    assert not (tmp_path / "query-args.json").exists(), output
    assert "VERIFY-STOP" in output


@pytest.mark.parametrize("query_code,version", [(2, "160004"), (0, "120000"), (0, "not-a-version")])
def test_verify_rejects_bad_authentication_or_unsupported_server(tmp_path, query_code, version):
    result, output = run_helper(tmp_path, "Verify-PostgreSQL.ps1", query_code=query_code, version=version)
    assert result.returncode != 0
    assert "VERIFY-STOP" in output


def test_prep_missing_all_credentials_records_actionable_reason(tmp_path):
    result, output = run_helper(tmp_path, "Prepare-PostgreSQL.ps1", config=None)
    assert result.returncode != 0
    diag = (tmp_path / "RoofSpan" / "prereq-diag.log").read_text()
    assert "PREP-STOP" in diag and "credential" in diag.lower(), output


def test_prep_does_not_create_new_database_over_existing_config(tmp_path):
    result, output = run_helper(tmp_path, "Prepare-PostgreSQL.ps1", service=False)
    assert result.returncode != 0, output
    assert "PREP-STOP" in output and "service is missing" in output
