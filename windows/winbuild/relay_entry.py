"""PyInstaller entry: roofspan-relay-connector.exe — outbound-only Secure Relay tunnel Windows service.

SEPARATE Windows service (RoofSpanRelayConnector), independent of the RoofSpanBackend service. When the
packaged exe is started by the Windows SCM it runs as a real service (see winservice: it connects via
StartServiceCtrlDispatcher and reports RUNNING/STOP correctly). Outside a frozen build it runs in the
foreground (dev/debug). The connector loads the installation identity and opens an authenticated
OUTBOUND WebSocket to the RoofSpan Secure Relay, forwarding routed Mobile requests to the LOCAL backend
on 127.0.0.1. No inbound ports. If the relay/cloud is unavailable it reconnects (bounded backoff) and the
local Office backend (a separate process) is entirely unaffected. Native SCM execution HUMAN REQUIRED.

Runtime bootstrap (a Windows service does NOT auto-load a .env):
  * loads C:\\ProgramData\\RoofSpan\\config\\roofspan.env (KEY=VALUE, no secrets) WITHOUT overriding
    values already set in the service/machine environment,
  * configures rotating file logging under C:\\ProgramData\\RoofSpan\\logs\\relay-connector.log,
  * resolves the relay + local API URLs and the installation identity dir.
"""
import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

DEFAULT_DATA_ROOT = r"C:\ProgramData\RoofSpan"
DEFAULT_CONFIG_DIR = os.path.join(DEFAULT_DATA_ROOT, "config")
DEFAULT_LOG_DIR = os.path.join(DEFAULT_DATA_ROOT, "logs")
DEFAULT_IDENTITY_DIR = os.path.join(DEFAULT_DATA_ROOT, "identity")
DEFAULT_LOCAL_API_URL = "http://127.0.0.1:8001"
ENV_FILENAME = "roofspan.env"

# Windows service identity — MUST match installer/RoofSpan.wxs ServiceInstall Name.
SVC_NAME = "RoofSpanRelayConnector"
SVC_DISPLAY = "RoofSpan Relay Connector"
SVC_DESC = "Outbound-only Secure Relay tunnel (no inbound ports)."

log = logging.getLogger("roofspan.relay.connector")


def load_env_file(path: str) -> dict:
    """Parse a simple KEY=VALUE env file (comments with '#', blank lines ignored). No external dep."""
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
    for k, v in values.items():
        if override or k not in os.environ:
            os.environ[k] = v


def resolve_config() -> dict:
    """Resolve connector runtime config, loading the ProgramData env file first (env vars win)."""
    config_dir = os.environ.get("ROOFSPAN_CONFIG_DIR", DEFAULT_CONFIG_DIR)
    apply_env(load_env_file(os.path.join(config_dir, ENV_FILENAME)), override=False)
    os.environ.setdefault("INSTALLATION_KEYS_DIR", DEFAULT_IDENTITY_DIR)
    log_dir = os.environ.get("ROOFSPAN_LOG_DIR", DEFAULT_LOG_DIR)
    return {
        "relay_ws_url": os.environ.get("ROOFSPAN_RELAY_WS_URL"),
        "local_api_url": os.environ.get("ROOFSPAN_LOCAL_API_URL", DEFAULT_LOCAL_API_URL),
        "identity_dir": os.environ["INSTALLATION_KEYS_DIR"],
        "log_path": os.path.join(log_dir, "relay-connector.log"),
    }


def setup_logging(log_path: str) -> None:
    root = logging.getLogger("roofspan")
    if root.handlers:  # avoid duplicate handlers if called twice (console + service)
        return
    root.setLevel(logging.INFO)
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        handlers.append(RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"))
    except OSError as e:  # logging must never crash the service
        root.warning("relay-connector: file logging unavailable (%s); using console only", e)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)


def build_tunnel(cfg: dict):
    """Build the outbound InstallationTunnel from resolved config (heavy imports are lazy)."""
    from licensing.identity import get_or_create_identity
    from relay.tunnel_client import InstallationTunnel

    private_key, installation_id = get_or_create_identity()
    log.info("RoofSpan Relay Connector (outbound-only) installation=%s relay=%s local=%s",
             installation_id, cfg["relay_ws_url"], cfg["local_api_url"])
    return InstallationTunnel(cfg["relay_ws_url"], installation_id, private_key, cfg["local_api_url"])


def _prepare_or_exit() -> dict:
    """Resolve config + logging; exit(2) with a clear log if the relay URL is missing (no tight loop:
    SCM applies the 15s restart delay; console exits)."""
    cfg = resolve_config()
    setup_logging(cfg["log_path"])
    if not cfg["relay_ws_url"]:
        log.error("ROOFSPAN_RELAY_WS_URL is not configured (checked env + %s\\%s). The connector cannot "
                  "start until it is set. The local RoofSpan Office backend is unaffected.",
                  os.environ.get("ROOFSPAN_CONFIG_DIR", DEFAULT_CONFIG_DIR), ENV_FILENAME)
        raise SystemExit(2)
    return cfg


def build_runner():
    """Factory for the Windows service: returns an AsyncServiceRunner driving the tunnel with clean stop."""
    from winbuild import winservice  # local import so tests/PyInstaller resolve it via the package path
    cfg = _prepare_or_exit()
    tunnel = build_tunnel(cfg)
    return winservice.AsyncServiceRunner(lambda: tunnel.run(), on_stop=tunnel.stop)


def run_console() -> None:
    """Foreground run for development/debugging (no SCM)."""
    cfg = _prepare_or_exit()
    tunnel = build_tunnel(cfg)
    log.info("RoofSpan Relay Connector running in console mode (dev)")
    try:
        asyncio.run(tunnel.run())
    except KeyboardInterrupt:
        tunnel.stop()
        log.info("RoofSpan Relay Connector stopping")


def main() -> None:
    if getattr(sys, "frozen", False):
        # Packaged service exe -> integrate with the Windows SCM (or handle install/start/stop verbs).
        try:
            from winbuild import winservice
        except ImportError:
            import winservice  # PyInstaller flat layout fallback
        svc = winservice.build_service_class(SVC_NAME, SVC_DISPLAY, SVC_DESC, build_runner)
        winservice.dispatch(svc)
    else:
        run_console()


if __name__ == "__main__":
    main()
