r"""roofspan-backend.exe - RoofSpanBackend Windows service (local Office API + Office UI).

Real SCM service. Runs the existing FastAPI app (server:app) via a CONTROLLABLE uvicorn.Server bound to
127.0.0.1:8001 only, serving the installed Office frontend from ROOFSPAN_STATIC_DIR. SERVICE_RUNNING is
reported only after uvicorn has actually started. Database bootstrap + Alembic migrations are completed
before uvicorn starts so migration failures surface directly in backend-service.log instead of being
hidden inside FastAPI lifespan handling.
"""
import os
import sys
import threading

import build_identity
import config_reconcile
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
        """First-install local PostgreSQL bootstrap. MUST complete (setting DATABASE_URL) before app import."""
        template = os.path.join(install_root(), "config-templates", "roofspan.env.template")
        # Upgrade/repair: reconcile an existing saved config (targeted, atomic, idempotent) before reuse.
        config_reconcile.reconcile(config_path(), template, install_root(), self.log)
        db_bootstrap.bootstrap(
            self.log,
            template_path=template,
            config_path=config_path(),
            identity_dir=os.environ["INSTALLATION_KEYS_DIR"],
        )

    def _wire_app_logging(self):
        """Route app/uvicorn/alembic records to the service-owned handlers exactly once."""
        import logging
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "alembic", "roofspan"):
            lg = logging.getLogger(name)
            for h in self.log.handlers:
                if h not in lg.handlers:
                    lg.addHandler(h)
            lg.setLevel(logging.INFO)
            lg.propagate = False

    def start(self, on_ready=None):
        import uvicorn

        self._wire_app_logging()

        # 1) Provision/reuse the local DB credentials.
        self._provision_database()

        # 2) Prove Field-photo persistence is actually writable under the service identity. This must
        # happen before uvicorn/SCM readiness so an ACL/path regression cannot become silent Pending
        # photo uploads on field devices.
        from services.object_storage import ensure_storage_ready
        photo_dir = ensure_storage_ready()
        if photo_dir:
            self.log.info("backend: photo storage ready at %s", photo_dir)

        # 3) Schema guard BEFORE uvicorn: service start never migrates an existing database (that is the
        # upgrade coordinator's separate `--migrate` step); only a brand-new empty database migrates here.
        # An out-of-date or newer-than-supported schema refuses to start with an actionable error.
        import schema_guard
        schema_guard.enforce(self.log)
        os.environ["ROOFSPAN_MIGRATIONS_PREAPPLIED"] = "1"

        from licensing import config as licensing_config
        self.log.info("backend: build identity version=%s build_sha=%s licensing_software_version=%s",
                      build_identity.VERSION, build_identity.BUILD_SHA, licensing_config.SOFTWARE_VERSION)

        # 4) Start the existing app. log_config=None prevents uvicorn from replacing the service's logging
        # configuration; use_colors=False keeps the no-console SCM path safe.
        config = uvicorn.Config("server:app", host="127.0.0.1", port=8001,
                                log_level="info", loop="asyncio", lifespan="on",
                                use_colors=False, log_config=None)
        self._server = uvicorn.Server(config)

        def _run():
            try:
                self.log.info("backend: uvicorn serving on 127.0.0.1:8001")
                self._server.run()
                if not getattr(self._server, "started", False) and self._error is None:
                    self._error = RuntimeError(
                        "FastAPI application/lifespan startup failed before uvicorn reported started")
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


def _offline_mode(mode: str) -> int:
    """--migrate / --schema-status: run as a separate observable process (own log + exit code + JSON)."""
    import json
    import logging

    import schema_guard
    args = sys.argv[1:]
    log_path = args[args.index("--log") + 1] if "--log" in args else None
    log = logging.getLogger("roofspan.migrate")
    log.setLevel(logging.INFO)
    handler = logging.FileHandler(log_path, encoding="utf-8") if log_path else logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    for name in ("roofspan.migrate", "alembic", "roofspan"):
        logging.getLogger(name).addHandler(handler)
    load_runtime_config()
    template = os.path.join(install_root(), "config-templates", "roofspan.env.template")
    try:
        if mode == "--migrate":
            config_reconcile.reconcile(config_path(), template, install_root(), log)
        db_bootstrap.bootstrap(log, template_path=template, config_path=config_path(),
                               identity_dir=os.environ["INSTALLATION_KEYS_DIR"])
        if mode == "--migrate":
            result = schema_guard.migrate(log)
            if build_identity.FAULT_INJECTION and os.environ.get("ROOFSPAN_UPGRADE_FAULT") == "migration":
                raise RuntimeError("injected migration failure (after schema changes were applied)")
        else:
            result = schema_guard.status()
    except Exception:
        log.exception("%s failed", mode)
        return 1
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


def main():
    if "--build-info" in sys.argv[1:]:
        build_identity.print_build_info("roofspan-backend")
        return
    for mode in ("--migrate", "--schema-status"):
        if mode in sys.argv[1:]:
            sys.exit(_offline_mode(mode))
    load_runtime_config()
    dispatch(make_service_class(SVC_NAME, SVC_DISPLAY, _worker_factory, LOG_FILE))


if __name__ == "__main__":
    main()
