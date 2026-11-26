"""Runs the hermetic SQLite mobile-revision cases (_mobile_new_revision_cases.py) in a FRESH interpreter.

Those cases swap the shared ORM column types to SQLite variants in-process. Inside a long pytest worker,
earlier PostgreSQL-backed tests have already compiled/cached statements against the real types, so the cases
only behave correctly in a clean process.
"""
import os
import subprocess
import sys
from pathlib import Path


def test_mobile_new_revision_cases_in_isolated_process():
    here = Path(__file__).resolve().parent
    r = subprocess.run([sys.executable, "-m", "pytest", str(here / "_mobile_new_revision_cases.py"), "-q", "-n0",
                        "-p", "no:cacheprovider"], cwd=here.parent, capture_output=True, text=True, timeout=600,
                       env={**os.environ})
    assert r.returncode == 0, (r.stdout[-4000:] + r.stderr[-2000:])
    assert " passed" in r.stdout
