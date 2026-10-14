"""Immutable build identity (release version + full Git SHA) of THIS RoofSpan executable.

build_exes.ps1 generates `_roofspan_build_identity.py` (constants) and freezes it into all three service
executables together with the same runtime hook. The installed roofspan.env is never authoritative for
these values: config loaders skip IDENTITY_KEYS and call enforce() afterwards so every consumer that reads
the environment (backend/version.py, licensing, relay, updater) sees the executable's identity.
"""
from __future__ import annotations

import json
import os
import re

BUILD_CONTRACT = "roofspan-build-identity-v1"
IDENTITY_KEYS = ("ROOFSPAN_VERSION", "ROOFSPAN_BUILD_SHA")

try:  # present only inside a frozen build produced by build_exes.ps1
    import _roofspan_build_identity as _embedded  # type: ignore
except ImportError:  # source checkout / tests
    _embedded = None


def _source_version() -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "VERSION")
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
    except OSError:
        return "development"
    return value if re.fullmatch(r"\d+\.\d+\.\d+", value) else "development"


EMBEDDED = _embedded is not None
VERSION = _embedded.VERSION if EMBEDDED else _source_version()
BUILD_SHA = _embedded.BUILD_SHA if EMBEDDED else "development"
# True ONLY in CI test builds (build_exes.ps1 -TestFaultInjection); production builds must report False.
FAULT_INJECTION = bool(getattr(_embedded, "FAULT_INJECTION", False)) if EMBEDDED else False


def enforce() -> None:
    """Re-assert the executable's identity in the process environment (after any config load)."""
    os.environ["ROOFSPAN_VERSION"] = VERSION
    os.environ["ROOFSPAN_BUILD_SHA"] = BUILD_SHA


def build_info(service: str, **extra) -> dict:
    info = {"service": service, "version": VERSION, "build_sha": BUILD_SHA,
            "build_contract": BUILD_CONTRACT, "embedded": EMBEDDED, "fault_injection": FAULT_INJECTION}
    info.update(extra)
    return info


def print_build_info(service: str, **extra) -> None:
    print(json.dumps(build_info(service, **extra), sort_keys=True))
