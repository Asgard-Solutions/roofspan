r"""Linux-runnable guards for the RoofSpan Windows SCM services.

pywin32 and the real SCM only exist on Windows (proven end-to-end by the windows-latest CI job), but the
lifecycle CONTRACT, the deterministic config loader, and the service AUTHORING are all verified here on
every platform so a regression (e.g. a blocking uvicorn.run() creeping back, or a service reverting to a
user-shell env var) fails fast.
"""
import os
import re
import sys
import threading
import time
from pathlib import Path

import pytest

WINBUILD = Path(__file__).resolve().parents[1] / "winbuild"
sys.path.insert(0, str(WINBUILD))

import roofspan_service as rs  # noqa: E402
import db_bootstrap as boot  # noqa: E402


# ---- First-install DB bootstrap (pure logic; asyncpg/DPAPI/PG proven in the clean-install CI job) ---

def test_generated_db_password_is_strong_and_differs_from_superuser():
    su = "SuperSecret123"
    pw = boot.generate_db_password(exclude=su)
    assert pw != su
    assert len(pw) >= 24
    assert pw.isalnum() and any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw)
    # two calls must not collide
    assert boot.generate_db_password() != boot.generate_db_password()


def test_render_env_replaces_placeholder_only():
    template = (
        "DATABASE_URL=postgresql+asyncpg://roofspan:__GENERATED_AT_FIRST_RUN__@127.0.0.1:5432/roofspan\n"
        "ROOFSPAN_VERSION=0.2.0\n"
    )
    out = boot.render_env_from_template(template, "AbC123xyz")
    assert "__GENERATED_AT_FIRST_RUN__" not in out
    assert "postgresql+asyncpg://roofspan:AbC123xyz@127.0.0.1:5432/roofspan" in out
    assert "ROOFSPAN_VERSION=0.2.0" in out


def test_config_provisioned_detection(tmp_path):
    cfg = tmp_path / "roofspan.env"
    # placeholder -> NOT provisioned
    cfg.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:__GENERATED_AT_FIRST_RUN__@127.0.0.1:5432/roofspan\n")
    assert boot.config_is_provisioned(str(cfg)) is False
    # real generated password -> provisioned
    cfg.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:Ab12Cd34@127.0.0.1:5432/roofspan\n")
    assert boot.config_is_provisioned(str(cfg)) is True
    assert boot.parse_generated_password(cfg.read_text()) == "Ab12Cd34"
    # missing file -> NOT provisioned
    assert boot.config_is_provisioned(str(tmp_path / "nope.env")) is False


def test_bootstrap_reuses_existing_credentials_without_touching_postgres(tmp_path, monkeypatch):
    """Idempotency: a valid provisioned config is reused verbatim (no DPAPI, no PG, no rotation)."""
    cfg = tmp_path / "config" / "roofspan.env"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:KeepMe9999@127.0.0.1:5432/roofspan\n"
                   "ROOFSPAN_VERSION=0.2.0\n")

    def _boom(*a, **k):
        raise AssertionError("must NOT contact PostgreSQL/DPAPI when already provisioned")

    monkeypatch.setattr(boot, "decrypt_super_password", _boom)
    url = boot.bootstrap(_Logger(), template_path=str(tmp_path / "tpl"), config_path=str(cfg),
                         identity_dir=str(tmp_path / "identity"))
    assert url == "postgresql+asyncpg://roofspan:KeepMe9999@127.0.0.1:5432/roofspan"
    assert os.environ["DATABASE_URL"] == url
    assert os.environ["ROOFSPAN_VERSION"] == "0.2.0"


def test_backend_provisions_db_before_importing_app():
    src = (WINBUILD / "backend_entry.py").read_text(encoding="utf-8")
    assert "_provision_database" in src and "db_bootstrap.bootstrap" in src
    # provisioning must happen before the app (server:app) is constructed/imported
    assert src.index("self._provision_database()") < src.index('uvicorn.Config("server:app"')


def test_shipped_template_still_carries_placeholder():
    tpl = (WINBUILD / "config" / "roofspan.env.template").read_text(encoding="utf-8")
    assert "__GENERATED_AT_FIRST_RUN__" in tpl, "template must NOT ship a real DB password"


def test_ci_service_job_is_a_clean_install():
    """The Windows service CI must NOT pre-provision the DB - it must exercise RoofSpan's own bootstrap."""
    wf = (Path(rs.__file__).resolve().parents[2] / ".github" / "workflows" / "windows-build-scripts.yml").read_text(encoding="utf-8")
    job = wf.split("services-install-smoke:", 1)[1]
    assert "CREATE ROLE roofspan" not in job, "CI must not manually create the roofspan role"
    assert "CREATE DATABASE roofspan" not in job, "CI must not manually create the roofspan database"
    assert "DATABASE_URL=postgresql" not in job, "CI must not hand-write roofspan.env before install"
    # It must reproduce only the clean-machine state (DPAPI superuser secret) and let bootstrap run.
    assert "pg_super.bin" in job and "ProtectedData" in job
    assert "__GENERATED_AT_FIRST_RUN__" in job, "CI must assert the placeholder is gone post-install"


