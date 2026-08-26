#!/usr/bin/env python3
"""Apply/verify RoofSpan's single public Control Plane + Relay origin.

The hosted ASGI application serves both the Control Plane and Secure Relay.  Keeping a second
``relay.roofspan.io`` client default created a split deployment: pairing succeeded against
``cp.roofspan.io`` while the Mobile/Office WebSockets attempted to reach a different host.  This
migration makes ``wss://cp.roofspan.io`` authoritative, while retaining an explicit runtime rewrite
for already-installed Office configs and already-issued pairing payloads that contain the legacy host.

Run without arguments to apply the migration.  Run with ``--check`` in CI to fail if a future change
reintroduces the split origin or removes one of the compatibility rewrites.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_ORIGIN = "wss://relay.roofspan.io"
CANONICAL_ORIGIN = "wss://cp.roofspan.io"

# Files that contain deploy/build/test defaults.  Missing optional files are ignored so this script
# remains usable across older checkouts, but all CRITICAL_FILES are required by --check.
ORIGIN_FILES = [
    "backend/control_plane/config.py",
    "backend/tests/hosted_pairing_probe.py",
    "backend/tests/test_hosted_pairing_client.py",
    "mobile/eas.json",
    "mobile/app.json",
    "mobile/app.config.js",
    "mobile/src/config.js",
    "windows/winbuild/config/roofspan.env.template",
    "infra/config/production.endpoints.env.example",
    "deploy/railway/README.md",
    "docs/control-plane-mobile-pairing-runbook.md",
    ".github/workflows/hosted-mobile-pairing.yml",
    ".github/workflows/control-plane-release-gate.yml",
]
CRITICAL_FILES = [
    "backend/control_plane/config.py",
    "mobile/eas.json",
    "mobile/src/config.js",
    "windows/winbuild/config/roofspan.env.template",
    "backend/routers/relay_connector.py",
    "backend/cp_asgi.py",
]

VALIDATION_WORKFLOW = r'''name: relay-single-origin-contract

on:
  push:
    paths:
      - "backend/control_plane/**"
      - "backend/relay/**"
      - "backend/routers/relay_connector.py"
      - "backend/cp_asgi.py"
      - "backend/tests/hosted_pairing_probe.py"
      - "mobile/**"
      - "windows/winbuild/config/roofspan.env.template"
      - "infra/config/production.endpoints.env.example"
      - "deploy/railway/**"
      - "tools/apply_relay_single_origin.py"
      - ".github/workflows/relay-single-origin-contract.yml"
  pull_request:
    paths:
      - "backend/control_plane/**"
      - "backend/relay/**"
      - "backend/routers/relay_connector.py"
      - "backend/cp_asgi.py"
      - "backend/tests/hosted_pairing_probe.py"
      - "mobile/**"
      - "windows/winbuild/config/roofspan.env.template"
      - "infra/config/production.endpoints.env.example"
      - "deploy/railway/**"
      - "tools/apply_relay_single_origin.py"
      - ".github/workflows/relay-single-origin-contract.yml"
  workflow_dispatch:

jobs:
  contract:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Verify canonical public Relay origin and legacy rewrites
        run: python tools/apply_relay_single_origin.py --check
      - name: Compile changed Python modules
        run: python -m py_compile backend/routers/relay_connector.py backend/control_plane/config.py backend/cp_asgi.py
      - name: Validate Mobile pairing helpers
        working-directory: mobile
        run: |
          npm ci
          npm run test:pairing
      - name: Verify clean patch
        run: git diff --check
'''


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _write(relative: str, text: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _replace_public_defaults() -> list[str]:
    changed: list[str] = []
    for relative in ORIGIN_FILES:
        path = ROOT / relative
        if not path.is_file():
            continue
        old = path.read_text(encoding="utf-8")
        new = old.replace(LEGACY_ORIGIN, CANONICAL_ORIGIN)
        if new != old:
            _write(relative, new)
            changed.append(relative)
    return changed


def _patch_mobile_config() -> bool:
    relative = "mobile/src/config.js"
    text = _read(relative)
    original = text

    helper = '''\n// cp_asgi serves both Control Plane HTTP and Secure Relay WebSockets. Pairings created before the\n// single-origin correction may still contain relay.roofspan.io; rewrite those durable payloads\n// locally so already-paired devices recover without clearing app data or pairing again.\nconst LEGACY_RELAY_ORIGIN_RE = /^wss?:\\/\\/relay\\.roofspan\\.io(?=\\/|$)/i;\nfunction canonicalRelayOrigin(value) {\n  return cleanBase(value).replace(LEGACY_RELAY_ORIGIN_RE, "wss://cp.roofspan.io");\n}\n'''
    if "LEGACY_RELAY_ORIGIN_RE" not in text:
        needle = '''function cleanBase(value) {\n  return String(value || "").trim().replace(/\\/+$/, "");\n}\n'''
        if needle not in text:
            raise RuntimeError(f"{relative}: cleanBase anchor not found")
        text = text.replace(needle, needle + helper, 1)

    text = text.replace(
        "  let origin = cleanBase(pairingEndpoint) || RELAY_WSS_BASE;",
        "  let origin = canonicalRelayOrigin(pairingEndpoint) || canonicalRelayOrigin(RELAY_WSS_BASE);",
    )
    text = text.replace(
        '''  if (/\\/api\\/relay\\/tunnel$/i.test(origin)) {\n    return origin.replace(/\\/api\\/relay\\/tunnel$/i, "/api/relay/mobile");\n  }''',
        '''  if (/\\/api\\/relay\\/(?:tunnel|installation)$/i.test(origin)) {\n    return origin.replace(/\\/api\\/relay\\/(?:tunnel|installation)$/i, "/api/relay/mobile");\n  }''',
    )

    if "canonicalRelayOrigin(pairingEndpoint)" not in text:
        raise RuntimeError(f"{relative}: pairing endpoint compatibility rewrite was not installed")
    if "(?:tunnel|installation)" not in text:
        raise RuntimeError(f"{relative}: installation-to-mobile path normalization was not installed")

    if text != original:
        _write(relative, text)
        return True
    return False


def _patch_office_connector() -> bool:
    relative = "backend/routers/relay_connector.py"
    text = _read(relative)
    original = text

    if "LEGACY_RELAY_HOST" not in text:
        anchor = 'router = APIRouter(prefix="/api/relay/connector", tags=["relay-connector"])\n'
        addition = '''\n# PR #5 originally shipped a separate relay.roofspan.io default even though the Railway ASGI\n# deployment serves both Control Plane and Relay. Preserve upgrade compatibility by rewriting the\n# old host at runtime; customer roofspan.env files are intentionally retained across upgrades.\nLEGACY_RELAY_HOST = "relay.roofspan.io"\nCANONICAL_RELAY_HOST = "cp.roofspan.io"\n'''
        if anchor not in text:
            raise RuntimeError(f"{relative}: router anchor not found")
        text = text.replace(anchor, anchor + addition, 1)

    parse_anchor = "    parsed = urlparse(raw)\n"
    rewrite = '''    parsed = urlparse(raw)\n    if (parsed.hostname or "").lower() == LEGACY_RELAY_HOST:\n        # The legacy hostname may remain in a preserved ProgramData roofspan.env.  Route it to the\n        # same deployed ASGI origin that issued the hosted installation id and pairing credential.\n        netloc = CANONICAL_RELAY_HOST + (f":{parsed.port}" if parsed.port else "")\n        parsed = parsed._replace(scheme="wss", netloc=netloc)\n'''
    if "same deployed ASGI origin" not in text:
        if parse_anchor not in text:
            raise RuntimeError(f"{relative}: urlparse anchor not found")
        text = text.replace(parse_anchor, rewrite, 1)

    old_path_block = '''    elif path.endswith("/api/relay/tunnel"):\n        # Compatibility with the pre-release template; use the canonical route going forward.\n        path = path[: -len("/api/relay/tunnel")] + "/api/relay/installation"\n'''
    new_path_block = '''    elif path.endswith(("/api/relay/tunnel", "/api/relay/mobile")):\n        # Compatibility with pre-release connector/mobile endpoints; the Windows service needs the\n        # installation-tunnel route on the same canonical origin.\n        old_suffix = "/api/relay/tunnel" if path.endswith("/api/relay/tunnel") else "/api/relay/mobile"\n        path = path[: -len(old_suffix)] + "/api/relay/installation"\n'''
    if old_path_block in text:
        text = text.replace(old_path_block, new_path_block, 1)

    if "LEGACY_RELAY_HOST" not in text or "same deployed ASGI origin" not in text:
        raise RuntimeError(f"{relative}: legacy Office configuration rewrite was not installed")

    if text != original:
        _write(relative, text)
        return True
    return False


def _install_validation_workflow() -> bool:
    relative = ".github/workflows/relay-single-origin-contract.yml"
    path = ROOT / relative
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    wanted = VALIDATION_WORKFLOW.rstrip() + "\n"
    if current != wanted:
        _write(relative, wanted)
        return True
    return False


def apply() -> list[str]:
    changed = _replace_public_defaults()
    if _patch_mobile_config():
        changed.append("mobile/src/config.js")
    if _patch_office_connector():
        changed.append("backend/routers/relay_connector.py")
    if _install_validation_workflow():
        changed.append(".github/workflows/relay-single-origin-contract.yml")
    return sorted(set(changed))


def validate() -> list[str]:
    errors: list[str] = []
    for relative in CRITICAL_FILES:
        if not (ROOT / relative).is_file():
            errors.append(f"missing critical file: {relative}")

    for relative in ORIGIN_FILES:
        path = ROOT / relative
        if path.is_file() and LEGACY_ORIGIN in path.read_text(encoding="utf-8"):
            errors.append(f"legacy public Relay origin remains in {relative}")

    mobile = _read("mobile/src/config.js")
    if CANONICAL_ORIGIN not in mobile:
        errors.append("Mobile does not default to the canonical Relay origin")
    if "LEGACY_RELAY_ORIGIN_RE" not in mobile or "canonicalRelayOrigin(pairingEndpoint)" not in mobile:
        errors.append("Mobile cannot migrate already-issued legacy pairing payloads")
    if "(?:tunnel|installation)" not in mobile:
        errors.append("Mobile does not normalize the Office installation route")

    office = _read("backend/routers/relay_connector.py")
    if "LEGACY_RELAY_HOST" not in office or "CANONICAL_RELAY_HOST" not in office:
        errors.append("Office cannot migrate a preserved legacy roofspan.env Relay host")
    if CANONICAL_ORIGIN not in office:
        errors.append("Office connector does not default to the canonical Relay origin")

    cp_asgi = _read("backend/cp_asgi.py")
    if "app.include_router(relay_router)" not in cp_asgi:
        errors.append("Hosted cp_asgi does not expose Relay WebSocket routes")
    if "relay_hub.startup" not in cp_asgi:
        errors.append("Hosted cp_asgi does not start the Relay routing hub")

    eas = _read("mobile/eas.json")
    if CANONICAL_ORIGIN not in eas:
        errors.append("EAS preview/production builds are not pinned to the canonical Relay origin")

    template = _read("windows/winbuild/config/roofspan.env.template")
    if f"ROOFSPAN_RELAY_WS_URL={CANONICAL_ORIGIN}/api/relay/installation" not in template:
        errors.append("Windows template does not use the canonical installation WebSocket route")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if not args.check:
        changed = apply()
        if changed:
            print("Updated Relay single-origin contract:")
            for item in changed:
                print(f"  - {item}")
        else:
            print("Relay single-origin contract already applied.")

    errors = validate()
    if errors:
        print("Relay single-origin validation FAILED:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Relay single-origin validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
