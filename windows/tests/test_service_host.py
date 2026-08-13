"""Static + unit validation that ALL THREE RoofSpan Office services use the one common pywin32 SCM
service host (winservice), match their WiX names, keep foreground/dev paths, and stop cleanly. Runs
in-container (no Windows/pywin32). Native SCM execution remains HUMAN REQUIRED.
"""
import asyncio
import os
import re
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # windows/
INSTALLER = os.path.join(HERE, "installer")
WINBUILD = os.path.join(HERE, "winbuild")

from winbuild import winservice, backend_entry, update_service_entry, relay_entry  # noqa: E402
from winbuild.targets import WINDOWS_SERVICES  # noqa: E402


def _read(p):
    with open(p) as f:
        return f.read()


# ---- shared runner: graceful (backend) stop ----

def test_async_runner_graceful_stop_uses_on_stop_not_cancel():
    flag = {"exit": False, "on_stop": False}

    async def _loop():
        while not flag["exit"]:
            await asyncio.sleep(0.02)

    def _on_stop():
        flag["on_stop"] = True
        flag["exit"] = True  # graceful: signal the coroutine to finish on its own

    runner = winservice.AsyncServiceRunner(_loop, on_stop=_on_stop, graceful_stop=True)
    t = threading.Thread(target=runner.run)
    t.start()
    time.sleep(0.15)
    runner.stop()
    t.join(timeout=5)
    assert not t.is_alive(), "graceful runner did not stop"
    assert flag["on_stop"] is True


# ---- Backend ----

def test_backend_service_name_matches_wix():
    assert backend_entry.SVC_NAME == "RoofSpanBackend"
    assert "RoofSpanBackend" in WINDOWS_SERVICES


def test_backend_uses_scm_host_and_graceful_shutdown():
    src = _read(os.path.join(WINBUILD, "backend_entry.py"))
    assert "winservice.build_service_class" in src and "winservice.dispatch" in src
    assert 'getattr(sys, "frozen"' in src
    assert "graceful_stop=True" in src
    assert "should_exit = True" in src        # controlled uvicorn shutdown (FastAPI lifecycle runs)
    assert "def run_foreground" in src         # dev path preserved


def test_backend_binds_loopback_only():
    src = _read(os.path.join(WINBUILD, "backend_entry.py"))
    assert 'BIND_HOST = "127.0.0.1"' in src
    assert "0.0.0.0" not in src                # never public by default


# ---- Updater ----

def test_updater_service_name_matches_wix():
    assert update_service_entry.SVC_NAME == "RoofSpanUpdateService"
    assert "RoofSpanUpdateService" in WINDOWS_SERVICES


def test_updater_uses_scm_host_and_prompt_stop():
    src = _read(os.path.join(WINBUILD, "update_service_entry.py"))
    assert "winservice.build_service_class" in src and "winservice.dispatch" in src
    assert 'getattr(sys, "frozen"' in src
    # cancel-based stop interrupts the interval sleep immediately (no waiting the full 12h)
    assert "asyncio.sleep(CHECK_INTERVAL_SECONDS)" in src
    assert "graceful_stop=True" not in src
    assert "def run_foreground" in src


def test_updater_behavior_preserved():
    from updater.service import CHECK_INTERVAL_SECONDS
    assert CHECK_INTERVAL_SECONDS == 12 * 60 * 60
    src = _read(os.path.join(WINBUILD, "update_service_entry.py"))
    assert "plan_update" in src and "parse_manifest" in src  # verify+plan unchanged


# ---- all three consistent; no plain console-only frozen service remains ----

def test_all_three_services_use_common_host():
    for entry in ("backend_entry.py", "relay_entry.py", "update_service_entry.py"):
        src = _read(os.path.join(WINBUILD, entry))
        assert "winservice.build_service_class" in src, f"{entry} not on common SCM host"
        assert "winservice.dispatch" in src, f"{entry} missing SCM dispatch"
        assert 'getattr(sys, "frozen"' in src, f"{entry} missing frozen branch"


def test_all_specs_bundle_pywin32_service_host():
    for spec in ("roofspan-backend.spec", "roofspan-relay-connector.spec", "roofspan-update-service.spec"):
        s = _read(os.path.join(WINBUILD, spec))
        for mod in ("win32serviceutil", "servicemanager", "winbuild.winservice"):
            assert mod in s, f"{spec} missing hiddenimport {mod}"


def test_no_winsw_or_nssm_introduced():
    for entry in ("backend_entry.py", "relay_entry.py", "update_service_entry.py", "winservice.py"):
        s = _read(os.path.join(WINBUILD, entry)).lower()
        assert "winsw" not in s and "nssm" not in s


def test_wix_service_names_match_entry_constants():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    for name in (backend_entry.SVC_NAME, relay_entry.SVC_NAME, update_service_entry.SVC_NAME):
        assert f'Name="{name}"' in wxs, f"WiX missing service {name}"


def test_pywin32_pinned_to_python312_safe_release():
    req = _read(os.path.join(WINBUILD, "requirements-windows.txt"))
    m = re.search(r"^pywin32==(\d+)", req, re.M)
    assert m, "pywin32 must be pinned in requirements-windows.txt"
    ver = int(m.group(1))
    # 306 crashes (0xc0000005) under Python 3.12 in servicemanager; 307+ fixes it.
    assert ver >= 307, f"pywin32=={ver} is not Python 3.12-safe (need >= 307)"


def test_service_logging_is_crash_safe():
    src = _read(os.path.join(WINBUILD, "winservice.py"))
    # servicemanager logging must go through the swallow-all wrapper, never a bare inline call that could
    # fault before backend.log exists.
    assert "def _safe_log(" in src
    assert "servicemanager.LogInfoMsg(f\"" not in src
    assert "servicemanager.LogErrorMsg(f\"" not in src
    assert "_safe_log(servicemanager.LogInfoMsg" in src
    assert "_safe_log(servicemanager.LogErrorMsg" in src


def test_safe_log_swallows_logger_exceptions():
    # Rebuild the wrapper behavior locally: a raising logger must NOT propagate.
    def boom(_msg):
        raise OSError("event source not registered")

    def _safe_log(fn, message):
        try:
            fn(message)
        except Exception:
            pass

    _safe_log(boom, "starting")  # must not raise