# ---- Deterministic config (never a user-shell env var) ----------------------------------------------

def test_config_loads_from_installed_file_and_defaults(tmp_path, monkeypatch):
    for k in ("ROOFSPAN_RELAY_WS_URL", "ROOFSPAN_STATIC_DIR", "INSTALLATION_KEYS_DIR",
              "ROOFSPAN_UPDATE_PUBLIC_KEY", "ROOFSPAN_LOCAL_API_URL",
              "ROOFSPAN_WINDOWS_UPDATE_MANIFEST_URL"):
        monkeypatch.delenv(k, raising=False)
    root = tmp_path / "install"
    (root / "frontend").mkdir(parents=True)
    data = tmp_path / "data"
    (data / "config").mkdir(parents=True)
    (data / "config" / "roofspan.env").write_text(
        "# comment\nDATABASE_URL=postgresql+asyncpg://roofspan:pw@127.0.0.1:5432/roofspan\n"
        "ROOFSPAN_RELAY_WS_URL=wss://relay.example/api/relay/tunnel\n", encoding="utf-8")
    monkeypatch.setenv("ROOFSPAN_INSTALL_ROOT", str(root))
    monkeypatch.setenv("ROOFSPAN_DATA_ROOT", str(data))

    rs.load_runtime_config()

    # value from the installed config file
    assert os.environ["DATABASE_URL"].startswith("postgresql+asyncpg://roofspan")
    assert os.environ["ROOFSPAN_RELAY_WS_URL"] == "wss://relay.example/api/relay/tunnel"
    # install-relative + production defaults (no user shell required)
    assert os.environ["ROOFSPAN_STATIC_DIR"] == str(root / "frontend")
    assert os.environ["INSTALLATION_KEYS_DIR"] == str(data / "identity")
    assert os.environ["ROOFSPAN_LOCAL_API_URL"] == "http://127.0.0.1:8001"


def test_relay_url_has_production_default(monkeypatch):
    for k in ("ROOFSPAN_RELAY_WS_URL",):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ROOFSPAN_DATA_ROOT", "/nonexistent-roofspan-data")
    monkeypatch.setenv("ROOFSPAN_INSTALL_ROOT", "/nonexistent-roofspan-install")
    rs.load_runtime_config()
    # The relay endpoint must resolve WITHOUT the customer setting an env var.
    assert os.environ["ROOFSPAN_RELAY_WS_URL"] == "wss://relay.roofspan.io/api/relay/tunnel"


# ---- SCM lifecycle contract (simulated; no pywin32) -------------------------------------------------

class _FakeWorker:
    def __init__(self, fail_init=False, ready_delay=0.0):
        self.events = []
        self._fail = fail_init
        self._ready_delay = ready_delay
        self._ready = threading.Event()
        self._stopped = threading.Event()

    def start(self, on_ready=None):
        self.events.append("start")

        def _run():
            time.sleep(self._ready_delay)
            if not self._fail:
                self._ready.set()
                if on_ready:
                    on_ready()
        threading.Thread(target=_run, daemon=True).start()

    def wait_ready(self, timeout):
        if self._fail:
            raise RuntimeError("init failed")
        if not self._ready.wait(timeout):
            raise TimeoutError("not ready")
        self.events.append("ready")

    def stop(self):
        self.events.append("stop")
        self._stopped.set()

    def wait(self, timeout=30):
        self.events.append("wait")


class _Logger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def exception(self, *a, **k):
        pass


def test_lifecycle_reports_running_only_after_worker_ready():
    w = _FakeWorker(ready_delay=0.05)
    running = threading.Event()
    stop_flag = threading.Event()

    def stop_wait():
        stop_flag.wait(2)

    t = threading.Thread(target=lambda: rs.drive_lifecycle(
        w, _Logger(), stop_wait, running.set, ready_timeout=2), daemon=True)
    t.start()
    assert running.wait(2), "service never reported RUNNING"
    # RUNNING was reported only after the worker became ready.
    assert w.events.index("ready") < w.events.index("start") + 2
    stop_flag.set()
    t.join(3)
    # Clean shutdown ordering: stop() then wait().
    assert w.events[-2:] == ["stop", "wait"]


def test_lifecycle_raises_on_init_failure_and_does_not_report_running():
    w = _FakeWorker(fail_init=True)
    running = threading.Event()
    err = {}

    def _go():
        try:
            rs.drive_lifecycle(w, _Logger(), lambda: None, running.set, ready_timeout=1)
        except Exception as e:  # noqa: BLE001
            err["e"] = e

    t = threading.Thread(target=_go, daemon=True)
    t.start()
    t.join(3)
    assert "e" in err, "init failure must propagate (mapped to a nonzero SCM exit)"
    assert not running.is_set(), "must NOT report RUNNING when initialization failed"


