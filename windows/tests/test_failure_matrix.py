"""Failure-matrix controller, harness and workflow contract (runs on Linux; Windows behavior runs in CI)."""
import base64
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
MATRIX = HERE / "matrix"
sys.path.insert(0, str(MATRIX))
import matrix as M  # noqa: E402

REPO = HERE.parents[1]
WORKFLOW = REPO / ".github/workflows/windows-installer-matrix.yml"
SCENARIO_PS1 = (MATRIX / "Invoke-MatrixScenario.ps1").read_text(encoding="utf-8")
LIB_PSM1 = (MATRIX / "MatrixLib.psm1").read_text(encoding="utf-8")
PWSH = shutil.which("pwsh")
ACK = M.ACK

REQUIRED = {
    "clean-install-no-postgres", "clean-install-offline", "upgrade-n1-to-n", "upgrade-n2-to-n", "same-version-reinstall",
    "repair-from-arp", "legacy-pg-5442-no-pgsuper", "managed-pg-with-pgsuper", "pg-service-stopped",
    "port-5432-unrelated-process", "unrelated-postgres-service", "stale-config-no-cluster", "stale-config-real-cluster",
    "pg-non-default-location", "corrupt-saved-credential", "insufficient-backup-disk", "pg-dump-failure",
    "backup-verification-failure", "installer-failure-after-backup", "migration-failure-before-revision",
    "migration-failure-partial", "backend-startup-failure", "health-check-failure", "database-restore-failure",
    "interrupted-upgrade-retry", "pending-reboot", "silent-install", "uac-different-admin", "low-resource-large-db",
    "uninstall-reinstall-retained-data", "webview2-absent-offline",
}
OUTCOME_HELPERS = {"Assert-UpgradeSuccess": {"success", "success_after_retry"}, "Assert-UpgradeSafeStop": {"safe_stop"},
                   "Assert-UpgradeRollback": {"rollback"}}
BASELINES = {f"ROOFSPAN_BASELINE_{k}_{f}": v for k in ("N1", "N2") for f, v in
             (("URL", "https://example.invalid/RoofSpanSetup.exe"), ("SHA256", "a" * 64), ("VERSION", "1.2.3"))}


def _blocks() -> dict:
    parts = re.split(r"\n    '([a-z0-9-]+)' = \{", SCENARIO_PS1.split("$Scenarios = @{", 1)[1].split("\n# -- run", 1)[0])
    return dict(zip(parts[1::2], parts[2::2]))


# -- catalog <-> implementation -------------------------------------------------------------------------------
def test_catalog_covers_every_required_scenario_exactly():
    assert set(M.SCENARIOS) == REQUIRED
    assert len(M.CATALOG["scenarios"]) == len(REQUIRED)


def test_only_environment_bound_scenarios_need_a_vm():
    assert {s for s, v in M.SCENARIOS.items() if v["runner"] == "vm"} == {
        "uac-different-admin", "low-resource-large-db", "webview2-absent-offline"}


def test_every_scenario_has_an_implementation_that_records_its_expected_outcome():
    blocks = _blocks()
    assert set(blocks) == REQUIRED
    for sid, body in blocks.items():
        expect = M.SCENARIOS[sid]["expect"]
        direct = f"'outcome:{expect}'" in body
        via = any(h in body and expect in outs for h, outs in OUTCOME_HELPERS.items())
        if sid == "interrupted-upgrade-retry":
            via = "'success_after_retry'" in body and "Assert-UpgradeSuccess" in body
        assert direct or via, f"{sid} never records outcome:{expect}"


def test_helpers_record_the_outcomes_they_claim():
    assert "Write-Assertion \"outcome:$Outcome\"" in SCENARIO_PS1
    assert "Write-Assertion 'outcome:safe_stop'" in SCENARIO_PS1
    assert "Write-Assertion 'outcome:rollback'" in SCENARIO_PS1


