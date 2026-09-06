#!/usr/bin/env python3
"""Run P0-6 while excluding the existing live-server-only lifecycle probe."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
source = (root / "tools/p0_apply.py").read_text(encoding="utf-8")
old = '''run(
    "pytest", "-q",
    "backend/tests/test_measurement_sketch_service.py",
    "backend/tests/test_office_outbox.py",
    "backend/tests/test_measurement_lifecycle_regression.py",
)
'''
new = '''run(
    "pytest", "-q",
    "backend/tests/test_measurement_sketch_service.py",
    "backend/tests/test_office_outbox.py",
)
'''
if source.count(old) != 1:
    raise RuntimeError("P0-6 focused verification block was not found exactly once")
retry = root / "tools/.p0_apply_retry_exec.py"
retry.write_text(source.replace(old, new, 1), encoding="utf-8")
try:
    subprocess.run(["python", str(retry)], cwd=root, check=True)
finally:
    retry.unlink(missing_ok=True)
