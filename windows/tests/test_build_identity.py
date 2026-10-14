"""Build identity (version + Git SHA) belongs to the executable, never to a saved roofspan.env.

The stale-configuration tests reproduce the upgrade defect: the built application is newer than the
ROOFSPAN_VERSION=0.4.5 left in an old roofspan.env, and every component must still report the build.
"""
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

WINDOWS = Path(__file__).resolve().parents[1]
WINBUILD = WINDOWS / "winbuild"
BACKEND = WINDOWS.parent / "backend"
for p in (str(WINDOWS), str(WINBUILD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import build_identity
import db_bootstrap as boot
import roofspan_service as rs

BUILT_VERSION = (WINDOWS / "VERSION").read_text().strip()
STALE_SHA = "0" * 40
STALE_CONFIG = (
    "DATABASE_URL=postgresql+asyncpg://roofspan:KeepMe9999@127.0.0.1:5432/roofspan\n"
    "JWT_SECRET=keep-jwt-secret\n"
    "SECRETS_ENCRYPTION_KEY=MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=\n"
    "ROOFSPAN_VERSION=0.4.5\n"
    f"ROOFSPAN_BUILD_SHA={STALE_SHA}\n"
)


class _Logger:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a):
        self.lines.append(msg % a if a else msg)

    warning = error = info


@pytest.fixture()
def stale_install(tmp_path, monkeypatch):
    """An upgraded machine: newer executable, old roofspan.env with stale build identity."""
    root = tmp_path / "RoofSpan"
    (root / "config").mkdir(parents=True)
    (root / "config" / "roofspan.env").write_bytes(STALE_CONFIG.encode())
    monkeypatch.setenv("ROOFSPAN_DATA_ROOT", str(root))
    monkeypatch.setenv("ROOFSPAN_INSTALL_ROOT", str(tmp_path / "Program Files" / "RoofSpan Office"))
    # The executable's embedded identity (what the frozen build-info hook provides).
    monkeypatch.setattr(build_identity, "VERSION", BUILT_VERSION)
    monkeypatch.setattr(build_identity, "BUILD_SHA", "a" * 40)
    for k in ("ROOFSPAN_VERSION", "ROOFSPAN_BUILD_SHA", "DATABASE_URL", "JWT_SECRET", "SECRETS_ENCRYPTION_KEY"):
        monkeypatch.delenv(k, raising=False)
    build_identity.enforce()
    monkeypatch.setattr(boot, "decrypt_super_password",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no DPAPI for provisioned config")))
    monkeypatch.setattr(boot, "repair_control_plane_db", lambda *a, **k: None)
    return root


def _boot(root):
    rs.load_runtime_config()
    boot.bootstrap(_Logger(), "unused-template", str(root / "config" / "roofspan.env"), str(root / "identity"))


_ISOLATED = ("version", "licensing", "licensing.config", "update_service_entry", "relay_entry")


@pytest.fixture(autouse=True)
def _isolate_backend_modules(monkeypatch):
    """backend/version.py and windows/version.py share the module name `version`; never leak either."""
    saved = {m: sys.modules.get(m) for m in _ISOLATED}
    yield
    for m, mod in saved.items():
        if mod is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = mod


def _fresh(module_name):
    if module_name in ("version", "licensing.config"):
        sys.path.insert(0, str(BACKEND))
        try:
            for m in ("version", "licensing", "licensing.config") if module_name == "version" else ("licensing", "licensing.config"):
                sys.modules.pop(m, None)
            return importlib.import_module(module_name)
        finally:
            sys.path.remove(str(BACKEND))
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_backend_api_version_uses_executable_not_stale_config(stale_install):
    _boot(stale_install)
    version = _fresh("version")
    assert version.ROOFSPAN_VERSION == BUILT_VERSION
    assert version.BUILD_SHA == "a" * 40


def test_licensing_software_version_uses_executable_not_stale_config(stale_install):
    _boot(stale_install)
    _fresh("version")
    lic = _fresh("licensing.config")
    assert lic.SOFTWARE_VERSION == BUILT_VERSION


def test_update_service_current_version_uses_executable_not_stale_config(stale_install, monkeypatch):
    # The shipped updater had no build-info hook, so nothing set ROOFSPAN_VERSION before config loading.
    monkeypatch.delenv("ROOFSPAN_VERSION", raising=False)
    rs.load_runtime_config()
    upd = _fresh("update_service_entry")
    assert upd._current_version() == BUILT_VERSION


def test_relay_build_info_uses_executable_not_stale_config(stale_install):
    rs.load_runtime_config()
    relay = _fresh("relay_entry")
    info = relay.build_info()
    assert info["version"] == BUILT_VERSION and info["build_sha"] == "a" * 40


def test_loading_stale_config_cannot_change_build_identity(stale_install):
    rs.load_runtime_config()
    boot._load_env_file_into_process(str(stale_install / "config" / "roofspan.env"))
    assert os.environ["ROOFSPAN_VERSION"] == BUILT_VERSION
    assert os.environ["ROOFSPAN_BUILD_SHA"] == "a" * 40


def test_template_carries_no_build_identity():
    tpl = (WINBUILD / "config" / "roofspan.env.template").read_text(encoding="utf-8")
    for key in build_identity.IDENTITY_KEYS:
        assert not re.search(rf"^\s*{key}\s*=", tpl, re.MULTILINE), key


def test_all_three_specs_embed_the_same_build_info_hook():
    for spec in ("roofspan-backend.spec", "roofspan-relay-connector.spec", "roofspan-update-service.spec"):
        txt = (WINBUILD / spec).read_text(encoding="utf-8")
        assert 'BUILD_INFO_HOOK = os.environ.get("ROOFSPAN_BUILD_INFO_HOOK", "")' in txt, spec
        assert "runtime_hooks=RUNTIME_HOOKS" in txt, spec
        assert '"_roofspan_build_identity"' in txt, f"{spec} must freeze the generated identity module"
    build = (WINBUILD / "build_exes.ps1").read_text(encoding="utf-8")
    assert "_roofspan_build_identity.py" in build and "ROOFSPAN_BUILD_INFO_HOOK" in build


@pytest.mark.parametrize("entry,service", [("backend_entry.py", "roofspan-backend"),
                                           ("relay_entry.py", "roofspan-relay-connector"),
                                           ("update_service_entry.py", "roofspan-update-service")])
def test_every_executable_has_build_info_command(tmp_path, entry, service):
    env = dict(os.environ, ROOFSPAN_DATA_ROOT=str(tmp_path / "nodata"),
               PYTHONPATH=os.pathsep.join([str(WINBUILD), str(WINDOWS), str(BACKEND)]))  # as the specs' pathex
    out = subprocess.run([sys.executable, str(WINBUILD / entry), "--build-info"], env=env,
                         capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stderr[-2000:]
    info = json.loads(out.stdout.strip().splitlines()[-1])
    assert info["service"] == service
    assert info["version"] == BUILT_VERSION
    assert info["build_contract"] == build_identity.BUILD_CONTRACT
    assert "build_sha" in info and "embedded" in info