def test_failure_scenarios_arm_faults_externally_on_the_production_artifact():
    blocks = _blocks()
    assert "ROOFSPAN_UPGRADE_FAULT" not in SCENARIO_PS1 + LIB_PSM1
    assert "Mount-TinyVolume" in blocks["insufficient-backup-disk"]
    assert "pg_dump.exe" in blocks["pg-dump-failure"]
    assert "pg_restore.exe" in blocks["backup-verification-failure"]
    assert "Wait-CoordinatorState @('INSTALLING')" in blocks["migration-failure-before-revision"]
    assert "Enable-MigrationFault 'first'" in blocks["migration-failure-before-revision"]
    assert "Enable-MigrationFault 'final-head'" in blocks["migration-failure-partial"]
    assert "Start-PortHolder 8001" in blocks["backend-startup-failure"]
    assert "Watch-RelayDuringHealth" in blocks["health-check-failure"]
    assert "Add-DenyAce $restoreExe" in blocks["database-restore-failure"]
    assert "Stop-Process -Force" in blocks["interrupted-upgrade-retry"]


def test_pre_mutation_failures_assert_no_install_and_post_mutation_failures_assert_restore():
    for sid in ("insufficient-backup-disk", "pg-dump-failure", "backup-verification-failure"):
        assert "Assert-UpgradeSafeStop" in _blocks()[sid]
    for sid in ("installer-failure-after-backup", "migration-failure-before-revision", "migration-failure-partial",
                "backend-startup-failure", "health-check-failure"):
        assert "Assert-UpgradeRollback" in _blocks()[sid]
    safe = SCENARIO_PS1.split("function Assert-UpgradeSafeStop", 1)[1].split("\nfunction ", 1)[0]
    assert "-notcontains 'INSTALLING'" in safe and "install-new.log" in safe
    rb = SCENARIO_PS1.split("function Assert-UpgradeRollback", 1)[1].split("\nfunction ", 1)[0]
    for needle in ("'RESTORING'", "'INSTALLING'", "Assert-PreviousRestored", "roofspan_failed_", "rs_matrix_fault"):
        assert needle in rb


def test_rollback_compares_config_and_identity_hashes_and_sentinels():
    for key in ("config_sha256", "identity_sha256", "sentinel", "revisions", "office_msi_version"):
        assert f"'{key}'" in SCENARIO_PS1.split("$PreChange = @(", 1)[1].split(")", 1)[0]


# -- no vacuous assertions / arbitrary sleeps -----------------------------------------------------------------
@pytest.mark.parametrize("path", sorted(MATRIX.glob("*.ps*1")) + [WORKFLOW], ids=lambda p: p.name)
def test_no_unconditional_pass_patterns(path):
    text = path.read_text(encoding="utf-8")
    for bad in (r"-or\s+\$true\b", r"\|\|\s*true\b", r"\bor True\b", r"Assert-True\s+'[^']*'\s+\$true\b",
                r"continue-on-error:\s*true(?![\s\S]{0,80}matrix-build-info)"):
        assert not re.search(bad, text), f"{path.name}: {bad}"


@pytest.mark.parametrize("path", sorted(MATRIX.glob("*.ps*1")), ids=lambda p: p.name)
def test_condition_based_polling_only(path):
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"Start-Sleep\s+(-Seconds\s+)?\d", text), "use Wait-Until instead of fixed sleeps"
    for m in re.finditer(r"Start-Sleep -Milliseconds (\d+)", text):
        assert int(m.group(1)) <= 2000


def test_matrix_sources_are_ascii():
    for p in list(MATRIX.glob("*")) + [WORKFLOW]:
        if p.is_file() and p.suffix in (".ps1", ".psm1", ".py", ".json", ".yml"):
            p.read_bytes().decode("ascii")


# -- plan -------------------------------------------------------------------------------------------------------
def _disp(doc):
    return {s["id"]: s["disposition"] for s in doc["scenarios"]}


def test_plan_without_baselines_or_vm():
    d = _disp(M.plan({}))
    for sid, s in M.SCENARIOS.items():
        if s["runner"] == "vm":
            assert d[sid] == "PENDING_VM"
        elif s.get("baseline"):
            assert d[sid] == "BLOCKED_MISSING_BASELINE"
        else:
            assert d[sid] == "RUN_HOSTED"


def test_plan_with_everything_runs_everything():
    d = _disp(M.plan({**BASELINES, "ROOFSPAN_DISPOSABLE_VM_ENABLED": "true"}))
    assert all(v in ("RUN_HOSTED", "RUN_VM") for v in d.values())
    assert d["webview2-absent-offline"] == "RUN_VM"


def test_plan_n1_only_blocks_only_n2():
    env = {k: v for k, v in BASELINES.items() if "_N1_" in k}
    d = _disp(M.plan(env))
    assert d["upgrade-n2-to-n"] == "BLOCKED_MISSING_BASELINE"
    assert d["upgrade-n1-to-n"] == d["migration-failure-partial"] == "RUN_HOSTED"
    assert d["low-resource-large-db"] == "PENDING_VM"


