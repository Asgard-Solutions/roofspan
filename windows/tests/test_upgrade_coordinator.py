"""Transactional upgrade coordinator against a REAL disposable PostgreSQL cluster (Linux CI / dev).

Windows-native operations (services, msiexec, ACLs, scheduled task) are faked here and exercised for real by
the `transactional-upgrade` Windows job. Requires ROOFSPAN_UPGRADE_TEST_PG="host:port:superpassword" pointing
at a DISPOSABLE cluster: databases roofspan / roofspan_control_plane are dropped and recreated.
"""
import json
import logging
import os
import shutil
import sys
from pathlib import Path

import pytest

WINDOWS = Path(__file__).resolve().parents[1]
for p in (str(WINDOWS), str(WINDOWS / "winbuild")):
    if p not in sys.path:
        sys.path.insert(0, p)

import build_identity
from upgrade import coordinator as co
from upgrade.coordinator import Coordinator

PG = os.environ.get("ROOFSPAN_UPGRADE_TEST_PG", "")
pytestmark = pytest.mark.skipif(not PG or not shutil.which("pg_dump"), reason="needs a disposable PostgreSQL")
APP_PW = "App:Pw@ss%w0rd/9"
PREV, NEW = "0.4.8", "0.4.9"


def _host():
    h, port, pw = PG.split(":", 2)
    return h, int(port), pw


def _cx(db, user="postgres", pw=None):
    import psycopg
    h, port, spw = _host()
    return psycopg.connect(host=h, port=port, user=user, password=pw or spw, dbname=db, autocommit=True)


