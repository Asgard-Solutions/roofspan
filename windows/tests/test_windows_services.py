r"""Linux-runnable guards for the RoofSpan Windows SCM services.

pywin32 and the real SCM only exist on Windows (proven end-to-end by the windows-latest CI job), but the
lifecycle CONTRACT, the deterministic config loader, and the service AUTHORING are all verified here on
every platform so a regression (e.g. a blocking uvicorn.run() creeping back, or a service reverting to a
user-shell env var) fails fast.
"""
import base64
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
    assert boot.generate_db_password() != boot.generate_db_password()


def test_generated_runtime_secrets_are_valid():
    jwt_secret = boot.generate_jwt_secret()
    enc = boot.generate_secrets_encryption_key()
    assert len(jwt_secret) >= 48
    assert len(base64.urlsafe_b64decode(enc.encode("ascii"))) == 32


def test_render_env_replaces_all_local_secret_placeholders():
    template = (
        "DATABASE_URL=postgresql+asyncpg://roofspan:__GENERATED_AT_FIRST_RUN__@127.0.0.1:5432/roofspan\n"
        "JWT_SECRET=__GENERATED_JWT_SECRET__\n"
        "SECRETS_ENCRYPTION_KEY=__GENERATED_SECRETS_ENCRYPTION_KEY__\n"
        "ROOFSPAN_VERSION=0.2.0\n"
    )
    out = boot.render_env_from_template(template, "AbC123xyz")
    assert "__GENERATED_AT_FIRST_RUN__" not in out
    assert "__GENERATED_JWT_SECRET__" not in out
    assert "__GENERATED_SECRETS_ENCRYPTION_KEY__" not in out
    assert "postgresql+asyncpg://roofspan:AbC123xyz@127.0.0.1:5432/roofspan" in out
    values = boot._parse_env_text(out)
    assert values["JWT_SECRET"]
    assert len(base64.urlsafe_b64decode(values["SECRETS_ENCRYPTION_KEY"].encode("ascii"))) == 32


def test_config_provisioned_detection(tmp_path):
    cfg = tmp_path / "roofspan.env"
    cfg.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:__GENERATED_AT_FIRST_RUN__@127.0.0.1:5432/roofspan\n")
    assert boot.config_is_provisioned(str(cfg)) is False
    cfg.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:Ab12Cd34@127.0.0.1:5432/roofspan\n")
    assert boot.config_is_provisioned(str(cfg)) is True
    assert boot.parse_generated_password(cfg.read_text()) == "Ab12Cd34"
    assert boot.config_is_provisioned(str(tmp_path / "nope.env")) is False


def test_bootstrap_reuses_existing_db_credentials_and_repairs_missing_app_secrets(tmp_path, monkeypatch):
    cfg = tmp_path / "config" / "roofspan.env"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:KeepMe9999@127.0.0.1:5432/roofspan\n"
                   "ROOFSPAN_VERSION=0.2.0\n")

    def _boom(*a, **k):
        raise AssertionError("must NOT contact PostgreSQL/DPAPI when already provisioned")

    monkeypatch.setattr(boot, "decrypt_super_password", _boom)
    for key in ("DATABASE_URL", "JWT_SECRET", "SECRETS_ENCRYPTION_KEY", "ROOFSPAN_VERSION"):
        monkeypatch.delenv(key, raising=False)
    url = boot.bootstrap(_Logger(), template_path=str(tmp_path / "tpl"), config_path=str(cfg),
                         identity_dir=str(tmp_path / "identity"))
    assert url == "postgresql+asyncpg://roofspan:KeepMe9999@127.0.0.1:5432/roofspan"
    assert os.environ["DATABASE_URL"] == url
    assert os.environ["ROOFSPAN_VERSION"] == "0.2.0"
    assert os.environ["JWT_SECRET"]
    assert len(base64.urlsafe_b64decode(os.environ["SECRETS_ENCRYPTION_KEY"].encode("ascii"))) == 32
    repaired = cfg.read_text()
    assert "DATABASE_URL=postgresql+asyncpg://roofspan:KeepMe9999@" in repaired
    assert repaired.count("JWT_SECRET=") == 1
    assert repaired.count("SECRETS_ENCRYPTION_KEY=") == 1


def test_runtime_secret_repair_is_idempotent(tmp_path):
    cfg = tmp_path / "roofspan.env"
    cfg.write_text(
        "DATABASE_URL=postgresql+asyncpg://roofspan:KeepMe9999@127.0.0.1:5432/roofspan\n"
        "JWT_SECRET=keep-jwt\n"
        "SECRETS_ENCRYPTION_KEY=" + base64.urlsafe_b64encode(b"1" * 32).decode("ascii") + "\n"
    )
    before = cfg.read_text()
    boot.ensure_required_runtime_secrets(str(cfg), _Logger())
    assert cfg.read_text() == before


def test_backend_provisions_db_before_importing_app():
    src = (WINBUILD / "backend_entry.py").read_text(encoding="utf-8")
    assert "_provision_database" in src and "db_bootstrap.bootstrap" in src
    assert src.index("self._provision_database()") < src.index('uvicorn.Config("server:app"')