@pytest.mark.parametrize("env", [
    {"ROOFSPAN_BASELINE_N1_URL": "https://x/y.exe"},
    {**BASELINES, "ROOFSPAN_BASELINE_N1_SHA256": "nothex"},
    {**BASELINES, "ROOFSPAN_BASELINE_N1_URL": "http://insecure/y.exe"},
    {**BASELINES, "ROOFSPAN_BASELINE_N2_VERSION": "latest"},
])
def test_plan_rejects_misconfigured_baselines(env):
    with pytest.raises(ValueError):
        M.plan(env)


def test_plan_release_flag_and_reasons():
    doc = M.plan({"ROOFSPAN_RELEASE_BUILD": "true"})
    assert doc["release"] is True
    for s in doc["scenarios"]:
        assert (s["disposition"].startswith("RUN")) == (s["reason"] == "")


# -- guard ------------------------------------------------------------------------------------------------------
HOSTED = {"ROOFSPAN_MATRIX_DESTRUCTIVE": ACK, "RUNNER_OS": "Windows", "GITHUB_ACTIONS": "true",
          "RUNNER_ENVIRONMENT": "github-hosted"}


def test_guard_accepts_github_hosted_windows(tmp_path):
    assert M.guard(HOSTED, str(tmp_path / "none.json")) == "github-hosted"


@pytest.mark.parametrize("override", [{"ROOFSPAN_MATRIX_DESTRUCTIVE": ""}, {"ROOFSPAN_MATRIX_DESTRUCTIVE": "yes"},
                                      {"RUNNER_OS": "Linux"}, {"RUNNER_ENVIRONMENT": "self-hosted"},
                                      {"GITHUB_ACTIONS": ""}])
def test_guard_refuses_everything_else_without_a_marker(tmp_path, override):
    with pytest.raises(M.GuardRefused):
        M.guard({**HOSTED, **override}, str(tmp_path / "none.json"), machine_guid=lambda: "g1")


def _vm(tmp_path, guid="g1", **marker):
    m = tmp_path / "approved.json"
    m.write_text(json.dumps({"purpose": "roofspan-installer-matrix", "disposable": True, "machine_guid": guid, **marker}))
    env = {**HOSTED, "RUNNER_ENVIRONMENT": "self-hosted", "GITHUB_RUN_ID": "77", "ROOFSPAN_MATRIX_SCENARIO": "s1"}
    return env, str(m)


def test_guard_accepts_an_approved_single_use_vm_and_is_reentrant_for_the_same_job(tmp_path):
    env, marker = _vm(tmp_path)
    assert M.guard(env, marker, machine_guid=lambda: "g1") == "approved-vm"
    assert M.guard(env, marker, machine_guid=lambda: "g1") == "approved-vm"


def test_guard_refuses_a_vm_that_was_not_reverted(tmp_path):
    env, marker = _vm(tmp_path)
    M.guard(env, marker, machine_guid=lambda: "g1")
    with pytest.raises(M.GuardRefused, match="already used"):
        M.guard({**env, "ROOFSPAN_MATRIX_SCENARIO": "s2"}, marker, machine_guid=lambda: "g1")


@pytest.mark.parametrize("marker", [{"disposable": False}, {"purpose": "other"}, {"machine_guid": ""}])
def test_guard_refuses_bad_markers(tmp_path, marker):
    env, path = _vm(tmp_path, **marker)
    with pytest.raises(M.GuardRefused):
        M.guard(env, path, machine_guid=lambda: "g1")


def test_guard_refuses_a_marker_for_another_machine(tmp_path):
    env, path = _vm(tmp_path, guid="other")
    with pytest.raises(M.GuardRefused, match="different machine"):
        M.guard(env, path, machine_guid=lambda: "g1")