def _seed(legacy: bool):
    with _cx("postgres") as c:
        for d in ("roofspan", "roofspan_control_plane"):
            c.execute(f"DROP DATABASE IF EXISTS {d} WITH (FORCE)")
        for (name,) in c.execute("SELECT datname FROM pg_database WHERE datname LIKE 'roofspan_%%' "
                                 "OR datname LIKE 'rs_verify_%%'").fetchall():
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        c.execute("DROP ROLE IF EXISTS roofspan")
        c.execute(f"CREATE ROLE roofspan LOGIN PASSWORD '{APP_PW}' NOCREATEDB NOSUPERUSER")
        c.execute("CREATE DATABASE roofspan OWNER roofspan")
        if not legacy:
            c.execute("CREATE DATABASE roofspan_control_plane OWNER roofspan")
    with _cx("roofspan") as c:
        c.execute("ALTER SCHEMA public OWNER TO roofspan")
    with _cx("roofspan", "roofspan", APP_PW) as c:
        c.execute("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
        c.execute("INSERT INTO alembic_version VALUES ('rev_old')")
        c.execute("CREATE TABLE customers (id serial PRIMARY KEY, name text, note text)")
        c.execute("INSERT INTO customers (name, note) SELECT 'sentinel-' || g, E'line1\\nline2\\ttab' "
                  "FROM generate_series(1, 250) g")
        if legacy:
            c.execute("CREATE SCHEMA roofspan_control_plane")
            c.execute("CREATE TABLE roofspan_control_plane.alembic_version (version_num varchar(32) PRIMARY KEY)")
            c.execute("INSERT INTO roofspan_control_plane.alembic_version VALUES ('cp_old')")
            c.execute("CREATE TABLE roofspan_control_plane.installations (id int PRIMARY KEY)")
            c.execute("INSERT INTO roofspan_control_plane.installations VALUES (1), (2)")
    if not legacy:
        with _cx("roofspan_control_plane") as c:
            c.execute("ALTER SCHEMA public OWNER TO roofspan")
        with _cx("roofspan_control_plane", "roofspan", APP_PW) as c:
            c.execute("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
            c.execute("INSERT INTO alembic_version VALUES ('cp_old')")
            c.execute("CREATE TABLE installations (id int PRIMARY KEY)")
            c.execute("INSERT INTO installations VALUES (1)")


def _snapshot():
    with _cx("roofspan") as c:
        rev = c.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        rows = c.execute("SELECT id, name, note FROM customers ORDER BY id").fetchall()
        tables = sorted(r[0] for r in c.execute(
            "SELECT table_schema||'.'||table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog','information_schema')"))
    return rev, rows, tables


class FakeOps:
    def __init__(self, root: Path, fail: dict):
        self.root, self.fail = root, fail
        self.services = {"RoofSpanPostgreSQL": "running", "RoofSpanBackend": "running",
                         "RoofSpanRelayConnector": "running", "RoofSpanUpdateService": "running"}
        self.installed = {"product_code": "{PREV}", "version": PREV}
        self.calls, self.tasks = [], set()
        self.bindir = Path(shutil.which("pg_dump")).parent   # the real tools (with their DLLs on Windows)
        self.prev_msi = root / "cache" / "RoofSpanOffice-0.4.8.msi"
        self.prev_msi.parent.mkdir()
        self.prev_msi.write_bytes(b"previous msi with cab")

    def service_status(self, n):
        return self.services.get(n)

    def service_image_path(self, n):
        return f'"{self.bindir}/pg_ctl.exe" runservice -N "{n}" -D "C:\\data"'

    def stop_service(self, n):
        if n in self.services:
            self.services[n] = "stopped"

    def start_service(self, n):
        self.services[n] = "running"
        if n == "RoofSpanBackend":
            log = self.root / "data" / "logs" / "backend-service.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a") as f:
                f.write(f"backend: build identity licensing_software_version={self.installed['version']}\n")

    def msiexec(self, args, log):
        self.calls.append(args[:2])
        if args[0] == "/i" and args[1].endswith("new.msi"):
            if self.fail.get("msi"):
                return 1603
            self.installed = {"product_code": "{NEW}", "version": NEW}
        elif args[0] == "/x":
            self.installed = None
        elif args[0] == "/i":
            self.installed = {"product_code": "{PREV}", "version": PREV}
        return 0

    def installed_product(self):
        return dict(self.installed) if self.installed else None

    def msi_properties(self, path):
        return {"ProductCode": "{PREV}", "ProductVersion": PREV, "cabinets_present": True}

    def package_cache_candidates(self, product):
        return [str(self.prev_msi)]

    def free_bytes(self, path):
        return self.fail.get("free", 10 ** 12)

    def protect_directory(self, path):
        os.makedirs(path, exist_ok=True)

    def file_sddl(self, path):
        return "D:P(A;;FA;;;SY)"

    def apply_sddl(self, path, sddl):
        pass

    def register_recovery_task(self, exe):
        self.tasks.add(exe)

    def remove_recovery_task(self):
        self.tasks.clear()

    def set_coordinated_version(self, v):
        self.coordinated = v

    def http_get(self, url, timeout=10):
        if self.services["RoofSpanBackend"] != "running" or not self.installed:
            return 0, ""
        if url.endswith("/api/version"):
            return 200, json.dumps({"version": self.installed["version"]})
        return 200, '<html><div id="root"></div></html>' if url.endswith("/") else "{}"

    def run_exe(self, args, timeout=0):
        import subprocess
        if "--build-info" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps({"version": PREV, "build_sha": "p" * 40}), "")
        if "--migrate" in args:
            with _cx("roofspan", "roofspan", APP_PW) as c:      # forward schema change on real data
                c.execute("CREATE TABLE new_feature (id int)")
                c.execute("ALTER TABLE customers ADD COLUMN migrated boolean DEFAULT true")
                c.execute("UPDATE alembic_version SET version_num='rev_new'")
            cfg = self.root / "data" / "config" / "roofspan.env"
            cfg.write_text(cfg.read_text() + "NEW_ONLY_SETTING=1\n")
            if self.fail.get("crash_after_migration"):
                raise KeyboardInterrupt("simulated power loss")
            return subprocess.CompletedProcess(args, 1 if self.fail.get("migration") else 0, "", "")
        if "--schema-status" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps(
                {"business": {"current": "rev_new", "heads": ["rev_new"]},
                 "control_plane": {"current": "cp_old", "heads": ["cp_old"]}}), "")
        raise AssertionError(args)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    def make(legacy=False, **fail):
        _seed(legacy)
        h, port, spw = _host()
        data = tmp_path / "data"
        (data / "config").mkdir(parents=True)
        (data / "identity").mkdir()
        from urllib.parse import quote
        cfg = (f"DATABASE_URL=postgresql+asyncpg://roofspan:{quote(APP_PW, safe='')}@{h}:{port}/roofspan\n"
               "JWT_SECRET=jwt-sentinel-secret\nSECRETS_ENCRYPTION_KEY=enc-sentinel-key\n")
        (data / "config" / "roofspan.env").write_text(cfg)
        (data / "identity" / "installation.key").write_bytes(b"installation-identity-sentinel")
        if not legacy:
            (data / "identity" / "pg_super.bin").write_bytes(b"dpapi-blob")
        ops = FakeOps(tmp_path, fail)
        (tmp_path / "new.msi").write_bytes(b"new")
        monkeypatch.setattr(build_identity, "FAULT_INJECTION", True)
        for k, v in fail.items():
            if k in ("health", "backup_corrupt"):
                monkeypatch.setenv("ROOFSPAN_UPGRADE_FAULT", k)
        logger = logging.getLogger(f"upgrade-test-{id(ops)}")
        logger.handlers[:] = [logging.FileHandler(tmp_path / "upgrade.log")]
        logger.setLevel(logging.INFO)
        (tmp_path / "roofspan-upgrade.exe").write_bytes(b"exe")
        c = Coordinator(ops, str(data), str(tmp_path / "install"), logger, decrypt_super=lambda p: spw,
                        self_exe=str(tmp_path / "roofspan-upgrade.exe"))
        monkeypatch.setattr(co.time, "sleep", lambda s: None)
        return c, ops, data, cfg
    return make


