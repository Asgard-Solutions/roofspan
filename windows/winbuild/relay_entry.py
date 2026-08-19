r"""roofspan-relay-connector.exe - RoofSpanRelayConnector Windows service (outbound-only Secure Relay).

Real SCM service. Opens ONLY the existing authenticated OUTBOUND relay WebSocket (never an inbound port)
and forwards routed Mobile requests to the local backend. Depends on RoofSpanBackend (SCM ordering). The
relay endpoint comes from installed config / an app-owned production default (ROOFSPAN_RELAY_WS_URL) - it
NEVER requires a user-shell environment variable. Temporary relay/Internet outages are non-fatal: the
tunnel reconnects with bounded backoff and the Windows service stays RUNNING.
"""
import os
import threading

from roofspan_service import dispatch, load_runtime_config, make_service_class

SVC_NAME = "RoofSpanRelayConnector"
SVC_DISPLAY = "RoofSpan Relay Connector"
LOG_FILE = "relay-service.log"


class RelayWorker:
    def __init__(self, logger):
        self.log = logger
        self._loop = None
        self._task = None
        self._tunnel = None
        self._thread = None
        self._ready = threading.Event()
        self._error = None

    def start(self, on_ready=None):
        def _run():
            import asyncio

            from licensing.identity import get_or_create_identity
            from relay.tunnel_client import InstallationTunnel
            try:
                private_key, installation_id = get_or_create_identity()
                url = os.environ.get("ROOFSPAN_RELAY_WS_URL", "wss://relay.roofspan.io/api/relay/tunnel")
                local = os.environ.get("ROOFSPAN_LOCAL_API_URL", "http://127.0.0.1:8001")
                self._tunnel = InstallationTunnel(url, installation_id, private_key, local)
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._task = self._loop.create_task(self._tunnel.run())
                # The reconnect loop is now active; the SERVICE is running even if the relay is
                # momentarily unreachable (it will keep retrying with backoff).
                self._ready.set()
                if on_ready:
                    on_ready()
                self.log.info("relay: outbound tunnel loop started -> %s", url)
                self._loop.run_until_complete(self._task)
            except asyncio.CancelledError:
                self.log.info("relay: tunnel loop cancelled (stopping)")
            except Exception as e:  # noqa: BLE001
                self._error = e
                self.log.exception("relay: worker crashed")
                self._ready.set()

        self._thread = threading.Thread(target=_run, name="roofspan-relay", daemon=True)
        self._thread.start()

    def wait_ready(self, timeout):
        if not self._ready.wait(timeout):
            raise TimeoutError("relay worker did not initialize within timeout")
        if self._error is not None:
            raise self._error

    def stop(self):
        if self._tunnel is not None:
            self._tunnel.stop()
        if self._loop is not None and self._task is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)

    def wait(self, timeout=20):
        if self._thread is not None:
            self._thread.join(timeout)


def _worker_factory(logger):
    return RelayWorker(logger)


def main():
    load_runtime_config()
    dispatch(make_service_class(SVC_NAME, SVC_DISPLAY, _worker_factory, LOG_FILE))


if __name__ == "__main__":
    main()