def test_guard_cli_refuses_here_with_exit_3(tmp_path):
    p = subprocess.run([sys.executable, str(MATRIX / "matrix.py"), "guard", "--marker", str(tmp_path / "x")],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert p.returncode == 3 and "GUARD-REFUSED" in p.stderr


# -- finalize + classification -------------------------------------------------------------------------------------
def _ev(tmp_path, asserts):
    (tmp_path / "assertions.jsonl").write_text("\n".join(json.dumps(a) for a in asserts))
    return tmp_path


OK3 = [{"name": "a", "ok": True}, {"name": "b", "ok": True}, {"name": "outcome:success", "ok": True}]


def test_finalize_pass(tmp_path):
    r = M.finalize("silent-install", _ev(tmp_path, OK3), "PASS", "", "", {"artifact_sha256": "x"})
    assert r["status"] == "PASS" and json.loads((tmp_path / "result.json").read_text())["artifact_sha256"] == "x"


@pytest.mark.parametrize("asserts,why", [
    (OK3 + [{"name": "c", "ok": False}], "assertion failed"),
    (OK3[:1] + OK3[2:], "only 2 assertions"),
    ([{"name": n, "ok": True} for n in "abcd"], "never recorded"),
])
def test_finalize_never_passes_vacuously(tmp_path, asserts, why):
    r = M.finalize("silent-install", _ev(tmp_path, asserts), "PASS", "", "", {})
    assert r["status"] == "FAIL" and why in r["reason"]


def test_finalize_wrong_outcome_name_fails(tmp_path):
    r = M.finalize("port-5432-unrelated-process", _ev(tmp_path, OK3), "PASS", "", "", {})
    assert r["status"] == "FAIL"


def test_skip_needs_an_exact_environmental_reason(tmp_path):
    assert M.finalize("silent-install", _ev(tmp_path, []), "SKIP", "", "flaky", {})["status"] == "FAIL"
    r = M.finalize("silent-install", _ev(tmp_path, []), "SKIP", "", "ENV: runner image has no D: volume", {})
    assert r["status"] == "SKIP"


def test_classification_from_coordinator_state(tmp_path):
    hist = lambda *s: {"history": [{"state": x} for x in s]}  # noqa: E731
    (tmp_path / "state-upgrade.json").write_text(json.dumps({"state": "ROLLED_BACK", **hist(
        "PREFLIGHT", "BACKING_UP", "BACKUP_VERIFIED", "SERVICES_STOPPED", "INSTALLING", "MIGRATING", "RESTORING", "ROLLED_BACK")}))
    assert M.classify(tmp_path) == "migration"
    (tmp_path / "state-upgrade.json").write_text(json.dumps({"state": "FAILED", **hist("INSTALLING", "RESTORING", "FAILED")}))
    assert M.classify(tmp_path) == "recovery"
    (tmp_path / "state-upgrade.json").write_text(json.dumps({"state": "ROLLED_BACK", **hist("PREFLIGHT", "ROLLED_BACK")}))
    assert M.classify(tmp_path) == "backup"


def test_classification_from_burn_log(tmp_path):
    (tmp_path / "burn-x.log").write_text("Applied execute package: WebView2Runtime, result: 0x0\n"
                                         "Applied execute package: PostgreSQLPasswordPrep, result: 0x80070001\n")
    assert M.classify(tmp_path) == "prerequisite"
    (tmp_path / "burn-x.log").write_text("Applied execute package: RoofSpanOfficeMsi, result: 0x80070643\n")
    assert M.classify(tmp_path) == "msi"
    (tmp_path / "burn-x.log").write_text("Error 0x80070002: Failed to detect bundle\n")
    assert M.classify(tmp_path) == "burn-detection"
    r = M.finalize("silent-install", _ev(tmp_path, []), "FAIL", "", "x", {})
    assert r["layer"] == "burn-detection"


# -- scrub ----------------------------------------------------------------------------------------------------------
def test_scrub_removes_and_reports_secret_material(tmp_path):
    secret = "S3cr3t-Value-42"
    (tmp_path / "ok.log").write_text("all good postgresql+asyncpg://roofspan:***@127.0.0.1:5432/roofspan")
    (tmp_path / "leak8.log").write_text(f"pw={secret}")
    (tmp_path / "leak16.log").write_bytes(f"x{secret}x".encode("utf-16-le"))
    (tmp_path / "url.log").write_text("postgresql://roofspan:hunter22@127.0.0.1/roofspan")
    for forbidden in ("pg_super.bin", "roofspan.env", "roofspan.dump", "pgpass.conf"):
        (tmp_path / forbidden).write_text("x")
    hits = {h["file"] for h in M.scrub(tmp_path, [secret])}
    assert hits == {"leak8.log", "leak16.log", "url.log", "pg_super.bin", "roofspan.env", "roofspan.dump", "pgpass.conf"}
    assert (tmp_path / "ok.log").exists() and not (tmp_path / "leak8.log").exists()
    report = (tmp_path / "scrub-report.json").read_text()
    assert secret not in report


def test_scrub_cli_reads_secrets_from_env_and_fails(tmp_path):
    (tmp_path / "a.log").write_text("token=abcdefgh123")
    env = {"PATH": "/usr/bin:/bin",
           "ROOFSPAN_MATRIX_SECRETS_B64": base64.b64encode(json.dumps(["abcdefgh123"]).encode()).decode()}
    p = subprocess.run([sys.executable, str(MATRIX / "matrix.py"), "scrub", "--evidence", str(tmp_path)], env=env)
    assert p.returncode == 1 and not (tmp_path / "a.log").exists()


# -- summary ----------------------------------------------------------------------------------------------------------
def _results(tmp_path, statuses):
    for sid, st in statuses.items():
        d = tmp_path / sid
        d.mkdir()
        (d / "result.json").write_text(json.dumps({"scenario": sid, "status": st, "layer": "", "reason": "",
                                                   "assertions_total": 5}))
    return tmp_path


def test_summary_passes_non_release_with_pending_and_blocked(tmp_path):
    doc = M.plan({})
    run = {s["id"]: "PASS" for s in doc["scenarios"] if s["disposition"] == "RUN_HOSTED"}
    out, md, code = M.summarize(doc, _results(tmp_path, run), {"artifact_sha256": "abc"})
    assert code == 0 and out["counts"]["PASS"] == len(run)
    for s in M.CATALOG["scenarios"]:
        assert s["title"] in md
    assert "`abc`" in md and "PENDING_VM" in md and "BLOCKED_MISSING_BASELINE" in md


def test_summary_release_requires_every_scenario_to_pass(tmp_path):
    doc = M.plan({"ROOFSPAN_RELEASE_BUILD": "true"})
    run = {s["id"]: "PASS" for s in doc["scenarios"] if s["disposition"] == "RUN_HOSTED"}
    assert M.summarize(doc, _results(tmp_path, run), {})[2] == 1


def test_summary_missing_result_is_a_failure(tmp_path):
    doc = M.plan({})
    out, _, code = M.summarize(doc, tmp_path, {})
    assert code == 1
    assert all(r["status"] == "FAIL" for r in out["scenarios"] if r["disposition"] == "RUN_HOSTED")


# -- workflow contract --------------------------------------------------------------------------------------------------
WF = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
JOBS = WF["jobs"]


def _runs(job):
    return "\n".join(s.get("run", "") for s in JOBS[job]["steps"])


def test_installer_is_built_exactly_once_in_production_mode():
    builders = [j for j in JOBS if "build.ps1" in _runs(j) or "stage.ps1" in _runs(j)]
    assert builders == ["build"]
    assert "TestFaultInjection" not in WORKFLOW.read_text() and "ROOFSPAN_UPGRADE_FAULT" not in WORKFLOW.read_text()
    assert "fault_injection -ne $false" in _runs("build")
    assert "Remove-Item $env:EDB_INSTALLER, $env:WV_INSTALLER" in _runs("build")


@pytest.mark.parametrize("job", ["hosted", "vm"])
def test_scenario_jobs_test_the_same_bytes_and_always_upload_evidence(job):
    steps = JOBS[job]["steps"]
    dl = [s for s in steps if s.get("uses", "").startswith("actions/download-artifact")]
    assert dl and dl[0]["with"]["name"] == "matrix-installer"
    run = [s for s in steps if "Invoke-MatrixScenario.ps1" in s.get("run", "")][0]
    assert run["env"]["EXPECTED_SHA256"] == "${{ needs.build.outputs.artifact_sha256 }}"
    assert run["env"]["ROOFSPAN_MATRIX_DESTRUCTIVE"] == ACK
    up = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    assert up and all(s.get("if") == "always()" for s in up)
    assert JOBS[job]["strategy"]["fail-fast"] is False


def test_vm_job_only_targets_disposable_vm_runners():
    assert JOBS["vm"]["runs-on"] == ["self-hosted", "Windows", "roofspan-disposable-vm"]
    assert JOBS["vm"]["if"] == "needs.plan.outputs.has_vm == 'true'"


def test_summary_always_runs_and_gates():
    s = JOBS["summary"]
    assert s["if"] == "always()" and set(s["needs"]) == {"build", "plan", "hosted", "vm"}
    assert "GITHUB_STEP_SUMMARY" in _runs("summary") and "exit $rc" in _runs("summary")


def test_destructive_ack_is_only_given_to_scenario_jobs():
    for name, job in JOBS.items():
        text = json.dumps(job)
        assert (ACK in text) == (name in ("hosted", "vm")), name


# -- PowerShell: parse + pure helpers + guard refusal (real pwsh when available) -----------------------------------
needs_pwsh = pytest.mark.skipif(not PWSH, reason="ENV: pwsh is not installed on this machine (CI validate job has it)")


def _pwsh(script: str, **kw):
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, **kw)


