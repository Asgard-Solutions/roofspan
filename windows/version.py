"""Authoritative RoofSpan Office software version — the SINGLE source used by the application,
installer (WiX ProductVersion), updater, version policy, and release artifacts.

DEV/pre-release until production versioning is explicitly approved. Numeric MAJOR.MINOR.PATCH so it is
directly usable as an MSI ProductVersion; the human-facing DISPLAY_VERSION carries the channel suffix.
The single numeric value lives in windows/VERSION so both Python and PowerShell/WiX read one file.
"""
from __future__ import annotations

import os
import re

_VERSION_FILE = os.path.join(os.path.dirname(__file__), "VERSION")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _read_version() -> str:
    try:
        with open(_VERSION_FILE) as f:
            v = f.read().strip()
    except OSError:
        v = "0.1.0"
    return v if _SEMVER_RE.match(v) else "0.1.0"


# Numeric MAJOR.MINOR.PATCH (MSI-compatible). DEV baseline — NOT a production 1.0.0.
ROOFSPAN_VERSION = _read_version()
# Release channel: "dev" (default) until production versioning is approved, then "stable".
CHANNEL = os.environ.get("ROOFSPAN_CHANNEL", "dev")
# Human-facing version, e.g. "0.1.0-dev".
DISPLAY_VERSION = ROOFSPAN_VERSION if CHANNEL == "stable" else f"{ROOFSPAN_VERSION}-{CHANNEL}"


def is_valid_version(v: str) -> bool:
    return bool(_SEMVER_RE.match(str(v)))


def parse_version(v: str) -> tuple[int, int, int]:
    if not is_valid_version(v):
        raise ValueError(f"invalid semantic version: {v!r}")
    a, b, c = (int(x) for x in str(v).split("."))
    return (a, b, c)


def is_dev() -> bool:
    return CHANNEL != "stable"
