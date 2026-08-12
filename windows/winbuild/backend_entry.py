"""PyInstaller entry: roofspan-backend.exe — local RoofSpan Office API + Office UI Windows service.

Runs as a real Windows SCM service (RoofSpanBackend) when frozen, else in the foreground (dev). Serves
FastAPI/uvicorn bound to 127.0.0.1:8001 ONLY (never public) and the packaged production frontend from the
`frontend` folder next to this exe. A Windows STOP triggers a graceful uvicorn shutdown (FastAPI shutdown
lifecycle → PostgreSQL engine + relay-hub cleanup run as designed). Native SCM execution HUMAN REQUIRED.

Only the changes needed for the service to start with correct local paths are made here; the full
production-config cleanup is P1-4.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

DEFAULT_DATA_ROOT = r"C:\ProgramData\RoofSpan"
DEFAULT_LOG_DIR = os.path.join(DEFAULT_DATA_ROOT, "logs")
DEFAULT_IDENTITY_DIR = os.path.join(DEFAULT_DATA_ROOT, "identity")
BIND_HOST = "127.0.0.1"   # never bind publicly by default
BIND_PORT = 8001

SVC_NAME = "RoofSpanBackend"          # MUST match installer/RoofSpan.wxs
SVC_DISPLAY = "RoofSpan Backend"
SVC_DESC = "RoofSpan local API + local browser UI (binds 127.0.0.1 only)."

log = logging.getLogger("roofspan.backend.service")


def _install_root() -> str:
    exe_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    return os.path.dirname(exe_dir)  # -> <INSTALLFOLDER>


def prepare_runtime() -> None:
    """Load ProgramData config + set local runtime paths + rotating logs (idempotent)."""
    from winbuild import winservice
    winservice.load_programdata_env()
    root = _install_root()
    os.environ.setdefault("ROOFSPAN_STATIC_DIR", os.path.join(root, "frontend"))
    os.environ.setdefault("INSTALLATION_KEYS_DIR", DEFAULT_IDENTITY_DIR)
    _setup_logging(os.path.join(os.environ.get("ROOFSPAN_LOG_DIR", DEFAULT_LOG_DIR), "backend.log"))


def _setup_logging(log_path: str) -> None:
    root = logging.getLogger("roofspan")
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        handlers.append(RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"))
    except OSError as e:
        root.warning("backend: file logging unavailable (%s); console only", e)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)


def build_runner():
    """Windows service runner: uvicorn Server driven so a STOP sets should_exit -> graceful shutdown."""
    from winbuild import winservice
    prepare_runtime()
    import uvicorn

    state = {"server": None}

    async def _serve():
        config = uvicorn.Config("server:app", host=BIND_HOST, port=BIND_PORT, log_level="info")
        server = uvicorn.Server(config)
        state["server"] = server
        await server.serve()  # returns when should_exit is set (runs FastAPI shutdown lifecycle)

    def _on_stop():
        srv = state["server"]
        if srv is not None:
            srv.should_exit = True  # graceful uvicorn shutdown (same flag uvicorn's own signal handler sets)

    return winservice.AsyncServiceRunner(_serve, on_stop=_on_stop, graceful_stop=True)


def run_foreground() -> None:
    """Dev/non-frozen: run uvicorn directly (unchanged local behavior)."""
    prepare_runtime()
    import uvicorn
    uvicorn.run("server:app", host=BIND_HOST, port=BIND_PORT, log_level="info")


def main() -> None:
    if getattr(sys, "frozen", False):
        try:
            from winbuild import winservice
        except ImportError:
            import winservice  # PyInstaller flat-layout fallback
        svc = winservice.build_service_class(SVC_NAME, SVC_DISPLAY, SVC_DESC, build_runner)
        winservice.dispatch(svc)
    else:
        run_foreground()


if __name__ == "__main__":
    main()
