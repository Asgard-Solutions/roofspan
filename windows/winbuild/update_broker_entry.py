r"""roofspan-update-broker.exe - RoofSpanUpdateBroker (LocalSystem, demand-start, outbound network blocked).

Started by RoofSpanUpdateService only when a request is ready. It processes AT MOST one request from the fixed,
ACL-protected request location, re-verifies everything itself (updater.autoupdate.Broker), runs the verified
RoofSpanSetup.exe with fixed arguments (which uses the existing roofspan-upgrade.exe transaction), reconciles the
result with the coordinator's evidence, then stops itself.
"""
import sys
import threading

import build_identity
from roofspan_service import dispatch, make_service_class

SVC_NAME = "RoofSpanUpdateBroker"
SVC_DISPLAY = "RoofSpan Update Broker"
LOG_FILE = "update-broker.log"


def run_once(logger) -> str:
    """Fixed roots only: nothing (environment, config file, request) can redirect the broker's paths."""
    import os

    from updater.autoupdate import Broker
    from updater.states import exclusive_lock
    from updater.winupdate import DATA_ROOT, INSTALL_ROOT, WinUpdateOps, load_trust
    policy, auto, reason = load_trust(INSTALL_ROOT)
    if policy is None:
        logger.warning("update broker: refusing all requests (%s)", reason)
        return "BLOCKED"
    with exclusive_lock(os.path.join(DATA_ROOT, "update", "state", "broker.lock")):  # one broker run at a time
        ops = WinUpdateOps(DATA_ROOT, INSTALL_ROOT)
        state = Broker(ops, policy, build_identity.VERSION, DATA_ROOT, logger, auto).run()
    logger.info("update broker: finished in state %s", state)
    return state


class BrokerWorker:
    def __init__(self, logger):
        self.log, self._done, self._thread = logger, threading.Event(), None

    def start(self, on_ready=None):
        def _run():
            try:
                run_once(self.log)
            except Exception as e:  # noqa: BLE001
                self.log.error("update broker: unexpected %s", type(e).__name__)
            finally:
                self._done.set()
                import win32serviceutil
                win32serviceutil.StopService(SVC_NAME)  # demand-start: stop once the request is handled
        self._thread = threading.Thread(target=_run, name="roofspan-update-broker", daemon=True)
        self._thread.start()

    def wait_ready(self, timeout):
        return True

    def stop(self):
        pass

    def wait(self, timeout=30):
        self._done.wait(timeout)


def main():
    if "--build-info" in sys.argv[1:]:
        build_identity.print_build_info("roofspan-update-broker")
        return
    build_identity.enforce()  # no roofspan.env: the broker takes no configuration from writable locations
    dispatch(make_service_class(SVC_NAME, SVC_DISPLAY, lambda log: BrokerWorker(log), LOG_FILE))


if __name__ == "__main__":
    main()
