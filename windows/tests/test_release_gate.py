"""Release-gate contract for the Windows installer workflow (static; runs in the `validate` job).

Guards that every packaged input triggers Windows validation, that all six required jobs exist and run
unconditionally, that exactly one tested installer artifact is uploaded, and that promotion never rebuilds.
"""
import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/windows-build-scripts.yml"
PROMOTE = REPO / ".github/workflows/release-promote.yml"
REQUIRED_JOBS = ["bundle-compile", "validate", "burn-prep-runtime", "clean-machine-full-install",
                 "services-install-smoke", "db-bootstrap-integration", "transactional-upgrade"]


def _load(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # PyYAML parses the bare key `on` as True
    return data


def _matches(pattern: str, path: str) -> bool:
    rx = re.escape(pattern).replace(r"\*\*", "§").replace(r"\*", "[^/]*").replace("§", ".*")
    return re.fullmatch(rx, path) is not None


def _packaged_inputs():
    """Concrete files whose change alters the shipped installer (resolved from the build scripts)."""
    spec = (REPO / "windows/winbuild/roofspan-backend.spec").read_text(encoding="utf-8")
    assert '"..", "..", "backend"' in spec, "backend spec source root changed; update this test"
    stage = (REPO / "windows/installer/stage.ps1").read_text(encoding="utf-8")
    assert '$FrontendDir = "..\\..\\frontend"' in stage
    assert "..\\shell\\RoofSpanOfficeShell.csproj" in stage
    files = [
        "backend/server.py", "backend/requirements.txt", "backend/alembic/env.py",
        "backend/control_plane/alembic.ini", "frontend/package.json", "frontend/yarn.lock",
        "frontend/src/App.js", "frontend/public/index.html", "frontend/craco.config.js",
        "windows/VERSION", "windows/installer/RoofSpan.wxs", "windows/installer/bundle.wxs",
        "windows/installer/scripts/Prepare-PostgreSQL.ps1", "windows/winbuild/build_exes.ps1",
        "windows/winbuild/config/roofspan.env.template", "windows/shell/Program.cs",
        "windows/shell/RoofSpanOfficeShell.csproj", "windows/updater/service.py",
        "package.json", "package-lock.json", ".github/workflows/windows-build-scripts.yml",
    ]
    # Every local `file:` dependency of the frontend is packaged into the Office UI.
    pkg = json.loads((REPO / "frontend/package.json").read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        for spec_value in pkg.get(section, {}).values():
            if str(spec_value).startswith("file:"):
                rel = (REPO / "frontend" / spec_value[5:]).resolve().relative_to(REPO).as_posix()
                files += [f"{rel}/package.json", f"{rel}/index.js"]
    return files


def test_pull_requests_always_run_all_windows_jobs():
    pr = _load(WORKFLOW)["on"]["pull_request"]
    assert "paths" not in pr and "paths-ignore" not in pr, \
        "PRs must not be path-filtered: required checks would stay pending and block unrelated PRs"
    assert pr.get("branches") == ["main"]


def test_push_paths_cover_every_packaged_input():
    paths = _load(WORKFLOW)["on"]["push"]["paths"]
    for required in ("windows/**", "backend/**", "frontend/**", "packages/roof-sketch-core/**",
                     ".github/workflows/windows-build-scripts.yml"):
        assert required in paths, required
    missing = [f for f in _packaged_inputs() if not any(_matches(p, f) for p in paths)]
    assert not missing, f"packaged inputs that would not trigger Windows validation: {missing}"


def test_six_required_jobs_exist_and_cannot_be_skipped():
    jobs = _load(WORKFLOW)["jobs"]
    assert sorted(jobs) == sorted(REQUIRED_JOBS)
    for name, job in jobs.items():
        assert "if" not in job, f"{name} must not be conditional (a skipped job reports success)"
        assert not job.get("continue-on-error"), name
        assert "name" not in job, f"{name}: a display name would change the required check name"
        for step in job["steps"]:
            assert not step.get("continue-on-error"), f"{name}: {step.get('name')}"


def test_full_install_uploads_one_tested_artifact_after_acceptance():
    steps = _load(WORKFLOW)["jobs"]["clean-machine-full-install"]["steps"]
    names = [s.get("name", "") for s in steps]
    uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")
               and s["with"]["name"] == "roofspan-office-installer"]
    assert len(uploads) == 1 and "if" not in uploads[0]
    assert uploads[0]["with"]["if-no-files-found"] == "error"
    up = steps.index(uploads[0])
    build = next(i for i, n in enumerate(names) if n.startswith("Build the FULL customer installer"))
    verify = next(i for i, n in enumerate(names) if n.startswith("Verify the built artifact"))
    install = next(i for i, n in enumerate(names) if n.startswith("Go OFFLINE"))
    legacy = next(i for i, n in enumerate(names) if n.startswith("Real legacy upgrade"))
    assert build < verify < install < legacy < up
    assert "Test-InstallerArtifact.ps1" in steps[verify]["run"]
    assert "ARTIFACT_SHA256" in steps[install]["run"]
    full = "\n".join(s.get("run", "") for s in steps)
    assert full.count("build.ps1 -Version") == 1, "the release installer must be built exactly once"
    jobs = _load(WORKFLOW)["jobs"]
    for name, job in jobs.items():
        if name == "clean-machine-full-install":
            continue
        for s in job["steps"]:
            if str(s.get("uses", "")).startswith("actions/upload-artifact"):
                assert s["with"]["name"] != "roofspan-office-installer", f"{name} must not publish an installer"
    txn = "\n".join(s.get("run", "") for s in jobs["transactional-upgrade"]["steps"])
    assert "-TestFaultInjection" in txn and "Invoke-TransactionalUpgradeAcceptance.ps1" in txn


def test_promotion_never_rebuilds_and_requires_all_jobs():
    text = PROMOTE.read_text(encoding="utf-8")
    for forbidden in ("wix build", "build.ps1", "stage.ps1", "build_exes", "pyinstaller", "yarn build",
                      "dotnet publish", "signtool", "actions/checkout"):
        assert forbidden not in text, forbidden
    for job in REQUIRED_JOBS:
        assert f'"{job}"' in text, job
    wf = _load(PROMOTE)
    assert list(wf["on"]) == ["workflow_dispatch"]
    steps = wf["jobs"]["promote"]["steps"]
    dl = [s for s in steps if str(s.get("uses", "")).startswith("actions/download-artifact")]
    assert len(dl) == 1 and dl[0]["with"]["name"] == "roofspan-office-installer"
    assert "run-id" in dl[0]["with"]
    assert "--draft" in text and "sha256sum -c SHA256SUMS.txt" in text


def test_no_tautological_assertions_in_windows_tests():
    for f in Path(__file__).resolve().parent.glob("test_*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("assert"):
                assert not re.search(r"\bor\s+True\b", line), f"{f.name}:{n} assertion can never fail"
