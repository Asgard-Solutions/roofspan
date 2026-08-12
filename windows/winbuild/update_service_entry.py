"""PyInstaller entry: roofspan-update-service.exe — background signed-update checker Windows service.

Runs as a real Windows SCM service (RoofSpanUpdateService) when frozen, else foreground (dev). Every 12h
it fetches the CloudFront update manifest, verifies signature + SHA-256, and plans an update. It does NOT
apply updates here — the Windows-native install/rollback effects (which would need to replace Program
Files binaries and therefore elevated rights) remain HUMAN REQUIRED and are handled by the updater
orchestrator. A STOP request interrupts the interval sleep and exits promptly. Update behavior/cadence
unchanged.
"""
import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import httpx

from updater.manifest import parse_manifest
from updater.service import CHECK_INTERVAL_SECONDS, plan_update

DEFAULT_DATA_ROOT = r"C:\ProgramData\RoofSpan"
DEFAULT_LOG_DIR = os.path.join(DEFAULT_DATA_ROOT, "logs")

SVC_NAME = "RoofSpanUpdateService"    # MUST match installer/RoofSpan.wxs
SVC_DISPLAY = "RoofSpan Update Service"
SVC_DESC = "Checks downloads.roofspan.io for signed updates every 12h; verifies + applies safely."

MANIFEST_URL = os.environ.get(
    "ROOFSPAN_WINDOWS_UPDATE_MANIFEST_URL",
    "https://downloads.roofspan.io/update/windows/latest.json",
)

log = logging.getLogger("roofspan.update.service")


def _current_version() -> str:
    return os.environ.get("ROOFSPAN_VERSION", "0.1.0")


def _public_pem() -> str:
    with open(os.environ["ROOFSPAN_UPDATE_PUBLIC_KEY"], "r") as f:
        return f.read()


def check_once() -> str:
    resp = httpx.get(MANIFEST_URL, timeout=30)
    resp.raise_for_status()
    manifest = parse_manifest(resp.text)
    decision = plan_update(_current_version(), manifest, _public_pem())
    log.info("update check: %s (manifest %s)", decision, manifest.version)
    # HUMAN REQUIRED (Windows-native): on 'required'/'optional', hand off to UpdateOrchestrator with
    # native download/backup/install/migrate/health/restore effects. Verification + policy already done.
    return decision


def _prepare_runtime() -> None:
    from winbuild import winservice
    winservice.load_programdata_env()
    root = logging.getLogger("roofspan")
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    log_path = os.path.join(os.environ.get("ROOFSPAN_LOG_DIR", DEFAULT_LOG_DIR), "update-service.log")
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        handlers.append(RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"))
    except OSError as e:
        root.warning("update-service: file logging unavailable (%s); console only", e)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)


async def _check_loop() -> None:
    """Long-running loop; cancellation (SCM STOP) interrupts the interval sleep immediately."""
    while True:
        try:
            await asyncio.to_thread(check_once)
        except Exception as e:  # noqa: BLE001
            log.warning("update check failed: %s", str(e)[:200])
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def build_runner():
    from winbuild import winservice
    _prepare_runtime()
    # cancel-based stop: task.cancel() interrupts asyncio.sleep(interval) at once -> prompt STOP.
    return winservice.AsyncServiceRunner(_check_loop)


def run_foreground() -> None:
    _prepare_runtime()
    try:
        asyncio.run(_check_loop())
    except KeyboardInterrupt:
        log.info("update service stopping")


def main() -> None:
    if getattr(sys, "frozen", False):
        try:
            from winbuild import winservice
        except ImportError:
            import winservice  # PyInstaller flat-layout fallback
        svc = winservice.build_service_class(SVC_NAME, SVC_DISPLAY, SVC_DESC, build_runner)
        winservice.dispatch(svc)
    else:
        run_foreground()


if __name__ == "__main__":
    main()
