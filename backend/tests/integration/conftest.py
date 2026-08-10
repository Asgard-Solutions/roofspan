"""Fixtures for the REAL-Valkey relay integration suite.

Gated: nothing here runs during the fast unit run. It only runs when RELAY_RUN_INTEGRATION=1 is set
(the integration runner sets it) AND a real Valkey/Redis is reachable or a server binary is available.
No production credentials are used anywhere — only local/test values.

Valkey selection order:
  1. RELAY_VALKEY_URL (e.g. the docker-compose Valkey) if reachable.
  2. A session-managed local `valkey-server`/`redis-server` process on a free port (this container).
  3. Otherwise the whole suite is skipped.
"""
import os
import shutil
import socket
import subprocess
import time

import pytest

try:
    import redis  # redis-py; wire-compatible with Valkey
except Exception:  # noqa: BLE001
    redis = None


def _server_bin():
    return shutil.which("valkey-server") or shutil.which("redis-server")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_ping(url, timeout=10.0):
    if redis is None:
        return False
    r = redis.from_url(url)
    end = time.time() + timeout
    while time.time() < end:
        try:
            if r.ping():
                r.close()
                return True
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    try:
        r.close()
    except Exception:  # noqa: BLE001
        pass
    return False


class ManagedRedis:
    """A real Valkey/Redis server process this test controls (start/stop/restart) — for reconnect,
    TTL and node-death scenarios that require lifecycle control."""

    def __init__(self, port=None):
        self.port = port or _free_port()
        self.url = f"redis://127.0.0.1:{self.port}"
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen(
            [_server_bin(), "--port", str(self.port), "--save", "", "--appendonly", "no"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        assert _wait_ping(self.url, 10), f"managed valkey did not come up on {self.port}"

    def stop(self):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self.proc.kill()
            self.proc = None


def pytest_collection_modifyitems(config, items):
    """Skip the entire integration suite unless explicitly enabled and a Valkey is available."""
    if os.environ.get("RELAY_RUN_INTEGRATION") != "1":
        skip = pytest.mark.skip(reason="integration suite gated: set RELAY_RUN_INTEGRATION=1 to run")
        for item in items:
            if "integration" in item.nodeid:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def valkey_url():
    if redis is None:
        pytest.skip("redis-py not installed")
    ext = os.environ.get("RELAY_VALKEY_URL")
    if ext and _wait_ping(ext, 5):
        yield ext
        return
    if not _server_bin():
        pytest.skip("no external Valkey (RELAY_VALKEY_URL) and no valkey-server/redis-server binary")
    srv = ManagedRedis()
    srv.start()
    os.environ["RELAY_VALKEY_URL"] = srv.url  # so relay subprocesses inherit it
    try:
        yield srv.url
    finally:
        srv.stop()


@pytest.fixture()
def flush_valkey(valkey_url):
    r = redis.from_url(valkey_url)
    r.flushdb()
    yield
    try:
        r.flushdb()
        r.close()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture()
def managed_valkey():
    """A dedicated, restartable Valkey for reconnect/TTL/node-death tests."""
    if not _server_bin():
        pytest.skip("no valkey-server/redis-server binary for managed lifecycle test")
    srv = ManagedRedis()
    srv.start()
    try:
        yield srv
    finally:
        srv.stop()
