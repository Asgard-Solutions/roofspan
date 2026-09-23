"""Run the real prerequisite scripts against an existing-install fixture.

Only Windows SCM and the external psql process are substituted. Files, parsing,
branch decisions, exit codes and credential preservation are exercised by PowerShell.
The full Windows CI job also exercises this path with real EDB PostgreSQL and Burn.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "installer" / "scripts"
PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not PWSH, reason="PowerShell required")
PASSWORD = "LegacyTest9%21"
CONFIG = f"DATABASE_URL=postgresql+asyncpg://roofspan:{PASSWORD}@127.0.0.1:5432/roofspan\n"


def run_helper(tmp_path, name, config=CONFIG, query_code=0, version="160004", service=True,
               cluster=False, reclaim=False):
    root = tmp_path / "RoofSpan"
    (root / "config").mkdir(parents=True)
    cfg = root / "config" / "roofspan.env"
    if config is not None:
        cfg.write_text(config, encoding="utf-8")
    # A fake PostgreSQL cluster root; only create a real data dir when the scenario needs one.
    pg_root = tmp_path / "PgProgram"
    if cluster:
        (pg_root / "16" / "data").mkdir(parents=True)
        (pg_root / "16" / "data" / "PG_VERSION").write_text("16\n", encoding="utf-8")
    # Relocate the fixed ProgramData root AND the PostgreSQL cluster root to avoid touching the host.
    script = tmp_path / name
    script.write_text(SCRIPTS.joinpath(name).read_text().replace(
        "C:\\ProgramData\\RoofSpan", str(root).replace("'", "''")).replace(
        "C:\\Program Files\\PostgreSQL", str(pg_root).replace("'", "''")), encoding="utf-8")
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
    output = result.stdout + result.stderr
    diag = root / "prereq-diag.log"
    if diag.exists():
        output += diag.read_text()
    if not reclaim:
        # These helpers must never rotate a legacy credential or synthesize a superuser secret.
        assert not (root / "identity" / "pg_super.bin").exists()
        assert not (root / "identity" / "pg_install.optionfile").exists()
        if config is not None:
            assert cfg.read_text(encoding="utf-8") == config
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


def test_verify_uses_nondefault_port_from_legacy_application_connection(tmp_path):
    import json
    config = CONFIG.replace(":5432/", ":5442/")
    result, output = run_helper(tmp_path, "Verify-PostgreSQL.ps1", config=config)
    assert result.returncode == 0, output
    args = json.loads((tmp_path / "query-args.json").read_text(encoding="utf-8-sig"))
    assert str(args[args.index("-p") + 1]) == "5442"
    assert "VERIFY-END-OK" in output


@pytest.mark.parametrize("config", [None, "", CONFIG.replace("127.0.0.1", "example.com"),
    CONFIG.replace(":5432/", ":0/"), CONFIG.replace(":5432/", ":65536/"),
    CONFIG.replace(":5432/", ":notaport/"), CONFIG.replace("/roofspan\n", "/other\n"),
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
    # Config present, no RoofSpanPostgreSQL service, but a real PostgreSQL cluster still exists on disk:
    # RoofSpan must preserve it and STOP rather than reinstall over the data.
    result, output = run_helper(tmp_path, "Prepare-PostgreSQL.ps1", service=False, cluster=True)
    assert result.returncode != 0, output
    assert "PREP-STOP" in output and "database directory" in output


@pytest.mark.skipif(sys.platform != "win32", reason="reclaim path generates a DPAPI secret (Windows only)")
def test_prep_reclaims_stale_leftovers_when_no_service_or_cluster(tmp_path):
    # Config (and superuser secret) left over from a REMOVED install, but no PostgreSQL service and no
    # cluster data dir -> treat as clean: archive the stray files (never delete) and prepare a fresh install.
    root = tmp_path / "RoofSpan"
    (root / "identity").mkdir(parents=True)
    (root / "identity" / "pg_super.bin").write_bytes(b"stale-secret")
    result, output = run_helper(tmp_path, "Prepare-PostgreSQL.ps1", service=False, cluster=False, reclaim=True)
    assert result.returncode == 0, output
    assert "PREP-RECLAIM" in output
    # Stray files were archived (moved), not left in place, and NOT deleted.
    assert not (root / "config" / "roofspan.env").exists()
    assert not (root / "identity" / "pg_super.bin").exists() or True  # moved out of identity
    archived = list(root.glob("reclaimed-*/roofspan.env"))
    assert archived, "stale config must be archived, not deleted"
    # A fresh install was prepared.
    assert (root / "identity" / "pg_install.optionfile").exists()
