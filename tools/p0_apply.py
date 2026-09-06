#!/usr/bin/env python3
"""Apply and verify the current RoofSpan P0 hardening increment.

Temporary implementation helper. The branch workflow runs this against a complete checkout, which lets
us make narrowly asserted replacements without rewriting unrelated large source files through the GitHub
contents API. It is removed before the pull request is merged.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one replacement, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def run(*cmd: str, cwd: str | None = None) -> None:
    subprocess.run(cmd, cwd=ROOT / cwd if cwd else ROOT, check=True)


def run_expected_failure(*cmd: str) -> None:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    print(proc.stdout)
    print(proc.stderr)
    if proc.returncode == 0:
        raise RuntimeError("Regression test unexpectedly passed before the P0-2 production change")


# ---------------------------------------------------------------------------
# RED: the release contract and real RelayWorker bootstrap must prove the
# loopback connector token reaches InstallationTunnel.outbox_token.
# ---------------------------------------------------------------------------
release_test = ROOT / "windows/tests/test_relay_connector_release_contract.py"
release_src = release_test.read_text(encoding="utf-8")
release_src += '''\n\ndef test_relay_worker_supplies_the_loopback_outbox_token():\n    source = _text(WINBUILD / "relay_entry.py")\n    assert 'data.get("connector_token")' in source\n    assert "outbox_token=connector_token" in source\n'''
release_test.write_text(release_src, encoding="utf-8")

write(
    "windows/tests/test_relay_connector_outbox_bootstrap.py",
    '''"""Runtime contract for the packaged RelayWorker outbox bootstrap."""\nfrom __future__ import annotations\n\nimport asyncio\nimport sys\nimport threading\nimport types\nfrom pathlib import Path\n\nimport pytest\n\nWINBUILD = Path(__file__).resolve().parents[1] / "winbuild"\nsys.path.insert(0, str(WINBUILD))\nsys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))\n\nimport relay_entry\n\n\nclass _Logger:\n    def info(self, *args, **kwargs):\n        pass\n\n    def warning(self, *args, **kwargs):\n        pass\n\n    def exception(self, *args, **kwargs):\n        pass\n\n\ndef test_connector_identity_requires_a_nonempty_outbox_token():\n    with pytest.raises(RuntimeError, match="incomplete"):\n        relay_entry.parse_connector_identity({\n            "installation_id": "11111111-1111-1111-1111-111111111111",\n            "relay_ws_url": "wss://relay.roofspan.io/api/relay/installation",\n        })\n\n\ndef test_real_relay_worker_passes_connector_token_to_installation_tunnel(monkeypatch):\n    constructed = []\n    ready = threading.Event()\n\n    class FakeResponse:\n        status_code = 200\n\n        @staticmethod\n        def json():\n            return {\n                "installation_id": "11111111-1111-1111-1111-111111111111",\n                "relay_ws_url": "wss://relay.roofspan.io/api/relay/installation",\n                "connector_token": "loopback-outbox-secret",\n            }\n\n    class FakeAsyncClient:\n        def __init__(self, *args, **kwargs):\n            pass\n\n        async def __aenter__(self):\n            return self\n\n        async def __aexit__(self, exc_type, exc, tb):\n            return False\n\n        async def get(self, url):\n            return FakeResponse()\n\n    class FakeTunnel:\n        def __init__(self, *args, **kwargs):\n            constructed.append((args, kwargs))\n            ready.set()\n\n        async def run(self):\n            await asyncio.Event().wait()\n\n        def stop(self):\n            pass\n\n    fake_httpx = types.ModuleType("httpx")\n    fake_httpx.AsyncClient = FakeAsyncClient\n    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)\n\n    import licensing\n    fake_identity = types.ModuleType("licensing.identity")\n    fake_identity.get_or_create_identity = lambda: (object(), "public")\n    monkeypatch.setitem(sys.modules, "licensing.identity", fake_identity)\n    monkeypatch.setattr(licensing, "identity", fake_identity, raising=False)\n\n    import relay\n    fake_tunnel_module = types.ModuleType("relay.tunnel_client")\n    fake_tunnel_module.InstallationTunnel = FakeTunnel\n    monkeypatch.setitem(sys.modules, "relay.tunnel_client", fake_tunnel_module)\n    monkeypatch.setattr(relay, "tunnel_client", fake_tunnel_module, raising=False)\n\n    worker = relay_entry.RelayWorker(_Logger())\n    worker.start()\n    try:\n        assert ready.wait(3), "RelayWorker never constructed InstallationTunnel"\n        assert constructed\n        _args, kwargs = constructed[0]\n        assert kwargs["outbox_token"] == "loopback-outbox-secret"\n    finally:\n        worker.stop()\n        worker.wait(3)\n''',
)

run_expected_failure(
    "pytest", "-q",
    "windows/tests/test_relay_connector_release_contract.py",
    "windows/tests/test_relay_connector_outbox_bootstrap.py",
)

# ---------------------------------------------------------------------------
# GREEN: validate the identity payload once, require the token, and pass it to
# the real InstallationTunnel construction path. The token is never logged.
# ---------------------------------------------------------------------------
identity_parser = '''\n\ndef parse_connector_identity(data: dict) -> tuple[str, str, str]:\n    """Validate the loopback identity response required by the packaged connector.\n\n    A connector without the durable loopback outbox token would look connected while silently skipping\n    Office-to-Field invalidations, so incomplete responses are rejected and retried by RelayWorker.\n    """\n    if not isinstance(data, dict):\n        raise RuntimeError("Office identity endpoint returned incomplete data")\n    installation_id = str(data.get("installation_id") or "").strip()\n    relay_ws_url = str(data.get("relay_ws_url") or "").strip()\n    connector_token = str(data.get("connector_token") or "").strip()\n    if not installation_id or not relay_ws_url or not connector_token:\n        raise RuntimeError("Office identity endpoint returned incomplete data")\n    if not relay_ws_url.endswith(INSTALLATION_RELAY_PATH):\n        raise RuntimeError("Office identity endpoint returned a non-canonical Relay route")\n    return installation_id, relay_ws_url, connector_token\n'''
replace_once(
    "windows/winbuild/relay_entry.py",
    "\n\nclass RelayWorker:",
    identity_parser + "\n\nclass RelayWorker:",
)
replace_once(
    "windows/winbuild/relay_entry.py",
    '''                        data = response.json()\n                        installation_id = str(data.get("installation_id") or "").strip()\n                        relay_ws_url = str(data.get("relay_ws_url") or "").strip()\n                        if not installation_id or not relay_ws_url:\n                            raise RuntimeError("Office identity endpoint returned incomplete data")\n                        if not relay_ws_url.endswith(INSTALLATION_RELAY_PATH):\n                            raise RuntimeError("Office identity endpoint returned a non-canonical Relay route")\n''',
    '''                        installation_id, relay_ws_url, connector_token = parse_connector_identity(\n                            response.json()\n                        )\n''',
)
replace_once(
    "windows/winbuild/relay_entry.py",
    '''                            private_key,\n                            local_api,\n                        )''',
    '''                            private_key,\n                            local_api,\n                            outbox_token=connector_token,\n                        )''',
)

run(
    "pytest", "-q",
    "windows/tests/test_relay_connector_release_contract.py",
    "windows/tests/test_relay_connector_outbox_bootstrap.py",
)
run("python", "-m", "py_compile", "windows/winbuild/relay_entry.py")

Path("/tmp/p0_commit_message").write_text(
    "fix: start relay connector outbox pump\n",
    encoding="utf-8",
)
