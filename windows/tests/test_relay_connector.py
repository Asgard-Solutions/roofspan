"""Static + unit validation of the RoofSpan Relay Connector Windows service (runs in-container; no
Windows/WiX/pywin32 needed). Guards the separate-process architecture, the SCM service-host structure,
the async lifecycle stop, the connector runtime bootstrap, and the ProgramData service-account ACLs.
"""
import asyncio
import os
import re
import threading
import time

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # windows/
INSTALLER = os.path.join(HERE, "installer")
WINBUILD = os.path.join(HERE, "winbuild")

from winbuild import relay_entry as re_entry  # noqa: E402
from winbuild import winservice  # noqa: E402
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
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


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
    cfg_dir = tmp_path / "config"; cfg_dir.mkdir()
    (cfg_dir / "roofspan.env").write_text(
        "ROOFSPAN_RELAY_WS_URL=wss://relay.roofspan.io/api/relay/tunnel\n"
        "ROOFSPAN_LOCAL_API_URL=http://127.0.0.1:8001\n", encoding="utf-8")
    os.environ["ROOFSPAN_CONFIG_DIR"] = str(cfg_dir)
    os.environ["ROOFSPAN_LOG_DIR"] = str(tmp_path / "logs")
    cfg = re_entry.resolve_config()
    assert cfg["relay_ws_url"] == "wss://relay.roofspan.io/api/relay/tunnel"
    assert cfg["local_api_url"] == "http://127.0.0.1:8001"
    assert cfg["log_path"].endswith(os.path.join("logs", "relay-connector.log"))
    assert cfg["identity_dir"]


def test_resolve_config_explicit_env_overrides_file(clean_env, tmp_path):
    cfg_dir = tmp_path / "config"; cfg_dir.mkdir()
    (cfg_dir / "roofspan.env").write_text("ROOFSPAN_RELAY_WS_URL=wss://from-file\n", encoding="utf-8")
    os.environ["ROOFSPAN_CONFIG_DIR"] = str(cfg_dir)
    os.environ["ROOFSPAN_RELAY_WS_URL"] = "wss://from-service-env"
    assert re_entry.resolve_config()["relay_ws_url"] == "wss://from-service-env"


def test_prepare_exits_gracefully_when_relay_url_missing(clean_env, tmp_path):
    os.environ["ROOFSPAN_CONFIG_DIR"] = str(tmp_path / "config")
    os.environ["ROOFSPAN_LOG_DIR"] = str(tmp_path / "logs")
    with pytest.raises(SystemExit) as ei:
        re_entry._prepare_or_exit()
    assert ei.value.code == 2


# ---- SCM async lifecycle (unit; OS-independent) ----

def test_async_runner_runs_and_stops_cleanly_with_on_stop():
    stopped = {"tunnel": False}

    async def _loop():
        while True:
            await asyncio.sleep(0.05)

    runner = winservice.AsyncServiceRunner(_loop, on_stop=lambda: stopped.__setitem__("tunnel", True))
    t = threading.Thread(target=runner.run)
    t.start()
    time.sleep(0.2)
    runner.stop()          # simulates SCM SvcStop from the control thread
    t.join(timeout=5)
    assert not t.is_alive(), "service runner did not stop on stop()"
    assert stopped["tunnel"] is True, "on_stop (tunnel.stop) was not invoked"


# ---- architecture (static) ----

def test_connector_is_separate_process_not_merged_into_fastapi():
    src = _read(os.path.join(WINBUILD, "relay_entry.py"))
    assert "uvicorn" not in src and "server:app" not in src
    assert "InstallationTunnel" in src


def test_connector_uses_scm_service_host():
    # relay_entry dispatches to the pywin32 SCM host when frozen; svc name matches WiX.
    src = _read(os.path.join(WINBUILD, "relay_entry.py"))
    assert 'SVC_NAME = "RoofSpanRelayConnector"' in src
    assert "winservice.build_service_class" in src and "winservice.dispatch" in src
    assert 'getattr(sys, "frozen"' in src
    host = _read(os.path.join(WINBUILD, "winservice.py"))
    assert "StartServiceCtrlDispatcher" in host      # real SCM contract
    assert "ServiceFramework" in host
    assert "SvcStop" in host and "SvcDoRun" in host
    assert "_svc_name_ = svc_name" in host           # bound to the WiX name


def test_connector_target_and_service_registered():
    assert SERVICE_TARGETS["roofspan-relay-connector"] == "relay_entry.py"
    assert "RoofSpanRelayConnector" in WINDOWS_SERVICES


def test_relay_spec_bundles_pywin32_service_host():
    spec = _read(os.path.join(WINBUILD, "roofspan-relay-connector.spec"))
    for mod in ("win32serviceutil", "servicemanager", "win32service", "winbuild.winservice"):
        assert mod in spec, f"spec missing hiddenimport {mod}"


def test_wix_connector_service_autostart_and_restart():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    m = re.search(r'Name="RoofSpanRelayConnector".*?</ServiceInstall>', wxs, re.S)
    assert m, "RoofSpanRelayConnector ServiceInstall not found"
    block = m.group(0)
    assert 'Start="auto"' in block
    assert 'Type="ownProcess"' in block
    assert 'Account="NT SERVICE\\RoofSpanRelayConnector"' in block  # virtual account matches service Name
    assert 'FirstFailureActionType="restart"' in block
    assert 'Name="RoofSpanRelayConnector" Start="install" Stop="both" Remove="uninstall"' in wxs
    assert "FirewallException" not in wxs and "fire:" not in wxs  # no inbound firewall rule


def test_wix_grants_service_account_acls_for_programdata():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    # connector account must be able to read config, read/write identity, write logs
    assert re.search(r'Id="AclConfig".*?RoofSpanRelay.*?GenericRead="yes"', wxs, re.S)
    assert re.search(r'Id="AclIdentity".*?RoofSpanRelay.*?GenericWrite="yes"', wxs, re.S)
    assert re.search(r'Id="AclLogs".*?RoofSpanRelay.*?GenericWrite="yes"', wxs, re.S)
    assert 'Domain="NT SERVICE"' in wxs
    assert '<ComponentGroupRef Id="DataAcls" />' in wxs  # wired into the feature


def test_env_template_has_outbound_relay_and_local_api():
    t = _read(os.path.join(WINBUILD, "config", "roofspan.env.template"))
    assert "ROOFSPAN_RELAY_WS_URL=" in t
    assert "ROOFSPAN_LOCAL_API_URL=http://127.0.0.1:8001" in t


def test_tunnel_client_is_outbound_with_bounded_reconnect():
    src = _read(os.path.join(os.path.dirname(HERE), "backend", "relay", "tunnel_client.py"))
    assert "websockets.connect(self.url" in src
    assert "max_backoff" in src and "backoff = min(max_backoff" in src
    assert "def stop" in src
    assert ".listen(" not in src and "bind(" not in src
