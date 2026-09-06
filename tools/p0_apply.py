#!/usr/bin/env python3
"""Apply and verify the current RoofSpan P0 hardening increment.

Temporary implementation helper. The branch workflow runs this against a complete checkout, which lets
us make narrowly asserted replacements without rewriting unrelated large source files through the GitHub
contents API. It is removed before the pull request is merged.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one replacement, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def run(*cmd: str, cwd: str | None = None) -> None:
    subprocess.run(cmd, cwd=ROOT / cwd if cwd else ROOT, check=True)


# P0-1: preserve log_action's historical commit-by-default contract, while allowing the measurement
# mutation, audit entry and outbox row to be staged in one SQLAlchemy transaction.
replace_once(
    "backend/core.py",
    "    request: Request | None = None,\n):\n",
    "    request: Request | None = None,\n    commit: bool = True,\n):\n",
)
replace_once(
    "backend/core.py",
    "    db.add(entry)\n    await db.commit()",
    "    db.add(entry)\n    if commit:\n        await db.commit()\n    else:\n        # The caller owns the transaction boundary. Flush so database constraints fail here, while the\n        # business mutation, audit entry and transactional outbox row remain part of one final commit.\n        await db.flush()",
)

measurement_replacements = {
    "await log_action(db, user=user, action=\"measurement.create\", entity_type=\"measurement_revision\", entity_id=str(rev.id), detail={\"revision\": rev.revision_number}, request=request)":
        "await log_action(db, user=user, action=\"measurement.create\", entity_type=\"measurement_revision\", entity_id=str(rev.id), detail={\"revision\": rev.revision_number}, request=request, commit=False)",
    "await log_action(db, user=user, action=\"measurement.update\", entity_type=\"measurement_revision\", entity_id=str(rev.id), detail={\"revision\": rev.revision_number}, request=request)":
        "await log_action(db, user=user, action=\"measurement.update\", entity_type=\"measurement_revision\", entity_id=str(rev.id), detail={\"revision\": rev.revision_number}, request=request, commit=False)",
    "await log_action(db, user=user, action=f\"measurement.status.{payload.to}\", entity_type=\"measurement_revision\", entity_id=str(rev.id), detail={\"revision\": rev.revision_number}, request=request)":
        "await log_action(db, user=user, action=f\"measurement.status.{payload.to}\", entity_type=\"measurement_revision\", entity_id=str(rev.id), detail={\"revision\": rev.revision_number}, request=request, commit=False)",
    "await log_action(db, user=user, action=\"measurement.unlock\", entity_type=\"measurement_revision\", entity_id=str(rev.id), detail={\"revision\": rev.revision_number}, request=request)":
        "await log_action(db, user=user, action=\"measurement.unlock\", entity_type=\"measurement_revision\", entity_id=str(rev.id), detail={\"revision\": rev.revision_number}, request=request, commit=False)",
    "await log_action(db, user=user, action=\"measurement.new_revision\", entity_type=\"measurement_revision\", entity_id=str(new.id), detail={\"from\": rev.revision_number, \"to\": new.revision_number}, request=request)":
        "await log_action(db, user=user, action=\"measurement.new_revision\", entity_type=\"measurement_revision\", entity_id=str(new.id), detail={\"from\": rev.revision_number, \"to\": new.revision_number}, request=request, commit=False)",
}
for old, new in measurement_replacements.items():
    replace_once("backend/routers/measurements.py", old, new)

replace_once(
    "backend/routers/measurement_sketches.py",
    "await log_action(db, user=user, action=\"measurement.sketch.update\" if existed else \"measurement.sketch.create\", entity_type=\"measurement_sketch\", entity_id=structure_id, detail={\"revision_id\": revision_id, \"document_version\": out[\"document_version\"]}, request=request)",
    "await log_action(db, user=user, action=\"measurement.sketch.update\" if existed else \"measurement.sketch.create\", entity_type=\"measurement_sketch\", entity_id=structure_id, detail={\"revision_id\": revision_id, \"document_version\": out[\"document_version\"]}, request=request, commit=False)",
)

# Verification: real PostgreSQL migration + rollback injection + existing measurement/sketch contracts.
run("alembic", "-c", "alembic.ini", "upgrade", "head", cwd="backend")
run(
    "pytest", "-q",
    "backend/tests/test_measurement_sketch_service.py",
    "backend/tests/test_office_outbox.py",
    "backend/tests/test_measurement_lifecycle_regression.py",
)
run("python", "-m", "py_compile", "backend/core.py", "backend/routers/measurements.py", "backend/routers/measurement_sketches.py")

Path("/tmp/p0_commit_message").write_text(
    "fix: make measurement outbox writes transactional\n",
    encoding="utf-8",
)
