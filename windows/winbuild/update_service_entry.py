"""PyInstaller entry: roofspan-update-service.exe — background signed-update checker (every 12h).

Fetches the CloudFront update manifest, verifies signature + SHA-256, and (when an update applies) hands
off to updater.orchestrator with Windows-native effects. Never installs an unverified/tampered artifact.
Native execution + the Windows-native install/rollback effects are HUMAN REQUIRED.
"""
import logging
import os
import time

import httpx

from updater.manifest import parse_manifest
from updater.service import CHECK_INTERVAL_SECONDS, plan_update

log = logging.getLogger("roofspan.update")

MANIFEST_URL = os.environ.get(
    "ROOFSPAN_WINDOWS_UPDATE_MANIFEST_URL",
    "https://downloads.roofspan.io/update/windows/latest.json",
)


def _current_version() -> str:
    return os.environ.get("ROOFSPAN_VERSION", "0.1.0")


def _public_pem() -> str:
    # Update-verification PUBLIC key embedded at install time (never the private key).
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


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            check_once()
        except Exception as e:  # noqa: BLE001
            log.warning("update check failed: %s", str(e)[:200])
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
