import pytest
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
    try:
        config._biz_snapshot = _cleanup_module().business_snapshot()
    except Exception as exc:
        config._biz_snapshot = None
        print(f"[test cleanup] business snapshot skipped: {exc}")
    try:
        config._user_snapshot = _cleanup_module().user_snapshot()
    except Exception as exc:
        config._user_snapshot = None
        print(f"[test cleanup] user snapshot skipped: {exc}")


def pytest_sessionfinish(session, exitstatus):
    # After ALL workers finish. Order matters: price books first (their entries reference materials),
    # then business records (tracked by id), then users.
    config = session.config
    if hasattr(config, "workerinput"):
        return
    c = _cleanup_module()
    snap = getattr(config, "_pb_snapshot", None)
    if snap:
        try:
            n = c.purge(only_new_since=snap[0], restore_default=snap[1])
            if n:
                print(f"[test cleanup] removed {n} automated-test price book(s)")
        except Exception as exc:
            print(f"[test cleanup] price book purge skipped: {exc}")
    biz = getattr(config, "_biz_snapshot", None)
    if biz is not None:
        try:
            r = c.purge_business(biz)
            if r:
                print(f"[test cleanup] removed test business records: {r}")
        except Exception as exc:
            print(f"[test cleanup] business purge skipped: {exc}")
    users = getattr(config, "_user_snapshot", None)
    if users is not None:
        try:
            n = c.purge_users(only_new_since=users)
            if n:
                print(f"[test cleanup] removed {n} automated-test user(s)")
        except Exception as exc:
            print(f"[test cleanup] user purge skipped: {exc}")


@pytest.fixture(autouse=True)
def _fresh_db_pools():
    """Each test may run its own event loop (asyncio.run). Pooled asyncpg connections are bound to the loop
    that opened them, so drop (without awaiting) any pool left by an earlier test in this worker."""
    import sys as _sys
    for mod in ("db", "control_plane.db"):
        m = _sys.modules.get(mod)
        eng = getattr(m, "engine", None) if m else None
        if eng is not None:
            eng.sync_engine.dispose(close=False)
    yield


# Suites that change the company's live subscription/licence state (suspended, grace, seat counts) or
# rotate relay/pairing state. While one runs, every other test would see "subscription requires attention",
# so they hold an EXCLUSIVE cross-worker lock for the whole module and every other module holds a SHARED lock.
GLOBAL_STATE_MODULES = {"test_licensing_api", "test_billing", "test_stripe_billing", "test_seat_enforcement",
                        "test_pairing", "test_relay"}
_LOCK_PATH = "/tmp/roofspan_pytest_global_state.lock"


def _module_name(request):
    return request.module.__name__.rsplit(".", 1)[-1]


@pytest.fixture(scope="module", autouse=True)
def _global_state_exclusive(request):
    if _module_name(request) not in GLOBAL_STATE_MODULES:
        yield
        return
    import fcntl
    with open(_LOCK_PATH, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


@pytest.fixture(scope="module", autouse=True)
def _global_state_shared(request):
    if _module_name(request) in GLOBAL_STATE_MODULES:
        yield
        return
    import fcntl
    with open(_LOCK_PATH, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# Shared singleton state that some suites change and others assert on. Modules in the same group run one at a
# time across workers (other tests are unaffected):
#  - abc: the ONE shared (MOCKED) ABC Supply connection (connect/disconnect/environment/ship-to)
#  - pricebook: which price book is the company default
_GROUP_LOCKS = {
    "abc": lambda src: "/integrations/abc/" in src,
    "pricebook": lambda src: "price-books" in src and ("is_default" in src or "set-default" in src),
}


@pytest.fixture(scope="module", autouse=True)
def _shared_state_groups(request, _global_state_shared, _global_state_exclusive):
    try:
        src = Path(request.module.__file__).read_text(errors="ignore")
    except Exception:
        src = ""
    groups = sorted(g for g, hit in _GROUP_LOCKS.items() if hit(src))  # fixed order -> no lock-order deadlock
    if not groups:
        yield
        return
    import contextlib
    import fcntl
    with contextlib.ExitStack() as stack:
        for g in groups:
            fh = stack.enter_context(open(f"/tmp/roofspan_pytest_{g}.lock", "a"))
            fcntl.flock(fh, fcntl.LOCK_EX)
            stack.callback(fcntl.flock, fh, fcntl.LOCK_UN)
        orig_pb = _cleanup_module().default_price_book() if "pricebook" in groups else None
        try:
            yield
        finally:
            if orig_pb:  # a module that made its own book the default must not leak that to later modules
                _cleanup_module().restore_default_price_book(orig_pb)
