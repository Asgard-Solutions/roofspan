"""Static + unit validation of the RoofSpan Relay Connector Windows service (runs in-container; no
Windows/WiX needed). Guards the separate-process architecture and the connector runtime bootstrap
(config-file loading, precedence, graceful missing-config, and outbound-only reconnect design).
"""
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # windows/
INSTALLER = os.path.join(HERE, "installer")
WINBUILD = os.path.join(HERE, "winbuild")

from winbuild import relay_entry as re_entry  # noqa: E402
from winbuild.targets import SERVICE_TARGETS, WINDOWS_SERVICES  # noqa: E402


def _read(p):
    with open(p) as f:
        return f.read()


@pytest.fixture
def clean_env():
    keys = ["ROOFSPAN_RELAY_WS_URL", "ROOFSPAN_LOCAL_API_URL", "ROOFSPAN_CONFIG_DIR",
            "ROOFSPAN_LOG_DIR", "INSTALLATION_KEYS_DIR"]
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---- runtime bootstrap (unit) ----

def test_load_env_file_parses_and_ignores_comments(tmp_path):
    p = tmp_path / "roofspan.env"
    p.write_text('# comment\n\nROOFSPAN_RELAY_WS_URL="wss://relay.roofspan.io/api/relay/tunnel"\n'
                 "ROOFSPAN_LOCAL_API_URL=http://127.0.0.1:8001\nBAD LINE NO EQUALS\n", encoding="utf-8")
    vals = re_entry.load_env_file(str(p))
    assert vals["ROOFSPAN_RELAY_WS_URL"] == "wss://relay.roofspan.io/api/relay/tunnel"
    assert vals["ROOFSPAN_LOCAL_API_URL"] == "http://127.0.0.1:8001"
    assert "BAD LINE NO EQUALS" not in vals


def test_load_env_file_missing_returns_empty():
    assert re_entry.load_env_file("/does/not/exist.env") == {}


def test_apply_env_service_env_wins_unless_override(clean_env):
    os.environ["ROOFSPAN_RELAY_WS_URL"] = "wss://set-by-service"
    re_entry.apply_env({"ROOFSPAN_RELAY_WS_URL": "wss://from-file"}, override=False)
    assert os.environ["ROOFSPAN_RELAY_WS_URL"] == "wss://set-by-service"
    re_entry.apply_env({"ROOFSPAN_RELAY_WS_URL": "wss://from-file"}, override=True)
    assert os.environ["ROOFSPAN_RELAY_WS_URL"] == "wss://from-file"


def test_resolve_config_loads_programdata_file(clean_env, tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "roofspan.env").write_text(
        "ROOFSPAN_RELAY_WS_URL=wss://relay.roofspan.io/api/relay/tunnel\n"
        "ROOFSPAN_LOCAL_API_URL=http://127.0.0.1:8001\n", encoding="utf-8")
    os.environ["ROOFSPAN_CONFIG_DIR"] = str(cfg_dir)
    os.environ["ROOFSPAN_LOG_DIR"] = str(tmp_path / "logs")
    cfg = re_entry.resolve_config()
    assert cfg["relay_ws_url"] == "wss://relay.roofspan.io/api/relay/tunnel"
    assert cfg["local_api_url"] == "http://127.0.0.1:8001"
    assert cfg["log_path"].endswith(os.path.join("logs", "relay-connector.log"))
    assert cfg["identity_dir"]  # defaulted


def test_resolve_config_explicit_env_overrides_file(clean_env, tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "roofspan.env").write_text("ROOFSPAN_RELAY_WS_URL=wss://from-file\n", encoding="utf-8")
    os.environ["ROOFSPAN_CONFIG_DIR"] = str(cfg_dir)
    os.environ["ROOFSPAN_RELAY_WS_URL"] = "wss://from-service-env"
    assert re_entry.resolve_config()["relay_ws_url"] == "wss://from-service-env"


def test_main_exits_gracefully_when_relay_url_missing(clean_env, tmp_path, monkeypatch):
    # empty config dir -> no relay url anywhere -> clear exit(2), NOT a KeyError tight-loop
    os.environ["ROOFSPAN_CONFIG_DIR"] = str(tmp_path / "config")
    os.environ["ROOFSPAN_LOG_DIR"] = str(tmp_path / "logs")
    with pytest.raises(SystemExit) as ei:
        re_entry.main()
    assert ei.value.code == 2


# ---- architecture (static) ----

def test_connector_is_separate_process_not_merged_into_fastapi():
    src = _read(os.path.join(WINBUILD, "relay_entry.py"))
    # The connector must NOT boot the FastAPI/uvicorn backend in-process.
    assert "uvicorn" not in src
    assert "server:app" not in src
    assert "InstallationTunnel" in src  # it runs the outbound tunnel


def test_connector_target_and_service_registered():
    assert SERVICE_TARGETS["roofspan-relay-connector"] == "relay_entry.py"
    assert "RoofSpanRelayConnector" in WINDOWS_SERVICES


def test_wix_connector_service_autostart_and_restart():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    m = re.search(r'Name="RoofSpanRelayConnector".*?</ServiceInstall>', wxs, re.S)
    assert m, "RoofSpanRelayConnector ServiceInstall not found"
    block = m.group(0)
    assert 'Start="auto"' in block                      # automatic startup
    assert 'Type="ownProcess"' in block                 # separate process
    assert 'Account="NT SERVICE\\RoofSpanRelay"' in block  # restricted, distinct account
    assert "FirstFailureActionType=\"restart\"" in block  # restart/recovery
    # install/stop/remove control + no inbound firewall exception anywhere
    assert 'Name="RoofSpanRelayConnector" Start="install" Stop="both" Remove="uninstall"' in wxs
    assert "FirewallException" not in wxs and "fire:" not in wxs


def test_env_template_has_outbound_relay_and_local_api():
    t = _read(os.path.join(WINBUILD, "config", "roofspan.env.template"))
    assert "ROOFSPAN_RELAY_WS_URL=" in t
    assert "ROOFSPAN_LOCAL_API_URL=http://127.0.0.1:8001" in t


def test_tunnel_client_is_outbound_with_bounded_reconnect():
    src = _read(os.path.join(os.path.dirname(HERE), "backend", "relay", "tunnel_client.py"))
    assert "websockets.connect(self.url" in src            # outbound WSS (client connects out)
    assert "max_backoff" in src and "backoff = min(max_backoff" in src  # bounded reconnect backoff
    assert "def stop" in src
    assert ".listen(" not in src and "bind(" not in src     # never opens an inbound socket
