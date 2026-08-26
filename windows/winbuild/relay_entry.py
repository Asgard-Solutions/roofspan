r"""roofspan-relay-connector.exe - RoofSpanRelayConnector Windows service.

The service opens only an authenticated OUTBOUND WebSocket to RoofSpan Relay and forwards routed Mobile
requests to the local Office backend. It does not guess an installation id from the identity files. The
local Office backend verifies/migrates the Ed25519 public identity on the hosted Control Plane and returns
the non-secret hosted installation id through a loopback-only endpoint. Temporary Office, Control Plane,
Relay, DNS, or Internet outages are non-fatal: the Windows service stays running and retries with bounded
backoff.
"""
import json
import os
import sys
import threading

from roofspan_service import dispatch, load_runtime_config, make_service_class

SVC_NAME = "RoofSpanRelayConnector"
SVC_DISPLAY = "RoofSpan Relay Connector"
LOG_FILE = "relay-service.log"
RELAY_CONNECTOR_CONTRACT = "hosted-installation-identity-v2"
IDENTITY_ENDPOINT_PATH = "/api/relay/connector/identity"
INSTALLATION_RELAY_PATH = "/api/relay/installation"


def build_info() -> dict:
    """Machine-readable identity used by build/stage/install release gates."""
    return {
        "service": "roofspan-relay-connector",
        "build_sha": os.environ.get("ROOFSPAN_BUILD_SHA", "development"),
        "version": os.environ.get("ROOFSPAN_VERSION", "development"),
        "contract": RELAY_CONNECTOR_CONTRACT,
        "identity_endpoint": IDENTITY_ENDPOINT_PATH,
        "installation_relay_path": INSTALLATION_RELAY_PATH,
    }


class RelayWorker:
    def __init__(self, logger):
        self.log = logger
        self._loop = None
        self._task = None
        self._tunnel = None
        self._thread = None
        self._ready = threading.Event()
        self._error = None
        self._stopping = False

    def start(self, on_ready=None):
        def _run():
            import asyncio
            import httpx

            from licensing.identity import get_or_create_identity
            from relay.tunnel_client import InstallationTunnel

            local_api = os.environ.get(
                "ROOFSPAN_LOCAL_API_URL", "http://127.0.0.1:8001"
            ).rstrip("/")
            identity_url = f"{local_api}{IDENTITY_ENDPOINT_PATH}"
            private_key, _public_pem = get_or_create_identity()

            async def _connector_loop():
                backoff = 1.0
                while not self._stopping:
                    try:
                        async with httpx.AsyncClient(timeout=15) as client:
                            response = await client.get(identity_url)
                        if response.status_code != 200:
                            detail = f"HTTP {response.status_code}"
                            try:
                                body = response.json()
                                if isinstance(body, dict) and body.get("detail"):
                                    detail = str(body["detail"])[:160]
                            except Exception:
                                pass
                            raise RuntimeError(f"Office identity endpoint returned {detail}")

                        data = response.json()
                        installation_id = str(data.get("installation_id") or "").strip()
                        relay_ws_url = str(data.get("relay_ws_url") or "").strip()
                        if not installation_id or not relay_ws_url:
                            raise RuntimeError("Office identity endpoint returned incomplete data")
                        if not relay_ws_url.endswith(INSTALLATION_RELAY_PATH):
                            raise RuntimeError("Office identity endpoint returned a non-canonical Relay route")

                        self._tunnel = InstallationTunnel(
                            relay_ws_url,
                            installation_id,
                            private_key,
                            local_api,
                        )
                        self.log.info(
                            "relay: hosted installation identity ready; outbound tunnel -> %s "
                            "(build_sha=%s contract=%s)",
                            relay_ws_url,
                            build_info()["build_sha"],
                            RELAY_CONNECTOR_CONTRACT,
                        )
                        backoff = 1.0
                        await self._tunnel.run()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        if self._stopping:
                            break
                        self.log.warning(
                            "relay: identity/tunnel bootstrap unavailable: %s (retry in %ss)",
                            str(exc)[:200],
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        backoff = min(30.0, backoff * 2)

            try:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._task = self._loop.create_task(_connector_loop())
                # The bounded retry loop is active; the SCM service is healthy even when central
                # services are temporarily unavailable.
                self._ready.set()
                if on_ready:
                    on_ready()
                info = build_info()
                self.log.info(
                    "relay: outbound connector loop started (build_sha=%s version=%s contract=%s)",
                    info["build_sha"],
                    info["version"],
                    info["contract"],
                )
                self._loop.run_until_complete(self._task)
            except asyncio.CancelledError:
                self.log.info("relay: connector loop cancelled (stopping)")
            except Exception as exc:  # noqa: BLE001
                self._error = exc
                self.log.exception("relay: worker crashed")
                self._ready.set()
            finally:
                if self._loop is not None:
                    try:
                        self._loop.close()
                    except Exception:
                        pass

        self._thread = threading.Thread(target=_run, name="roofspan-relay", daemon=True)
        self._thread.start()

    def wait_ready(self, timeout):
        if not self._ready.wait(timeout):
            raise TimeoutError("relay worker did not initialize within timeout")
        if self._error is not None:
            raise self._error

    def stop(self):
        self._stopping = True
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
    if "--build-info" in sys.argv[1:]:
        print(json.dumps(build_info(), sort_keys=True))
        return
    load_runtime_config()
    dispatch(make_service_class(SVC_NAME, SVC_DISPLAY, _worker_factory, LOG_FILE))


if __name__ == "__main__":
    main()
