"""RoofSpan Office version resolution for the running app (support/diagnostics).

Single source of truth is windows/VERSION (also used by the installer/updater). In production the
installer can set ROOFSPAN_VERSION/ROOFSPAN_CHANNEL env vars; otherwise we read the repo VERSION file.
"""
import os
import re
from pathlib import Path

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_FALLBACK = "0.1.0"


def _read_version() -> str:
    env_v = os.environ.get("ROOFSPAN_VERSION", "").strip()
    if _SEMVER_RE.match(env_v):
        return env_v
    version_file = Path(__file__).resolve().parent.parent / "windows" / "VERSION"
    try:
        file_v = version_file.read_text().strip()
        if _SEMVER_RE.match(file_v):
            return file_v
    except OSError:
        pass
    return _FALLBACK


ROOFSPAN_VERSION = _read_version()
CHANNEL = os.environ.get("ROOFSPAN_CHANNEL", "dev")
DISPLAY_VERSION = ROOFSPAN_VERSION if CHANNEL == "stable" else f"{ROOFSPAN_VERSION}-{CHANNEL}"