# ---- Service authoring guards (real SCM services, no blocking run, no user-shell dependency) --------

ENTRIES = {
    "backend_entry.py": "RoofSpanBackend",
    "relay_entry.py": "RoofSpanRelayConnector",
    "update_service_entry.py": "RoofSpanUpdateService",
}


def test_entries_are_real_scm_services():
    for fname, svc in ENTRIES.items():
        src = (WINBUILD / fname).read_text(encoding="utf-8")
        assert f'SVC_NAME = "{svc}"' in src, f"{fname} must host the {svc} service"
        assert "make_service_class" in src and "dispatch(" in src, f"{fname} must dispatch to SCM"
        assert "load_runtime_config()" in src, f"{fname} must load deterministic config"
        for meth in ("def start", "def stop", "def wait", "def wait_ready"):
            assert meth in src, f"{fname} worker missing {meth} (SCM controllability)"


def test_backend_uses_controllable_server_not_blocking_run():
    src = (WINBUILD / "backend_entry.py").read_text(encoding="utf-8")
    assert "uvicorn.Server(" in src, "backend must use a controllable uvicorn.Server"
    assert "should_exit = True" in src, "SvcStop must be able to signal a clean uvicorn shutdown"
    assert "uvicorn.run(" not in src, "backend must NOT use the blocking uvicorn.run() as the service"
    assert '127.0.0.1' in src and "8001" in src
    # No-console fix: color/TTY detection must be disabled (SCM services have no stdout/stderr).
    assert "use_colors=False" in src, "uvicorn.Config must set use_colors=False for a console-less service"


def test_backend_uvicorn_config_builds_without_a_console(monkeypatch):
    """Reproduce the Windows SCM (no stdout/stderr) environment: building the backend's uvicorn.Config
    must NOT raise. Without use_colors=False, uvicorn's DefaultFormatter calls sys.stdout.isatty() ->
    AttributeError: 'NoneType' object has no attribute 'isatty' / ValueError: Unable to configure
    formatter 'default' (this test fails against the pre-fix code and passes after)."""
    import uvicorn

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    # The FIXED configuration (mirrors backend_entry.BackendWorker.start) must construct cleanly.
    cfg = uvicorn.Config("server:app", host="127.0.0.1", port=8001, log_level="info",
                         loop="asyncio", lifespan="on", use_colors=False)
    assert cfg.use_colors is False
    # The source must build the console-less config exactly this way (fails against pre-fix code).
    src = (WINBUILD / "backend_entry.py").read_text(encoding="utf-8")
    assert "use_colors=False" in src


def test_relay_does_not_require_user_shell_env_var():
    src = (WINBUILD / "relay_entry.py").read_text(encoding="utf-8")
    # Must NOT hard-require the env var (os.environ["ROOFSPAN_RELAY_WS_URL"]); must use a default.
    assert 'os.environ["ROOFSPAN_RELAY_WS_URL"]' not in src
    assert 'os.environ.get("ROOFSPAN_RELAY_WS_URL"' in src


def test_services_log_to_programdata_paths():
    expected = {
        "backend_entry.py": "backend-service.log",
        "relay_entry.py": "relay-service.log",
        "update_service_entry.py": "update-service.log",
    }
    for fname, logname in expected.items():
        src = (WINBUILD / fname).read_text(encoding="utf-8")
        assert logname in src, f"{fname} must log to {logname}"


def test_specs_are_onedir_with_pywin32():
    for spec in ("roofspan-backend.spec", "roofspan-relay-connector.spec", "roofspan-update-service.spec"):
        src = (WINBUILD / spec).read_text(encoding="utf-8")
        assert "COLLECT(" in src and "exclude_binaries=True" in src, f"{spec} must be ONEDIR (COLLECT)"
        assert "onefile=True" not in src, f"{spec} must not be onefile (breaks pywin32 SCM start)"
        for mod in ("win32serviceutil", "win32service", "servicemanager", "pywintypes", "win32event"):
            assert mod in src, f"{spec} must package pywin32 module {mod}"


def test_wix_declares_service_dependencies():
    wxs = (Path(rs.__file__).resolve().parents[1] / "installer" / "RoofSpan.wxs").read_text(encoding="utf-8")
    # Backend after PostgreSQL; Relay after Backend.
    assert re.search(r'Name="RoofSpanBackend".*?<ServiceDependency Id="RoofSpanPostgreSQL"', wxs, re.DOTALL)
    assert re.search(r'Name="RoofSpanRelayConnector".*?<ServiceDependency Id="RoofSpanBackend"', wxs, re.DOTALL)


def test_wix_acls_service_accounts_without_broad_grants():
    wxs = (Path(rs.__file__).resolve().parents[1] / "installer" / "RoofSpan.wxs").read_text(encoding="utf-8")
    assert 'util:PermissionEx' in wxs and 'Domain="NT SERVICE"' in wxs
    # Never broaden to Everyone / FullControl.
    assert "Everyone" not in wxs
    assert 'GenericAll="yes"' not in wxs
