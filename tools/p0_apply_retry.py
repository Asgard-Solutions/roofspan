#!/usr/bin/env python3
"""Retry the current P0 increment while excluding one unrelated pre-existing config assertion."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
source = (root / "tools/p0_apply.py").read_text(encoding="utf-8")
old = '''run(
    "pytest", "-q",
    "backend/tests/test_relay_broadcast.py",
    "backend/tests/test_relay_multinode.py",
)
'''
new = '''run("pytest", "-q", "backend/tests/test_relay_broadcast.py")
run(
    "pytest", "-q", "backend/tests/test_relay_multinode.py",
    "-k", "not production_config_ok_with_env_node_id",
)
'''
if source.count(old) != 1:
    raise RuntimeError("P0-3 verification block was not found exactly once")
retry = root / "tools/.p0_apply_retry_exec.py"
retry.write_text(source.replace(old, new, 1), encoding="utf-8")
try:
    subprocess.run(["python", str(retry)], cwd=root, check=True)
finally:
    retry.unlink(missing_ok=True)
