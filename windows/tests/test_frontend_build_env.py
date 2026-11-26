"""RC: the installed Office UI is always built for the local backend, never a preview/hosted server."""
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "installer" / "build-office-frontend.js"


def _check(tmp_path, files):
    d = tmp_path / "frontend"
    for rel, text in {"index.html": "<div id=root></div>", **files}.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return subprocess.run(["node", str(SCRIPT), "--check", str(d)], capture_output=True, text=True)


def test_check_accepts_local_only_build(tmp_path):
    r = _check(tmp_path, {"static/js/main.js": 'const BACKEND_URL="";fetch(BACKEND_URL+"/api/version")'})
    assert r.returncode == 0, r.stderr


def test_check_rejects_preview_server_address(tmp_path):
    r = _check(tmp_path, {"static/js/main.js": 'const B="https://roofspan-x.preview.emergentagent.com";'})
    assert r.returncode == 2 and "emergentagent.com" in r.stderr


def test_check_rejects_preview_tooling_in_index(tmp_path):
    r = _check(tmp_path, {"index.html": '<script src="https://assets.emergent.sh/scripts/emergent-main.js"></script>'})
    assert r.returncode == 2


def test_check_rejects_missing_build(tmp_path):
    (tmp_path / "frontend").mkdir()
    r = subprocess.run(["node", str(SCRIPT), "--check", str(tmp_path / "frontend")], capture_output=True, text=True)
    assert r.returncode == 2


def test_stage_and_build_use_the_guarded_frontend_build():
    stage = (ROOT / "installer" / "stage.ps1").read_text()
    assert '$env:REACT_APP_BACKEND_URL = ""' not in stage, "PowerShell 5.1 removes empty variables; use the node build"
    assert 'build-office-frontend.js") $feDirResolved' in stage
    assert 'build-office-frontend.js") --check $frontend' in stage
    build = (ROOT / "installer" / "build.ps1").read_text()
    assert "frontend\\roofspan-build.json" in build and "$feIdentity.git_sha -ne $gitSha" in build
    assert 'build-office-frontend.js") --check' in build


def test_version_is_release_candidate():
    assert (ROOT / "VERSION").read_text().strip() == "0.5.0"
    app = json.loads((ROOT.parent / "mobile" / "app.json").read_text())["expo"]
    assert app["version"] == "1.1.0" and "versionCode" not in app.get("android", {}) and "buildNumber" not in app.get("ios", {})
    eas = json.loads((ROOT.parent / "mobile" / "eas.json").read_text())
    assert eas["cli"]["appVersionSource"] == "remote"
    assert eas["build"]["preview"]["autoIncrement"] is True and eas["build"]["production"]["autoIncrement"] is True
