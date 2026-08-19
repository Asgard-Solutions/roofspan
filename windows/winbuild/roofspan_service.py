r"""Shared Windows-service scaffolding for the three RoofSpan Office background executables.

Each service exe (roofspan-backend / roofspan-relay-connector / roofspan-update-service) is a REAL
native Windows SCM service hosted via pywin32 (win32serviceutil.ServiceFramework + servicemanager).
This module provides:

  * load_runtime_config()  - deterministic, install-owned configuration (NEVER a user-shell env var).
                             Reads C:\ProgramData\RoofSpan\config\roofspan.env when present and fills
                             in install-relative + production defaults so a service launched by SCM
                             (no interactive user, no PowerShell env) always has what it needs.
  * get_logger()           - rotating log under C:\ProgramData\RoofSpan\logs\<name>.log. Startup /
                             shutdown / exceptions (with traceback) are logged; secrets never are.
  * make_service_class()   - builds a ServiceFramework subclass that drives a Worker through the full
                             SCM lifecycle: START_PENDING -> (worker ready) -> RUNNING ->
                             STOP_PENDING -> clean terminate -> STOPPED, with a nonzero exit on init
                             failure. pywin32 is imported lazily so this module stays importable (and
                             unit-testable) on non-Windows CI.
  * drive_lifecycle()      - the same lifecycle contract without pywin32, so the ordering/readiness/
                             stop semantics are unit-tested on Linux against a fake worker.

A Worker implements: start(on_ready)  (non-blocking; call on_ready() once genuinely RUNNING),
                     wait_ready(timeout)  (raise if init failed / timed out),
                     stop()  (request a clean stop),
                     wait(timeout)  (block until the worker thread has fully terminated).
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import time
import traceback

# Backend readiness (migrations + lifespan) can legitimately take a while on first run.
DEFAULT_READY_TIMEOUT = float(os.environ.get("ROOFSPAN_SERVICE_READY_TIMEOUT", "120"))


def data_root() -> str:
    """Persistent per-machine data root. Overridable (tests/CI) but defaults to the production path."""
    return os.environ.get("ROOFSPAN_DATA_ROOT", r"C:\ProgramData\RoofSpan")


def install_root() -> str:
    """INSTALLFOLDER. Frozen exe lives at INSTALLFOLDER/services/<name>/<name>.exe (PyInstaller
    onedir), so walk up until we see the sibling 'frontend'/'config-templates' payload."""
    if os.environ.get("ROOFSPAN_INSTALL_ROOT"):
        return os.environ["ROOFSPAN_INSTALL_ROOT"]
    base = os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)
    d = os.path.dirname(base)
    for _ in range(5):
        if os.path.isdir(os.path.join(d, "frontend")) or os.path.isdir(os.path.join(d, "config-templates")):
            return d
        d = os.path.dirname(d)
    # Fallback: three levels up from the exe (services\<name>\<name>.exe -> INSTALLFOLDER).
    return os.path.dirname(os.path.dirname(os.path.dirname(base)))


def _parse_env_file(path: str) -> dict:
    out = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def config_path() -> str:
    """Path to the installed local config file the services read (written by first-install bootstrap)."""
    return os.path.join(data_root(), "config", "roofspan.env")


def load_runtime_config() -> None:
    """Populate os.environ from the installed config file + deterministic defaults (idempotent)."""
    root = install_root()
    droot = data_root()

    cfg_file = config_path()
    if os.path.isfile(cfg_file):
        for k, v in _parse_env_file(cfg_file).items():
            os.environ.setdefault(k, v)

    os.environ.setdefault("ROOFSPAN_STATIC_DIR", os.path.join(root, "frontend"))
    os.environ.setdefault("INSTALLATION_KEYS_DIR", os.path.join(droot, "identity"))
    os.environ.setdefault("ROOFSPAN_UPDATE_PUBLIC_KEY",
                          os.path.join(root, "config-templates", "update_public_key.pem"))
    # Production defaults (outbound relay + signed-update manifest). NOT derived from a user shell.
    os.environ.setdefault("ROOFSPAN_RELAY_WS_URL", "wss://relay.roofspan.io/api/relay/tunnel")
    os.environ.setdefault("ROOFSPAN_LOCAL_API_URL", "http://127.0.0.1:8001")
    os.environ.setdefault("ROOFSPAN_WINDOWS_UPDATE_MANIFEST_URL",
                          "https://downloads.roofspan.io/update/windows/latest.json")


def logs_dir() -> str:
    d = os.path.join(data_root(), "logs")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def get_logger(name: str, filename: str) -> logging.Logger:
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    # Service-owned records must not bubble to root and get written twice after backend logging is wired.
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        fh = logging.handlers.RotatingFileHandler(
            os.path.join(logs_dir(), filename), maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError:
        pass
    # SCM services have no interactive stderr. Do not construct a console handler around a None stream.
    # In `...exe debug` mode stderr exists, so the same logger still mirrors output to the console.
    if sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        log.addHandler(sh)
    return log


def drive_lifecycle(worker, logger, stop_wait, report_running, ready_timeout=DEFAULT_READY_TIMEOUT):
    """SCM-agnostic lifecycle used by BOTH the pywin32 host and the Linux unit tests.

    stop_wait(): blocks until a stop has been requested (SCM stop event / test event).
    report_running(): called exactly once, only after the worker is genuinely RUNNING.
    Returns 0 on clean stop; raises on init failure (caller maps to a nonzero SCM exit).
    """
    logger.info("service starting")
    worker.start(on_ready=lambda: None)
    worker.wait_ready(ready_timeout)  # raises on init failure / timeout
    report_running()
    logger.info("service RUNNING")
    try:
        stop_wait()
    finally:
        logger.info("stop requested; shutting down worker")
        worker.stop()
        worker.wait(30)
    logger.info("service stopped cleanly")
    return 0


def make_service_class(svc_name: str, svc_display: str, worker_factory, log_filename: str):
    """Return a win32serviceutil.ServiceFramework subclass hosting `worker_factory(logger)`.

    pywin32 is imported HERE (call time) so importing this module on non-Windows never fails.
    """
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    class _RoofSpanService(win32serviceutil.ServiceFramework):
        _svc_name_ = svc_name
        _svc_display_name_ = svc_display

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_evt = win32event.CreateEvent(None, 0, 0, None)
            self._worker = None
            self._log = get_logger(svc_name, log_filename)

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self._log.info("SCM SERVICE_CONTROL_STOP received")
            try:
                if self._worker is not None:
                    self._worker.stop()
            except Exception:  # noqa: BLE001
                self._log.error("worker.stop() failed:\n%s", traceback.format_exc())
            win32event.SetEvent(self._stop_evt)

        def SvcDoRun(self):
            import threading as _t
            try:
                self.ReportServiceStatus(win32service.SERVICE_START_PENDING, waitHint=180000)
                load_runtime_config()
                self._worker = worker_factory(self._log)
                # Initialization (first-install DB bootstrap + migrations) can legitimately exceed SCM's
                # default start timeout, so run it in a thread and keep sending START_PENDING heartbeats
                # until the worker is genuinely ready (or fails).
                ready = _t.Event()
                err = {}

                def _init():
                    try:
                        self._worker.start(on_ready=lambda: None)
                        self._worker.wait_ready(DEFAULT_READY_TIMEOUT)
                    except Exception as e:  # noqa: BLE001
                        err["e"] = e
                    finally:
                        ready.set()

                _t.Thread(target=_init, name=f"{svc_name}-init", daemon=True).start()
                while not ready.wait(5):
                    self.ReportServiceStatus(win32service.SERVICE_START_PENDING, waitHint=20000)
                if "e" in err:
                    raise err["e"]

                self.ReportServiceStatus(win32service.SERVICE_RUNNING)
                servicemanager.LogInfoMsg(f"{svc_name} is running")
                self._log.info("%s RUNNING", svc_name)
                win32event.WaitForSingleObject(self._stop_evt, win32event.INFINITE)
                self._worker.wait(30)
                self._log.info("%s stopped cleanly", svc_name)
            except Exception:  # noqa: BLE001
                tb = traceback.format_exc()
                self._log.error("FATAL: %s failed to start/run:\n%s", svc_name, tb)
                try:
                    servicemanager.LogErrorMsg(f"{svc_name} failed: {tb[:800]}")
                except Exception:  # noqa: BLE001
                    pass
                # Report a nonzero service-specific error so SCM does NOT think the start succeeded.
                self.ReportServiceStatus(win32service.SERVICE_STOPPED,
                                         win32ExitCode=win32service.SERVICE_SPECIFIC_ERROR,
                                         svcExitCode=1)

    return _RoofSpanService


def dispatch(service_cls) -> None:
    """SCM entry: when launched by the Service Control Manager (no extra args) host the dispatcher;
    otherwise (developer console) fall through to install/remove/start/stop/debug handling."""
    import servicemanager
    import win32serviceutil

    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(service_cls)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(service_cls)