def test_shipped_template_carries_only_placeholders_for_local_secrets():
    tpl = (WINBUILD / "config" / "roofspan.env.template").read_text(encoding="utf-8")
    assert "__GENERATED_AT_FIRST_RUN__" in tpl
    assert "JWT_SECRET=__GENERATED_JWT_SECRET__" in tpl
    assert "SECRETS_ENCRYPTION_KEY=__GENERATED_SECRETS_ENCRYPTION_KEY__" in tpl


def test_ci_service_job_is_a_clean_install():
    wf = (Path(rs.__file__).resolve().parents[2] / ".github" / "workflows" / "windows-build-scripts.yml").read_text(encoding="utf-8")
    job = wf.split("services-install-smoke:", 1)[1]
    assert "CREATE ROLE roofspan" not in job
    assert "CREATE DATABASE roofspan" not in job
    assert "DATABASE_URL=postgresql" not in job
    assert "pg_super.bin" in job and "ProtectedData" in job
    assert "__GENERATED_AT_FIRST_RUN__" in job


# ---- Deterministic config ---------------------------------------------------------------------------

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
    assert os.environ["DATABASE_URL"].startswith("postgresql+asyncpg://roofspan")
    assert os.environ["ROOFSPAN_RELAY_WS_URL"] == "wss://relay.example/api/relay/tunnel"
    assert os.environ["ROOFSPAN_STATIC_DIR"] == str(root / "frontend")
    assert os.environ["INSTALLATION_KEYS_DIR"] == str(data / "identity")
    assert os.environ["ROOFSPAN_LOCAL_API_URL"] == "http://127.0.0.1:8001"


def test_relay_url_has_production_default(monkeypatch):
    monkeypatch.delenv("ROOFSPAN_RELAY_WS_URL", raising=False)
    monkeypatch.setenv("ROOFSPAN_DATA_ROOT", "/nonexistent-roofspan-data")
    monkeypatch.setenv("ROOFSPAN_INSTALL_ROOT", "/nonexistent-roofspan-install")
    rs.load_runtime_config()
    assert os.environ["ROOFSPAN_RELAY_WS_URL"] == "wss://relay.roofspan.io/api/relay/tunnel"


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
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass
    def exception(self, *a, **k): pass


def test_lifecycle_reports_running_only_after_worker_ready():
    w = _FakeWorker(ready_delay=0.05)
    running = threading.Event()
    stop_flag = threading.Event()
    def stop_wait(): stop_flag.wait(2)
    t = threading.Thread(target=lambda: rs.drive_lifecycle(w, _Logger(), stop_wait, running.set, ready_timeout=2), daemon=True)
    t.start()
    assert running.wait(2)
    stop_flag.set()
    t.join(3)
    assert w.events[-2:] == ["stop", "wait"]


def test_lifecycle_raises_on_init_failure_and_does_not_report_running():
    w = _FakeWorker(fail_init=True)
    running = threading.Event()
    err = {}
    def _go():
        try:
            rs.drive_lifecycle(w, _Logger(), lambda: None, running.set, ready_timeout=1)
        except Exception as e:
            err["e"] = e
    t = threading.Thread(target=_go, daemon=True)
    t.start(); t.join(3)
    assert "e" in err
    assert not running.is_set()


ENTRIES = {
    "backend_entry.py": "RoofSpanBackend",
    "relay_entry.py": "RoofSpanRelayConnector",
    "update_service_entry.py": "RoofSpanUpdateService",
}


def test_entries_are_real_scm_services():
    for fname, svc in ENTRIES.items():
        src = (WINBUILD / fname).read_text(encoding="utf-8")
        assert f'SVC_NAME = "{svc}"' in src
        assert "make_service_class" in src and "dispatch(" in src
        assert "load_runtime_config()" in src
        for meth in ("def start", "def stop", "def wait", "def wait_ready"):
            assert meth in src


def test_backend_uses_controllable_server_not_blocking_run():
    src = (WINBUILD / "backend_entry.py").read_text(encoding="utf-8")
    assert "uvicorn.Server(" in src
    assert "should_exit = True" in src
    assert "uvicorn.run(" not in src
    assert '127.0.0.1' in src and "8001" in src
    assert "use_colors=False" in src


def test_service_failure_path_uses_valid_pywin32_constant():
    src = (WINBUILD / "roofspan_service.py").read_text(encoding="utf-8")
    assert "win32service.ERROR_SERVICE_SPECIFIC_ERROR" not in src
    assert "win32service.SERVICE_SPECIFIC_ERROR" in src
    assert "svcExitCode=1" in src


def test_migrations_runner_is_frozen_runtime_safe():
    src = (Path(rs.__file__).resolve().parents[2] / "backend" / "migrations_runner.py").read_text(encoding="utf-8")
    assert 'getattr(sys, "frozen"' in src and "_MEIPASS" in src
