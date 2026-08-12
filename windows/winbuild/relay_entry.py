"""PyInstaller entry: roofspan-relay-connector.exe — outbound-only Secure Relay tunnel.

SEPARATE Windows service (RoofSpanRelayConnector), independent of the RoofSpanBackend service. Loads
the installation identity created by the licensing flow and opens an authenticated OUTBOUND WebSocket
to the RoofSpan Secure Relay, forwarding routed Mobile requests to the LOCAL backend on 127.0.0.1.
No inbound ports. If the relay/cloud is unavailable the connector simply reconnects (bounded backoff)
and the local Office backend is entirely unaffected. Native Windows service execution HUMAN REQUIRED.

Runtime bootstrap (a Windows service does NOT auto-load a .env file):
  * loads C:\\ProgramData\\RoofSpan\\config\\roofspan.env (KEY=VALUE, no secrets) into the environment
    WITHOUT overriding values already set in the service/machine environment,
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

log = logging.getLogger("roofspan.relay.connector")


def load_env_file(path: str) -> dict:
    """Parse a simple KEY=VALUE env file (comments with '#', blank lines ignored). No external dep."""
    values: dict[str, str] = {}
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


def main() -> None:
    cfg = resolve_config()
    setup_logging(cfg["log_path"])
    if not cfg["relay_ws_url"]:
        # Do NOT raise a bare KeyError (that tight-loops under the service restart policy). Log a clear,
        # actionable message and exit non-zero so the failure is visible in the service log.
        log.error("ROOFSPAN_RELAY_WS_URL is not configured (checked env + %s\\%s). "
                  "The connector cannot start until it is set. The local RoofSpan Office backend is "
                  "unaffected.", os.environ.get("ROOFSPAN_CONFIG_DIR", DEFAULT_CONFIG_DIR), ENV_FILENAME)
        sys.exit(2)

    from licensing.identity import get_or_create_identity
    from relay.tunnel_client import InstallationTunnel

    private_key, installation_id = get_or_create_identity()
    log.info("RoofSpan Relay Connector starting (outbound-only) installation=%s relay=%s local=%s",
             installation_id, cfg["relay_ws_url"], cfg["local_api_url"])
    tunnel = InstallationTunnel(cfg["relay_ws_url"], installation_id, private_key, cfg["local_api_url"])
    try:
        asyncio.run(tunnel.run())
    except KeyboardInterrupt:
        log.info("RoofSpan Relay Connector stopping")


if __name__ == "__main__":
    main()
