"""Windows Control Plane DB provisioning/repair (fixes the 'permission denied to create database' /
missing roofspan_control_plane pairing defect).

db_bootstrap imports asyncpg lazily inside its functions, so we inject a fake asyncpg that records
the SQL issued and simulates server state. This lets us assert the provisioning DECISIONS without a
real PostgreSQL superuser or Windows DPAPI.
"""
import sys
import types
import asyncio
import importlib

# Make windows/winbuild importable.
sys.path.insert(0, "/app/windows/winbuild")
db_bootstrap = importlib.import_module("db_bootstrap")


class _FakeConn:
    def __init__(self, state, connect_kwargs):
        self.state = state
        self.connect_kwargs = connect_kwargs

    async def fetchval(self, q, *args):
        if "quote_literal" in q:
            return "'quoted-pw'"
        if "pg_roles" in q:
            return 1 if args and args[0] in self.state["roles"] else None
        if "pg_database" in q:
            return 1 if args and args[0] in self.state["dbs"] else None
        return None

    async def execute(self, q, *args):
        self.state["executed"].append(q)
        up = q.upper()
        if up.startswith("CREATE DATABASE"):
            # CREATE DATABASE <name> OWNER <owner>
            name = q.split()[2]
            self.state["dbs"].add(name)
        if up.startswith("CREATE ROLE") or up.startswith("ALTER ROLE"):
            self.state["roles"].add(q.split()[2])
        return "OK"

    async def close(self):
        pass


def _install_fake_asyncpg(state):
    mod = types.ModuleType("asyncpg")

    async def connect(**kwargs):
        state["connects"].append(kwargs)
        return _FakeConn(state, kwargs)

    mod.connect = connect
    sys.modules["asyncpg"] = mod


class _Log:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


def _state(dbs=(), roles=()):
    return {"dbs": set(dbs), "roles": set(roles), "executed": [], "connects": []}


def _no_createdb_privilege(executed):
    """CREATEDB must never be granted — every 'CREATEDB' token must be part of 'NOCREATEDB'."""
    for stmt in executed:
        idx = 0
        while True:
            idx = stmt.upper().find("CREATEDB", idx)
            if idx == -1:
                break
            assert stmt.upper()[max(0, idx - 2):idx] == "NO", f"CREATEDB granted in: {stmt}"
            idx += 1


def test_fresh_install_creates_both_databases_owned_by_roofspan():
    st = _state()
    _install_fake_asyncpg(st)
    asyncio.run(db_bootstrap._ensure_role_and_db("superpw", "apppw", _Log()))
    ex = st["executed"]
    assert any("CREATE ROLE roofspan WITH LOGIN NOSUPERUSER NOCREATEDB" in s for s in ex)
    assert any(s.startswith("CREATE DATABASE roofspan OWNER roofspan") for s in ex)
    assert any(s.startswith("CREATE DATABASE roofspan_control_plane OWNER roofspan") for s in ex)
    assert {"roofspan", "roofspan_control_plane"} <= st["dbs"]
    _no_createdb_privilege(ex)
    # every DB operation went through the postgres superuser, never the runtime role
    assert all(c["user"] == "postgres" for c in st["connects"])


def test_existing_role_kept_and_forced_least_privilege():
    st = _state(dbs={"roofspan", "roofspan_control_plane"}, roles={"roofspan"})
    _install_fake_asyncpg(st)
    asyncio.run(db_bootstrap._ensure_role_and_db("superpw", "apppw", _Log()))
    ex = st["executed"]
    assert any("ALTER ROLE roofspan WITH LOGIN NOSUPERUSER NOCREATEDB" in s for s in ex)
    assert not any(s.startswith("CREATE ROLE") for s in ex)          # role kept, not recreated
    assert not any(s.startswith("CREATE DATABASE") for s in ex)      # both DBs already present
    _no_createdb_privilege(ex)


def test_repair_creates_missing_control_plane_db():
    st = _state(dbs={"roofspan"}, roles={"roofspan"})   # business DB present, CP DB missing
    _install_fake_asyncpg(st)
    created = asyncio.run(db_bootstrap._ensure_cp_db_only("superpw", _Log()))
    assert created is True
    assert any(s.startswith("CREATE DATABASE roofspan_control_plane OWNER roofspan") for s in st["executed"])
    assert "roofspan_control_plane" in st["dbs"]
    # repair must never create/alter the business DB or the role
    assert not any("CREATE DATABASE roofspan " in (s + " ") and "control_plane" not in s for s in st["executed"])
    assert all(c["user"] == "postgres" for c in st["connects"])


def test_repair_preserves_existing_cp_db_and_is_idempotent():
    st = _state(dbs={"roofspan", "roofspan_control_plane"}, roles={"roofspan"})
    _install_fake_asyncpg(st)
    created1 = asyncio.run(db_bootstrap._ensure_cp_db_only("superpw", _Log()))
    created2 = asyncio.run(db_bootstrap._ensure_cp_db_only("superpw", _Log()))
    assert created1 is False and created2 is False
    assert not any(s.startswith("CREATE DATABASE") for s in st["executed"])
