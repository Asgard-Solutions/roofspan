import os
from pathlib import Path

# Ensure the backend integration test suite can always find the app URL with a single command
# (`python -m pytest tests/`) by falling back to the frontend .env if REACT_APP_BACKEND_URL is unset.
if not os.environ.get("REACT_APP_BACKEND_URL"):
    env_file = Path("/app/frontend/.env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                os.environ["REACT_APP_BACKEND_URL"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

# Load backend/.env (DATABASE_URL, secrets, etc.) so unit tests that import db/service/licensing
# modules work standalone. Only fills keys that are not already set in the environment.
_backend_env = Path(__file__).resolve().parent.parent / ".env"
if _backend_env.exists():
    for line in _backend_env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def _cleanup_module():
    try:
        from tests import _test_data_cleanup as c
    except ImportError:
        import _test_data_cleanup as c
    return c


def pytest_configure(config):
    # Controller process only (xdist workers have `workerinput`): snapshot price books before any test runs.
    if hasattr(config, "workerinput"):
        return
    try:
        config._pb_snapshot = _cleanup_module().snapshot()
    except Exception as exc:
        config._pb_snapshot = None
        print(f"[test cleanup] price book snapshot skipped: {exc}")


def pytest_sessionfinish(session, exitstatus):
    # After ALL workers finish: delete price books this run created (strict test-name pattern only), restore default.
    config = session.config
    snap = getattr(config, "_pb_snapshot", None)
    if hasattr(config, "workerinput") or not snap:
        return
    try:
        n = _cleanup_module().purge(only_new_since=snap[0], restore_default=snap[1])
        if n:
            print(f"[test cleanup] removed {n} automated-test price book(s)")
    except Exception as exc:
        print(f"[test cleanup] price book purge skipped: {exc}")