def _secrets_absent(tmp_path, data):
    _, _, spw = _host()
    blobs = [tmp_path / "upgrade.log"] + list((data / "upgrade").glob("*"))
    for b in blobs:
        if b.is_file():
            text = b.read_text(errors="replace")
            for s in (APP_PW, spw, "jwt-sentinel-secret", "enc-sentinel-key"):
                assert s not in text, f"secret leaked into {b.name}"
    assert not list(data.rglob("pgpass.conf"))


def test_successful_upgrade_preserves_sentinel_data_and_config(env, tmp_path):
    c, ops, data, cfg = env()
    before = _snapshot()
    assert c.run(str(tmp_path / "new.msi"), NEW) == "COMPLETE"
    rev, rows, tables = _snapshot()
    assert rev == "rev_new" and [r[:3] for r in rows] == [r[:3] for r in before[1]]
    assert ops.installed["version"] == NEW and not ops.tasks
    st = json.loads((data / "upgrade" / "state.json").read_text())
    assert [h["state"] for h in st["history"]] == ["PREFLIGHT", "BACKING_UP", "BACKUP_VERIFIED", "SERVICES_STOPPED",
                                                  "INSTALLING", "MIGRATING", "STARTING", "HEALTH_CHECKING", "COMPLETE"]
    manifest = json.loads((Path(st["backup_dir"]) / "manifest.json").read_text())
    assert manifest["verified"] is True and manifest["attempt_id"] == st["attempt_id"]
    assert {d["name"] for d in manifest["databases"]} == {"roofspan", "roofspan_control_plane"}
    _secrets_absent(tmp_path, data)


@pytest.mark.parametrize("legacy", [False, True])
def test_forced_migration_failure_restores_schema_data_config_and_version(env, tmp_path, legacy):
    c, ops, data, cfg = env(legacy=legacy, migration=True)
    before = _snapshot()
    assert c.run(str(tmp_path / "new.msi"), NEW) == "ROLLED_BACK"
    assert _snapshot() == before                                       # schema + data + revision restored
    assert (data / "config" / "roofspan.env").read_text() == cfg       # configuration restored byte-for-byte
    assert ops.installed["version"] == PREV and all(ops.services[s] == "running" for s in ops.services)
    st = json.loads((data / "upgrade" / "state.json").read_text())
    assert st["health_previous"]["api_health"] == "ok" and "RESTORING" in [h["state"] for h in st["history"]]
    with _cx("postgres") as cx:
        failed = [r[0] for r in cx.execute("SELECT datname FROM pg_database WHERE datname LIKE '%%_failed_%%'")]
    assert bool(failed) == (not legacy)                                # failed DB kept (renamed), never dropped
    _secrets_absent(tmp_path, data)


def test_unverifiable_backup_stops_before_install_or_migration(env, tmp_path):
    c, ops, data, _ = env(backup_corrupt=True)
    before = _snapshot()
    assert c.run(str(tmp_path / "new.msi"), NEW) == "ROLLED_BACK"
    assert ops.calls == [] and _snapshot() == before and ops.installed["version"] == PREV
    st = json.loads((data / "upgrade" / "state.json").read_text())
    assert "not fully readable" in st["error"] or "does not contain every row" in st["error"]
    assert "INSTALLING" not in [h["state"] for h in st["history"]]


def test_insufficient_disk_space_stops_in_preflight(env, tmp_path):
    c, ops, _, _ = env(free=1)
    assert c.run(str(tmp_path / "new.msi"), NEW) == "ROLLED_BACK" and ops.calls == []


def test_failed_health_check_triggers_recovery(env, tmp_path):
    c, ops, data, cfg = env(health=True)
    before = _snapshot()
    assert c.run(str(tmp_path / "new.msi"), NEW) == "ROLLED_BACK"
    assert _snapshot() == before and ops.installed["version"] == PREV


def test_interrupted_upgrade_resumes_into_recovery_idempotently(env, tmp_path):
    c, ops, data, cfg = env(crash_after_migration=True)
    before = _snapshot()
    with pytest.raises(KeyboardInterrupt):
        c.run(str(tmp_path / "new.msi"), NEW)
    st = json.loads((data / "upgrade" / "state.json").read_text())
    assert st["state"] == "MIGRATING" and ops.tasks                     # boot recovery task still registered
    first_backup = Path(st["backup_dir"])
    manifest_bytes = (first_backup / "manifest.json").read_bytes()
    assert c.resume() == "ROLLED_BACK" and _snapshot() == before
    assert c.resume() == "ROLLED_BACK"                                  # second resume is a no-op
    ops.fail.pop("crash_after_migration")
    assert c.run(str(tmp_path / "new.msi"), NEW) == "COMPLETE"          # later attempt: new backup folder
    assert (first_backup / "manifest.json").read_bytes() == manifest_bytes
