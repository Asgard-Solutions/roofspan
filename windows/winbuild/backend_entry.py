r"""roofspan-backend.exe - RoofSpanBackend Windows service (local Office API + Office UI).

Real SCM service. Runs the existing FastAPI app (server:app) via a CONTROLLABLE uvicorn.Server bound to
127.0.0.1:8001 only, serving the installed Office frontend from ROOFSPAN_STATIC_DIR. SERVICE_RUNNING is
reported only after uvicorn has actually started (lifespan startup - migrations, seed, bootstrap - done);
if initialization fails the service reports a nonzero error instead of a false "running".
"""
import os
import threading

import db_bootstrap
from roofspan_service import (config_path, dispatch, install_root, load_runtime_config,
                              make_service_class)

SVC_NAME = "RoofSpanBackend"
SVC_DISPLAY = "RoofSpan Backend"
LOG_FILE = "backend-service.log"


class BackendWorker:
    """Hosts uvicorn.Server in a background thread with a clean, signalable shutdown."""

    def __init__(self, logger):
        self.log = logger
        self._server = None
        self._thread = None
        self._ready = threading.Event()
        self._error = None

    def _provision_database(self):
        """First-install local PostgreSQL bootstrap. MUST complete (setting DATABASE_URL) BEFORE
        server/backend.db import. Raises on failure so the service never falsely reports RUNNING."""
        template = os.path.join(install_root(), "config-templates", "roofspan.env.template")
        db_bootstrap.bootstrap(
            self.log,
            template_path=template,
            config_path=config_path(),
            identity_dir=os.environ["INSTALLATION_KEYS_DIR"],
        )

    def start(self, on_ready=None):
        import logging
        import uvicorn

        # Route uvicorn/alembic/app logging - INCLUDING any FastAPI lifespan-startup traceback (uvicorn
        # logs it via 'uvicorn.error' and then exits WITHOUT re-raising) - into backend-service.log so a
        # failed startup is diagnosable instead of the generic "not started". Secrets are never logged
        # by these components; we only attach handlers, we do not print env/DATABASE_URL.
        for h in self.log.handlers:
            for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "alembic", "roofspan"):
                lg = logging.getLogger(name)
                if h not in lg.handlers:
                    lg.addHandler(h)
                if lg.level == logging.NOTSET or lg.level > logging.INFO:
                    lg.setLevel(logging.INFO)

        # Provision + load DATABASE_URL synchronously before importing the app (server:app -> db.py).
        self._provision_database()

        config = uvicorn.Config("server:app", host="127.0.0.1", port=8001,
                                log_level="info", loop="asyncio", lifespan="on",
                                use_colors=False)
        self._server = uvicorn.Server(config)

        def _run():
            try:
                self.log.info("backend: uvicorn serving on 127.0.0.1:8001")
                self._server.run()  # blocks; runs lifespan startup (migrations/seed/bootstrap)
                # uvicorn catches a FastAPI lifespan-startup failure, LOGS it (uvicorn.error, now routed
                # to backend-service.log) and returns WITHOUT re-raising. Detect that here so wait_ready
                # surfaces a real failure instead of a false success.
                if not getattr(self._server, "started", False) and self._error is None:
                    self._error = RuntimeError(
                        "FastAPI application/lifespan startup failed before uvicorn reported started; "
                        "see the 'Application startup failed' traceback above in backend-service.log")
                    self.log.error("backend: %s", self._error)
            except Exception as e:  # noqa: BLE001
                self._error = e
                self.log.exception("backend: server crashed")
            finally:
                self._ready.set()

        self._thread = threading.Thread(target=_run, name="roofspan-backend", daemon=True)
        self._thread.start()

        def _poll():
            while not self._ready.is_set():
                if getattr(self._server, "started", False):
                    self._ready.set()
                    break
                import time
                time.sleep(0.25)
            if on_ready and self._error is None:
                on_ready()

        threading.Thread(target=_poll, name="roofspan-backend-ready", daemon=True).start()

    def wait_ready(self, timeout):
        if not self._ready.wait(timeout):
            raise TimeoutError("backend did not reach RUNNING within timeout")
        if self._error is not None:
            raise self._error
        if not getattr(self._server, "started", False):
            raise RuntimeError("backend uvicorn reported not started")

    def stop(self):
        if self._server is not None:
            self._server.should_exit = True

    def wait(self, timeout=30):
        if self._thread is not None:
            self._thread.join(timeout)


def _worker_factory(logger):
    return BackendWorker(logger)


def main():
    load_runtime_config()
    dispatch(make_service_class(SVC_NAME, SVC_DISPLAY, _worker_factory, LOG_FILE))


if __name__ == "__main__":
    main()
