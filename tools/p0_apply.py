#!/usr/bin/env python3
"""Finalize permanent P0 coverage, repository safety, and reproducible builds.

This temporary helper runs from GitHub Actions against a full Linux checkout. It removes itself and its
runner before committing, so no implementation machinery remains in the merged product tree.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def run(*cmd: str, cwd: Path | None = None, env: dict | None = None) -> None:
    subprocess.run(cmd, cwd=cwd or ROOT, env=env, check=True)


def replace_n(path: str, old: str, new: str, expected: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise RuntimeError(
            f"{path}: expected {expected} occurrence(s), found {count}: {old[:140]!r}"
        )
    target.write_text(text.replace(old, new), encoding="utf-8")


# ---------------------------------------------------------------------------
# Permanent CI coverage for all six P0 contracts.
# ---------------------------------------------------------------------------
replace_n(
    ".github/workflows/roof-takeoff-contract.yml",
    '      - "backend/models.py"\n',
    '      - "backend/models.py"\n      - "backend/core.py"\n',
    expected=2,
)
replace_n(
    ".github/workflows/roof-takeoff-contract.yml",
    '      - "backend/alembic/versions/e0f1a2b3c4d5_measurement_sketches.py"\n',
    '      - "backend/alembic/versions/e0f1a2b3c4d5_measurement_sketches.py"\n'
    '      - "backend/alembic/versions/e7f8a9b0c1d2_lead_primary_measurement_sets.py"\n',
    expected=2,
)
replace_n(
    ".github/workflows/roof-takeoff-contract.yml",
    '      - "backend/tests/test_measurement_sketch_survival.py"\n',
    '      - "backend/tests/test_measurement_sketch_survival.py"\n'
    '      - "backend/tests/test_measurement_set_constraint_migration.py"\n',
    expected=2,
)
replace_n(
    ".github/workflows/roof-takeoff-contract.yml",
    '      - "mobile/src/measurementCache.js"\n',
    '      - "mobile/src/measurementCache.js"\n'
    '      - "mobile/src/measurementConflict.js"\n'
    '      - "mobile/src/measurementReconcile.js"\n'
    '      - "mobile/src/measurementRecovery.js"\n'
    '      - "mobile/src/measurementWorkingDraft.js"\n'
    '      - "mobile/src/tests/measurement_conflict_transition.node.test.js"\n'
    '      - "mobile/src/tests/measurement_durable_merge_base.node.test.js"\n',
    expected=2,
)
replace_n(
    ".github/workflows/roof-takeoff-contract.yml",
    '''      - name: Apply database migrations
        working-directory: backend
        run: alembic -c alembic.ini upgrade head
''',
    '''      - name: Apply database migrations
        working-directory: backend
        run: alembic -c alembic.ini upgrade head
      - name: Verify lead-primary measurement-set migration
        run: pytest -q -n 0 backend/tests/test_measurement_set_constraint_migration.py
''',
)
replace_n(
    ".github/workflows/roof-takeoff-contract.yml",
    '          backend/alembic/versions/e0f1a2b3c4d5_measurement_sketches.py\n',
    '          backend/alembic/versions/e0f1a2b3c4d5_measurement_sketches.py\n'
    '          backend/alembic/versions/e7f8a9b0c1d2_lead_primary_measurement_sets.py\n',
)
replace_n(
    ".github/workflows/roof-takeoff-contract.yml",
    "'src/measurementCache.js','src/sketchCache.js'",
    "'src/measurementCache.js','src/measurementConflict.js','src/measurementReconcile.js','src/measurementRecovery.js','src/measurementWorkingDraft.js','src/sketchCache.js'",
)

replace_n(
    ".github/workflows/hosted-mobile-pairing.yml",
    '      - "backend/tests/test_hosted_pairing_client.py"\n',
    '      - "backend/tests/test_hosted_pairing_client.py"\n'
    '      - "backend/tests/test_relay_broadcast.py"\n',
    expected=2,
)
replace_n(
    ".github/workflows/hosted-mobile-pairing.yml",
    '            qrcode pillow PyJWT passlib bcrypt alembic websockets\n',
    '            qrcode pillow PyJWT passlib bcrypt alembic websockets redis\n',
)
replace_n(
    ".github/workflows/hosted-mobile-pairing.yml",
    '''          pytest -q -n 0 backend/tests/test_hosted_pairing_client.py
          pytest -q -n 0 windows/tests/test_relay_connector_release_contract.py
''',
    '''          pytest -q -n 0 backend/tests/test_hosted_pairing_client.py
          pytest -q -n 0 backend/tests/test_relay_broadcast.py
          pytest -q -n 0 windows/tests/test_relay_connector_release_contract.py windows/tests/test_relay_connector_outbox_bootstrap.py
''',
)
replace_n(
    ".github/workflows/hosted-mobile-pairing.yml",
    '''            backend/licensing/pairing_client.py \\
            backend/relay/server.py \\
            backend/routers/relay_connector.py \\
''',
    '''            backend/licensing/pairing_client.py \\
            backend/relay/config.py \\
            backend/relay/hub.py \\
            backend/relay/server.py \\
            backend/relay/tunnel_client.py \\
            backend/routers/relay_connector.py \\
''',
)
replace_n(
    ".github/workflows/hosted-mobile-pairing.yml",
    '''            windows/winbuild/relay_entry.py \\
            windows/tests/test_relay_connector_release_contract.py
''',
    '''            windows/winbuild/relay_entry.py \\
            windows/tests/test_relay_connector_release_contract.py \\
            windows/tests/test_relay_connector_outbox_bootstrap.py
''',
)
replace_n(
    ".github/workflows/hosted-mobile-pairing.yml",
    "          grep -q 'hosted-installation-identity-v2' windows/winbuild/relay_entry.py\n",
    "          grep -q 'hosted-installation-identity-v2' windows/winbuild/relay_entry.py\n"
    "          grep -q 'outbox_token=connector_token' windows/winbuild/relay_entry.py\n",
)

# Parse the edited workflow YAML before relying on GitHub to do it.
for workflow in (
    ROOT / ".github/workflows/roof-takeoff-contract.yml",
    ROOT / ".github/workflows/hosted-mobile-pairing.yml",
):
    parsed = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or "jobs" not in parsed:
        raise RuntimeError(f"Invalid workflow YAML: {workflow}")


# ---------------------------------------------------------------------------
# Remove every tracked path that Windows cannot check out. The corrupt path is
# not representable safely through a normal Windows filesystem or text API, so
# operate on Git's raw NUL-separated byte paths in this Linux runner.
# ---------------------------------------------------------------------------
def windows_unsafe(path_bytes: bytes) -> bool:
    if any(value < 0x20 or value == 0x7F for value in path_bytes):
        return True
    try:
        decoded = path_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return True
    reserved = set('<>:"|?*')
    for segment in decoded.split("/"):
        if any(char in reserved for char in segment):
            return True
        if segment.endswith((".", " ")):
            return True
    return False


raw_paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
unsafe = [value for value in raw_paths.split(b"\x00") if value and windows_unsafe(value)]
for raw_path in unsafe:
    print(f"Removing Windows-unsafe tracked path: {raw_path!r}", flush=True)
    subprocess.run([b"git", b"rm", b"-f", b"--", raw_path], cwd=os.fsencode(ROOT), check=True)
remaining = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
remaining_unsafe = [
    value for value in remaining.split(b"\x00") if value and windows_unsafe(value)
]
if remaining_unsafe:
    raise RuntimeError(f"Windows-unsafe tracked paths remain: {remaining_unsafe!r}")
if not unsafe:
    raise RuntimeError("Expected the known Windows-unsafe tracked path, but none was found")


# ---------------------------------------------------------------------------
# Regenerate the stale Office lockfile with the repository's required Yarn 1,
# then prove frozen installation and a production Office build.
# ---------------------------------------------------------------------------
run("npm", "install", "--global", "yarn@1.22.22")
run("yarn", "install", "--network-timeout", "600000", cwd=FRONTEND)
run("yarn", "install", "--frozen-lockfile", "--network-timeout", "600000", cwd=FRONTEND)
build_env = os.environ.copy()
build_env["CI"] = "false"
run("yarn", "build", cwd=FRONTEND, env=build_env)


# ---------------------------------------------------------------------------
# Fresh cross-area verification before deleting this temporary runner.
# ---------------------------------------------------------------------------
run("alembic", "-c", "alembic.ini", "upgrade", "head", cwd=BACKEND)
run("pytest", "-q", "-n", "0", "backend/tests/test_measurement_set_constraint_migration.py")
run(
    "pytest", "-q", "-n", "0",
    "backend/tests/test_measurement_sketch_service.py",
    "backend/tests/test_office_outbox.py",
    "backend/tests/test_relay_broadcast.py",
    "windows/tests/test_relay_connector_release_contract.py",
    "windows/tests/test_relay_connector_outbox_bootstrap.py",
)
run("npm", "ci")
run("npm", "--prefix", "mobile", "run", "test:measurements")


# No temporary implementation mechanism belongs in the product branch.
for temporary in (
    ".github/workflows/p0-implementation-runner.yml",
    "tools/p0_apply.py",
    "tools/p0_apply_retry.py",
):
    candidate = ROOT / temporary
    if candidate.exists():
        run("git", "rm", "-f", "--", temporary)

run("git", "diff", "--check")
