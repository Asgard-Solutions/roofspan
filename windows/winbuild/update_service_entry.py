r"""roofspan-update-service.exe - RoofSpanUpdateService Windows service (signed-update checker).

Real SCM service. Stays alive continuously and checks the signed CloudFront update manifest on its
existing 12h cadence. Network errors, a missing manifest, or an unavailable CloudFront endpoint are
RECOVERABLE: they are logged and retried later - they never terminate the Windows service. The update
verification PUBLIC key path is install-owned (ROOFSPAN_UPDATE_PUBLIC_KEY); no user-shell env var.
"""
import os
import sys
import threading

import build_identity
from roofspan_service import dispatch, load_runtime_config, make_service_class
from updater.manifest import parse_manifest
from updater.service import CHECK_INTERVAL_SECONDS, plan_update

SVC_NAME = "RoofSpanUpdateService"
SVC_DISPLAY = "RoofSpan Update Service"
LOG_FILE = "update-service.log"
SVC_NAME_ID = "roofspan-update-service"
ACTIVE_STATES = ("UPDATE_AVAILABLE", "DOWNLOADING", "DOWNLOAD_PAUSED", "DOWNLOADED", "VERIFYING", "SCHEDULED")


def _current_version() -> str:
    return build_identity.VERSION


def _public_pem() -> str:
    with open(os.environ["ROOFSPAN_UPDATE_PUBLIC_KEY"], "r") as f:
        return f.read()


def tick_once(logger) -> str:
    """Signed-update state machine (download + verify + schedule) when the install-owned trust policy is valid;
    otherwise the legacy check-and-log behavior. Installation itself only ever happens in RoofSpanUpdateBroker."""
    from updater.autoupdate import Checker
    from updater.winupdate import WinUpdateOps, load_trust
    policy, auto, reason = load_trust()
    if policy is None:
        logger.info("update: automatic download/install disabled (%s); check only", reason)
        return check_once(logger)
    return Checker(WinUpdateOps(), policy, _current_version(), os.environ.get("ROOFSPAN_DATA_ROOT", r"C:\ProgramData\RoofSpan"),
                   logger, auto).tick()


def check_once(logger) -> str:
    import httpx

    url = os.environ.get("ROOFSPAN_WINDOWS_UPDATE_MANIFEST_URL",
                         "https://downloads.roofspan.io/update/windows/latest.json")
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    manifest = parse_manifest(resp.text)
    decision = plan_update(_current_version(), manifest, _public_pem())
    logger.info("update check: %s (manifest %s)", decision, manifest.version)
    return decision


class UpdateWorker:
    def __init__(self, logger):
        self.log = logger
        self._stop = threading.Event()
        self._thread = None
        self._ready = threading.Event()

    def start(self, on_ready=None):
        def _run():
            self._ready.set()
            if on_ready:
                on_ready()
            self.log.info("update: checker started (interval %ss) current_version=%s build_sha=%s",
                          CHECK_INTERVAL_SECONDS, _current_version(), build_identity.BUILD_SHA)
            while not self._stop.is_set():
                state = "IDLE"
                try:
                    state = tick_once(self.log)
                except Exception as e:  # noqa: BLE001  - all update-check failures are recoverable
                    self.log.warning("update check failed (will retry): %s", type(e).__name__)
                # Active download/verify/schedule states are polled every minute; otherwise the 12h cadence.
                # Interruptible wait so SCM stop is prompt.
                self._stop.wait(60 if state in ACTIVE_STATES else CHECK_INTERVAL_SECONDS)

        self._thread = threading.Thread(target=_run, name="roofspan-update", daemon=True)
        self._thread.start()

    def wait_ready(self, timeout):
        if not self._ready.wait(timeout):
            raise TimeoutError("update worker did not initialize within timeout")

    def stop(self):
        self._stop.set()

    def wait(self, timeout=10):
        if self._thread is not None:
            self._thread.join(timeout)


def _worker_factory(logger):
    return UpdateWorker(logger)


def main():
    if "--build-info" in sys.argv[1:]:
        build_identity.print_build_info(SVC_NAME_ID)
        return
    load_runtime_config()
    dispatch(make_service_class(SVC_NAME, SVC_DISPLAY, _worker_factory, LOG_FILE))


if __name__ == "__main__":
    main()