@needs_pwsh
def test_matrix_powershell_and_inline_workflow_powershell_parse(tmp_path):
    sources = [MATRIX / "MatrixLib.psm1", MATRIX / "Invoke-MatrixScenario.ps1"]
    for name, job in JOBS.items():
        for i, step in enumerate(job["steps"]):
            if "run" in step and step.get("shell") == "pwsh":
                p = tmp_path / f"{name}-{i}.ps1"
                p.write_text(re.sub(r"\$\{\{[^}]*\}\}", "X", step["run"]))
                sources.append(p)
    for src in sources:
        r = _pwsh(f"$t=$null;$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('{src}',[ref]$t,[ref]$e);"
                  "if ($e) { $e | % { $_.Message }; exit 1 }")
        assert r.returncode == 0, f"{src.name}: {r.stdout}{r.stderr}"


@needs_pwsh
def test_library_assertions_polling_and_redaction(tmp_path):
    ev = tmp_path / "ev"
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module '{MATRIX / 'MatrixLib.psm1'}' -Force
Initialize-Matrix '{ev}'
Register-Secret 'TopSecret-123'
Write-Assertion 'first' $true 'value TopSecret-123 and postgresql://u:pw123456@h/db'
$v = Wait-Until {{ 42 }} 5 'immediate'
if ($v -ne 42) {{ throw 'wait-until value' }}
$t0 = Get-Date
try {{ Wait-Until {{ $false }} 1 'never' -PollMs 100; throw 'no timeout' }} catch {{ if ($_.Exception.Message -notmatch 'timed out after 1 s') {{ throw }} }}
try {{ Wait-Until {{ throw 'ABORT: stop now' }} 30 'abort' ; throw 'no abort' }} catch {{ if ($_.Exception.Message -ne 'ABORT: stop now') {{ throw }} }}
if (((Get-Date) - $t0).TotalSeconds -gt 10) {{ throw 'abort did not short-circuit' }}
try {{ Write-Assertion 'second' $false 'boom'; throw 'no throw' }} catch {{ if ($_.Exception.Message -notmatch 'ASSERTION FAILED \\[second\\]') {{ throw }} }}
'done'
"""
    r = _pwsh(script)
    assert r.returncode == 0 and "done" in r.stdout, r.stdout + r.stderr
    lines = [json.loads(x) for x in (ev / "assertions.jsonl").read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    assert [(x["name"], x["ok"]) for x in lines] == [("first", True), ("second", False)]
    assert "TopSecret-123" not in lines[0]["detail"] and "pw123456" not in lines[0]["detail"]


@needs_pwsh
def test_scenario_runner_refuses_outside_a_disposable_environment(tmp_path):
    ev = tmp_path / "ev"
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path), "ROOFSPAN_MATRIX_DESTRUCTIVE": ACK}
    r = subprocess.run([PWSH, "-NoProfile", "-File", str(MATRIX / "Invoke-MatrixScenario.ps1"), "-Scenario",
                        "clean-install-no-postgres", "-Setup", "x", "-ExpectedSha256", "0" * 64, "-BuildInfo", "x",
                        "-EvidenceDir", str(ev)], capture_output=True, text=True, env=env)
    assert r.returncode != 0
    assert "GUARD-REFUSED" in r.stdout + r.stderr
    assert not ev.exists(), "nothing may be created before the guard approves"


def test_matrix_runs_for_relevant_main_changes_tags_and_manual():
    on = WF.get("on", WF.get(True))
    relevant = ["windows/**", "backend/**", "frontend/**", ".github/workflows/windows-installer-matrix.yml"]
    assert "main" in on["push"]["branches"] and on["push"]["paths"] == relevant
    assert on["push"]["tags"] == ["v*"]
    assert on["pull_request"]["branches"] == ["main"] and on["pull_request"]["paths"] == relevant
    assert "workflow_dispatch" in on
