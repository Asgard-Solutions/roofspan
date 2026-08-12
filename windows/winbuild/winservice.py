"""Minimal, reusable Windows Service host for RoofSpan Office service executables.

Why this exists: a plain PyInstaller console exe registered via WiX `ServiceInstall` does NOT satisfy the
Windows Service Control Manager (SCM) contract — SCM starts the process and expects it to connect via
`StartServiceCtrlDispatcher` within ~30s, otherwise the service fails to start (error 1053). This module
provides the SCM integration (pywin32 `ServiceFramework`) plus a thread-safe async lifecycle runner so a
long-lived asyncio connector (e.g. the Secure Relay `InstallationTunnel`) can run as a real service and
stop cleanly on Windows STOP/shutdown.

Design:
  * `AsyncServiceRunner` — pure, OS-independent: owns an asyncio loop running ONE long-lived coroutine and
    supports a thread-safe `stop()` (called from the SCM control thread). Fully unit-testable on Linux.
  * `build_service_class(...)` / `dispatch(...)` — the pywin32 SCM glue. pywin32 is Windows-only, so those
    imports are LAZY (inside the functions); this module imports cleanly on Linux for static tests.

The connector business logic (InstallationTunnel) is NOT duplicated — the runner just drives it.
Native SCM execution remains HUMAN REQUIRED.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("roofspan.winservice")


class AsyncServiceRunner:
    """Runs a single long-lived coroutine on a dedicated event loop; thread-safe stop for SvcStop."""

    def __init__(self, coro_factory, on_stop=None, graceful_stop=False):
        self._coro_factory = coro_factory   # () -> coroutine (the long-lived connector loop)
        self._on_stop = on_stop             # optional sync callback (e.g. tunnel.stop / server.should_exit)
        self._graceful = graceful_stop      # if True, rely on on_stop to end the coroutine (no task.cancel)
        self._loop = None
        self._task = None

    def run(self) -> None:
        """Blocking: runs until the task completes or is cancelled by stop()."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._task = self._loop.create_task(self._coro_factory())
        try:
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        finally:
            self._drain()
            self._loop.close()

    def stop(self) -> None:
        """Thread-safe: signal the connector to stop. Graceful runners end via on_stop (e.g. uvicorn
        should_exit); others additionally get their task cancelled to interrupt sleeps/waits promptly."""
        if self._on_stop:
            try:
                self._on_stop()
            except Exception:  # noqa: BLE001 — stop must never raise
                log.exception("on_stop callback failed")
        if self._graceful:
            return
        loop, task = self._loop, self._task
        if loop is not None and task is not None:
            loop.call_soon_threadsafe(task.cancel)

    def _drain(self) -> None:
        try:
            pending = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:  # noqa: BLE001
            log.exception("error draining tasks on shutdown")


def build_service_class(svc_name: str, display_name: str, description: str, runner_factory):
    """Create a pywin32 ServiceFramework subclass bound to `runner_factory` (Windows-only; lazy import).

    `runner_factory` -> AsyncServiceRunner. `svc_name` MUST match the WiX ServiceInstall Name so SCM can
    dispatch to this class.
    """
    import win32serviceutil
    import win32service
    import servicemanager

    class _RoofSpanService(win32serviceutil.ServiceFramework):
        _svc_name_ = svc_name
        _svc_display_name_ = display_name
        _svc_description_ = description

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._runner = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            servicemanager.LogInfoMsg(f"{svc_name}: stop requested")
            if self._runner is not None:
                self._runner.stop()

        def SvcDoRun(self):
            servicemanager.LogInfoMsg(f"{svc_name}: starting")
            try:
                self._runner = runner_factory()
                self.ReportServiceStatus(win32service.SERVICE_RUNNING)
                self._runner.run()  # blocks until SvcStop cancels the task
            except SystemExit as e:
                servicemanager.LogErrorMsg(f"{svc_name}: exiting (code {e.code})")
                raise
            except Exception:  # noqa: BLE001
                servicemanager.LogErrorMsg(f"{svc_name}: crashed; SCM will apply the restart policy")
                raise
            servicemanager.LogInfoMsg(f"{svc_name}: stopped")

    return _RoofSpanService


def dispatch(service_class) -> None:
    """SCM entrypoint (Windows-only; lazy import).

    When SCM launches the exe (no args) -> connect to SCM via the control dispatcher.
    When an admin runs `exe install|start|stop|remove|debug` -> handle that verb.
    """
    import sys
    import servicemanager
    import win32serviceutil

    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(service_class)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(service_class)


# ---- shared runtime config helpers (used by all service entrypoints) ----

def load_env_file(path: str) -> dict:
    """Parse a simple KEY=VALUE env file (comments with '#', blank lines ignored). No external dep."""
    import os

    values: dict = {}
    if not path or not os.path.isfile(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def apply_env(values: dict, *, override: bool = False) -> None:
    """Apply values to os.environ. Existing (service/machine) env wins unless override=True."""
    import os

    for k, v in values.items():
        if override or k not in os.environ:
            os.environ[k] = v


def load_programdata_env(env_filename: str = "roofspan.env",
                         default_config_dir: str = r"C:\ProgramData\RoofSpan\config") -> None:
    """Load the ProgramData config file into the environment (service env wins). A Windows service does
    NOT auto-load a .env, so every service entrypoint calls this on startup."""
    import os

    config_dir = os.environ.get("ROOFSPAN_CONFIG_DIR", default_config_dir)
    apply_env(load_env_file(os.path.join(config_dir, env_filename)), override=False)