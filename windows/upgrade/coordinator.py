"""Transactional RoofSpan Office upgrade coordinator (runs elevated from the Burn bundle; resumes at boot).

Durable states (state.json is atomically replaced + fsynced on every transition, journal.log is append-only):

  PREFLIGHT -> BACKING_UP -> BACKUP_VERIFIED -> SERVICES_STOPPED -> INSTALLING -> MIGRATING -> STARTING
  -> HEALTH_CHECKING -> COMPLETE
  any failure before INSTALLING           -> restart previous services, previous-version health -> ROLLED_BACK
  any failure at/after INSTALLING         -> RESTORING -> ROLLED_BACK   (FAILED if recovery itself fails)

Resume (boot task or the next setup run) never continues forward: it always recovers to the previous version.
A database is restored ONLY from the verified backup created by the same attempt.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import secrets
import shutil
import time

import build_identity

from .pgops import (
    CP_DB,
    CP_SCHEMA,
    Conn,
    Pg,
    UpgradeError,
    parse_database_url,
    pg_bin_from_image_path,
    sha256_file,
)
from .winops import PG_SERVICE, SERVICES

STATES = ("PREFLIGHT", "BACKING_UP", "BACKUP_VERIFIED", "SERVICES_STOPPED", "INSTALLING", "MIGRATING",
          "STARTING", "HEALTH_CHECKING", "COMPLETE", "RESTORING", "ROLLED_BACK", "FAILED")
TERMINAL = ("COMPLETE", "ROLLED_BACK", "FAILED")
PRE_CHANGE = ("PREFLIGHT", "BACKING_UP", "BACKUP_VERIFIED", "SERVICES_STOPPED")
API = "http://127.0.0.1:8001"


def _fault(point: str) -> bool:
    """Fault injection exists only in CI test builds (embedded flag); production builds ignore the env var."""
    return bool(build_identity.FAULT_INJECTION) and os.environ.get("ROOFSPAN_UPGRADE_FAULT") == point


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StateStore:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.path = os.path.join(root, "state.json")
        self.journal = os.path.join(root, "journal.log")

    def load(self) -> dict | None:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def save(self, st: dict, note: str = "") -> None:
        st["updated_utc"] = _now()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        with open(self.journal, "a", encoding="utf-8") as f:
            f.write(json.dumps({"utc": st["updated_utc"], "attempt": st["attempt_id"], "state": st["state"],
                                "note": note}) + "\n")
            f.flush()
            os.fsync(f.fileno())


def _parse_env(path: str) -> dict:
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                out[k.strip()] = v.strip()
    return out


class Coordinator:
    def __init__(self, ops, data_root: str, install_root: str, log, decrypt_super=None, self_exe: str | None = None):
        self.ops, self.data_root, self.install_root, self.log = ops, data_root, install_root, log
        self.store = StateStore(os.path.join(data_root, "upgrade"))
        self.decrypt_super = decrypt_super
        self.self_exe = self_exe
        self.st: dict = {}

    # -- plumbing --------------------------------------------------------------------------------------
    def _to(self, state: str, note: str = "") -> None:
        assert state in STATES, state
        self.st["state"] = state
        self.st.setdefault("history", []).append({"state": state, "utc": _now()})
        self.store.save(self.st, note)
        self.log.info("upgrade %s: state=%s %s", self.st["attempt_id"], state, note)

    def _step_done(self, step: str) -> bool:
        return step in self.st.setdefault("steps_done", [])

    def _mark(self, step: str) -> None:
        self.st.setdefault("steps_done", []).append(step)
        self.store.save(self.st, f"step {step}")

    @property
    def config_path(self) -> str:
        return os.path.join(self.data_root, "config", "roofspan.env")

    @property
    def identity_dir(self) -> str:
        return os.path.join(self.data_root, "identity")

    def _exe(self, service: str) -> str:
        return os.path.join(self.install_root, "services", service, service + ".exe")

    def _pg(self) -> Pg:
        c = self.st["pg"]
        env = _parse_env(self.config_path) if os.path.isfile(self.config_path) else {}
        url = parse_database_url(env.get("DATABASE_URL", ""))
        if c["superuser"]:
            password = self.decrypt_super(os.path.join(self.identity_dir, "pg_super.bin"))
            conn = Conn(url["host"], url["port"], "postgres", password, "postgres", True)
        else:
            conn = Conn(url["host"], url["port"], url["user"], url["password"], url["dbname"], False)
        return Pg(conn, c["bin_dir"], self.st["backup_dir"], self.log)

    # -- entry points ------------------------------------------------------------------------------------
    def run(self, new_msi: str, target_version: str, previous_msi: str | None = None) -> str:
        prior = self.store.load()
        if prior and prior["state"] not in TERMINAL:
            self.log.info("upgrade: recovering interrupted attempt %s before starting", prior["attempt_id"])
            self.resume()
        self.st = {"attempt_id": _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d%H%M%S") + secrets.token_hex(2),
                   "target_version": target_version, "target_build_sha": build_identity.BUILD_SHA,
                   "new_msi": os.path.abspath(new_msi), "created_utc": _now()}
        try:
            self._to("PREFLIGHT")
            self._preflight(previous_msi)
            self._to("BACKING_UP")
            self._backup()
            self._verify_backup()
            self._to("BACKUP_VERIFIED")
            self._to("SERVICES_STOPPED")
            for s in SERVICES:
                if self.ops.service_status(s) not in (None, "stopped"):
                    raise UpgradeError(f"{s} is not stopped")
        except Exception as e:
            self._abort_before_change(e)
            return self.st["state"]
        try:
            self._to("INSTALLING")
            self._install()
            self._to("MIGRATING")
            self._migrate()
            if _fault("hang_after_migration"):
                time.sleep(24 * 3600)
            self._to("STARTING")
            for s in SERVICES:
                self.ops.start_service(s)
            self._to("HEALTH_CHECKING")
            self._health(self.st["target_version"], new=True)
            self.ops.set_coordinated_version(self.st["target_version"])
            self.ops.remove_recovery_task()
            self._to("COMPLETE")
        except Exception as e:
            self.st["error"] = str(e)[:2000]
            self.log.error("upgrade %s failed in %s: %s", self.st["attempt_id"], self.st["state"], self.st["error"])
            self._recover()
        return self.st["state"]

    def resume(self) -> str:
        st = self.store.load()
        if not st or st["state"] in TERMINAL:
            return st["state"] if st else "NONE"
        self.st = st
        self.log.info("upgrade %s: resuming from %s (recovery only)", st["attempt_id"], st["state"])
        if st["state"] in PRE_CHANGE:
            self._abort_before_change(UpgradeError(f"interrupted in {st['state']}"))
        else:
            self._recover()
        return self.st["state"]

    # -- PREFLIGHT ---------------------------------------------------------------------------------------
    def _preflight(self, previous_msi: str | None) -> None:
        if self.ops.service_status(PG_SERVICE) is None:
            raise UpgradeError("RoofSpanPostgreSQL service is not installed")
        if self.ops.service_status(PG_SERVICE) != "running":
            self.ops.start_service(PG_SERVICE)
        bin_dir = pg_bin_from_image_path(self.ops.service_image_path(PG_SERVICE) or "")
        if not os.path.isfile(self.config_path):
            raise UpgradeError("roofspan.env is missing; nothing to upgrade safely")
        env = _parse_env(self.config_path)
        url = parse_database_url(env.get("DATABASE_URL", ""))
        superuser = os.path.isfile(os.path.join(self.identity_dir, "pg_super.bin"))
        self.st["pg"] = {"bin_dir": bin_dir, "host": url["host"], "port": url["port"], "superuser": superuser,
                         "business_db": url["dbname"]}
        self.st["backup_dir"] = os.path.join(self.data_root, "upgrade-backups", self.st["attempt_id"])
        self.ops.protect_directory(self.st["backup_dir"])
        with self._pg() as pg:
            if pg.server_version_num() < 130000:
                raise UpgradeError("PostgreSQL is older than 13")
            biz = url["dbname"]
            pg.query("SELECT 1", dbname=biz)
            if superuser and pg.database_exists(CP_DB):
                cp_mode = "database"
            elif pg.schema_exists(biz, CP_SCHEMA):
                cp_mode = "legacy_schema"
            else:
                cp_mode = "none"
            dbs = [biz] + ([CP_DB] if cp_mode == "database" else [])
            need = sum(pg.database_size(d) for d in dbs)
        prev = self.ops.installed_product()
        if not prev:
            raise UpgradeError("RoofSpan Office is not installed; use a fresh install")
        msi = self._previous_msi(prev, previous_msi)
        need = int(need * 1.5) + os.path.getsize(msi) + 512 * 1024 * 1024
        free = self.ops.free_bytes(self.st["backup_dir"])
        if free < need:
            raise UpgradeError(f"not enough free disk space for a verified backup (need {need} bytes, have {free})")
        prev_id = {"version": prev["version"], "build_sha": "unknown"}
        bi = self.ops.run_exe([self._exe("roofspan-backend"), "--build-info"], timeout=60)
        if bi.returncode == 0 and bi.stdout.strip().startswith("{"):
            info = json.loads(bi.stdout.strip().splitlines()[-1])
            prev_id = {"version": info.get("version", prev["version"]), "build_sha": info.get("build_sha", "unknown")}
        self.st.update({"cp_mode": cp_mode, "databases": [{"name": d} for d in dbs],
                        "previous": {**prev_id, "product_code": prev["product_code"], "msi_source": msi}})
        if self.self_exe:
            keep = os.path.join(self.data_root, "upgrade", "bin")
            os.makedirs(keep, exist_ok=True)
            persistent = os.path.join(keep, "roofspan-upgrade.exe")
            shutil.copy2(self.self_exe, persistent)
            self.ops.register_recovery_task(persistent)
        self.store.save(self.st, "preflight ok")

    def _previous_msi(self, prev: dict, override: str | None) -> str:
        candidates = [override] if override else self.ops.package_cache_candidates(prev)
        for c in candidates:
            if not c or not os.path.isfile(c):
                continue
            p = self.ops.msi_properties(c)
            if p.get("ProductCode") == prev["product_code"] and p.get("ProductVersion") == prev["version"] \
                    and p.get("cabinets_present"):
                return c
        raise UpgradeError("the previous RoofSpan Office installer package (full MSI) is not available; rerun "
                           "RoofSpanSetup.exe with PREVIOUSMSI=<path to RoofSpanOffice-"
                           f"{prev['version']}.msi>")

    # -- BACKING_UP / BACKUP_VERIFIED ------------------------------------------------------------------------
    def _backup(self) -> None:
        for s in SERVICES:
            self.ops.stop_service(s)
        bdir = self.st["backup_dir"]
        msi_copy = os.path.join(bdir, "previous.msi")
        shutil.copy2(self.st["previous"]["msi_source"], msi_copy)
        self.st["previous"].update({"msi": msi_copy, "msi_sha256": sha256_file(msi_copy)})
        files = []
        for src in [self.config_path] + sorted(
                os.path.join(self.identity_dir, n) for n in (os.listdir(self.identity_dir)
                                                              if os.path.isdir(self.identity_dir) else [])):
            if not os.path.isfile(src) or src.endswith(".optionfile"):
                continue
            dst = os.path.join(bdir, "files", os.path.relpath(src, self.data_root))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            files.append({"path": src, "backup": dst, "sha256": sha256_file(dst), "sddl": self._sddl(src)})
        self.st["files"] = files
        with self._pg() as pg:
            biz = self.st["pg"]["business_db"]
            self.st["revisions"] = {"business": pg.alembic_revision(biz),
                                    "control_plane": (pg.alembic_revision(CP_DB, "public") if self.st["cp_mode"] == "database"
                                                      else pg.alembic_revision(biz, CP_SCHEMA)
                                                      if self.st["cp_mode"] == "legacy_schema" else None)}
            for d in self.st["databases"]:
                d["counts"] = pg.row_counts(d["name"])
                d["file"] = os.path.join(bdir, f"{d['name']}.dump")
                d["sha256"] = pg.dump(d["name"], d["file"])
                if _fault("backup_corrupt"):
                    with open(d["file"], "r+b") as f:
                        f.truncate(max(1, os.path.getsize(d["file"]) // 2))
                    d["sha256"] = sha256_file(d["file"])
        self.store.save(self.st, "backup written")

    def _sddl(self, path: str) -> str | None:
        try:
            return self.ops.file_sddl(path)
        except Exception:
            return None

    def _verify_backup(self) -> None:
        with self._pg() as pg:
            for d in self.st["databases"]:
                if sha256_file(d["file"]) != d["sha256"]:
                    raise UpgradeError(f"backup of {d['name']} changed after it was written")
                replay = pg.replay_counts(d["file"])
                if replay != d["counts"]:
                    raise UpgradeError(f"backup of {d['name']} does not contain every row (replay mismatch)")
                if self.st["pg"]["superuser"]:
                    scratch = f"rs_verify_{self.st['attempt_id']}"
                    pg.query(f'DROP DATABASE IF EXISTS "{scratch}"', dbname="postgres")
                    pg.query(f'CREATE DATABASE "{scratch}" TEMPLATE template0', dbname="postgres")
                    try:
                        pg.restore_into(d["file"], scratch, clean_single_tx=False)
                        if pg.row_counts(scratch) != d["counts"]:
                            raise UpgradeError(f"test restore of {d['name']} does not match the source")
                    finally:
                        pg.query(f'DROP DATABASE IF EXISTS "{scratch}"', dbname="postgres")
            for f in self.st["files"]:
                if sha256_file(f["backup"]) != f["sha256"]:
                    raise UpgradeError("configuration backup changed after it was written")
        if sha256_file(self.st["previous"]["msi"]) != self.st["previous"]["msi_sha256"]:
            raise UpgradeError("previous installer copy changed after it was written")
        manifest = {k: self.st[k] for k in ("attempt_id", "databases", "files", "revisions", "cp_mode", "previous")}
        manifest["verified"] = True
        with open(os.path.join(self.st["backup_dir"], "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        self.st["backup_verified"] = True

    # -- INSTALLING / MIGRATING / HEALTH ----------------------------------------------------------------------
    def _install(self) -> None:
        log = os.path.join(self.st["backup_dir"], "install-new.log")
        rc = self.ops.msiexec(["/i", self.st["new_msi"], "ROOFSPAN_COORDINATED=1"], log)
        if rc not in (0, 3010):
            raise UpgradeError(f"new MSI install failed (msiexec exit {rc}); see {log}")

    def _migrate(self) -> None:
        log = os.path.join(self.st["backup_dir"], "migrate.log")
        p = self.ops.run_exe([self._exe("roofspan-backend"), "--migrate", "--log", log], timeout=3 * 3600)
        self.st["migration"] = {"exit_code": p.returncode, "log": log}
        self.store.save(self.st, f"migration exit {p.returncode}")
        if p.returncode != 0:
            raise UpgradeError(f"database migration failed (exit {p.returncode}); see {log}")

    def _wait_http(self, path: str, timeout: int = 180) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            code, body = self.ops.http_get(API + path)
            if code == 200:
                return body
            time.sleep(3)
        raise UpgradeError(f"{path} did not respond with 200")

    def _health(self, version: str, new: bool) -> None:
        if _fault("health") and new:
            raise UpgradeError("injected health-check failure")
        checks = {}
        with self._pg() as pg:
            pg.query("SELECT 1", dbname=self.st["pg"]["business_db"])
        checks["postgresql"] = "ok"
        if new:
            p = self.ops.run_exe([self._exe("roofspan-backend"), "--schema-status"], timeout=300)
            status = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 and p.stdout.strip() else {}
            for tree in ("business", "control_plane"):
                t = status.get(tree) or {}
                if t.get("current") not in (t.get("heads") or []):
                    raise UpgradeError(f"{tree} schema is not at the expected head")
            checks["schema_heads"] = "ok"
        if self.ops.service_status("RoofSpanBackend") != "running":
            raise UpgradeError("RoofSpanBackend is not running")
        self._wait_http("/api/health")
        checks["api_health"] = "ok"
        ver = json.loads(self._wait_http("/api/version") or "{}")
        if version and ver.get("version") != version:
            raise UpgradeError(f"backend reports version {ver.get('version')}, expected {version}")
        if '<div id="root"' not in self._wait_http("/"):
            raise UpgradeError("Office UI is not being served")
        checks["office_ui"] = "ok"
        if new:
            log = os.path.join(self.data_root, "logs", "backend-service.log")
            text = open(log, encoding="utf-8", errors="replace").read() if os.path.isfile(log) else ""
            if f"licensing_software_version={version}" not in text:
                raise UpgradeError("licensing did not initialize with the new version")
            checks["licensing"] = "ok"
        self.ops.start_service("RoofSpanRelayConnector")
        time.sleep(15)
        if self.ops.service_status("RoofSpanRelayConnector") != "running":
            raise UpgradeError("RoofSpanRelayConnector did not stay running")
        checks["relay"] = "ok"
        self.st["health_" + ("new" if new else "previous")] = checks

    # -- recovery ----------------------------------------------------------------------------------------
    def _abort_before_change(self, err: Exception) -> None:
        self.st["error"] = str(err)[:2000]
        self.log.error("upgrade %s stopped before any change: %s", self.st.get("attempt_id"), self.st["error"])
        try:
            for s in SERVICES:
                self.ops.start_service(s)
            prev = self.st.get("previous", {})
            self._health(prev.get("version", "") if prev.get("build_sha") != "unknown" else "", new=False)
            self.ops.remove_recovery_task()
            self._to("ROLLED_BACK", "no changes were made")
        except Exception as e2:
            self.st["recovery_error"] = str(e2)[:2000]
            self._to("FAILED", "previous services did not come back")

    def _recover(self) -> None:
        self._to("RESTORING")
        try:
            if not self.st.get("backup_verified"):
                raise UpgradeError("no verified backup for this attempt; refusing to restore")
            with open(os.path.join(self.st["backup_dir"], "manifest.json"), encoding="utf-8") as f:
                manifest = json.load(f)
            if manifest.get("attempt_id") != self.st["attempt_id"] or manifest.get("verified") is not True:
                raise UpgradeError("backup manifest does not belong to this attempt; refusing to restore")
            for s in SERVICES:
                self.ops.stop_service(s)
            prev = self.st["previous"]
            installed = self.ops.installed_product()
            if not self._step_done("remove_new") and installed and installed["version"] != prev["version"]:
                rc = self.ops.msiexec(["/x", installed["product_code"], "ROOFSPAN_COORDINATED=1"],
                                      os.path.join(self.st["backup_dir"], "uninstall-new.log"))
                if rc not in (0, 3010, 1605):
                    raise UpgradeError(f"could not remove the new version (msiexec exit {rc})")
            if not self._step_done("remove_new"):
                self._mark("remove_new")
            with self._pg() as pg:
                for d in self.st["databases"]:
                    step = f"restore_db:{d['name']}"
                    if not self._step_done(step):
                        self._restore_db(pg, d)
                        self._mark(step)
            if not self._step_done("restore_files"):
                for f in self.st["files"]:
                    self._restore_file(f)
                self._mark("restore_files")
            installed = self.ops.installed_product()
            if not installed or installed["version"] != prev["version"]:
                rc = self.ops.msiexec(["/i", prev["msi"]], os.path.join(self.st["backup_dir"], "reinstall-previous.log"))
                if rc not in (0, 3010):
                    raise UpgradeError(f"could not reinstall the previous version (msiexec exit {rc})")
            for s in SERVICES:
                self.ops.start_service(s)
            # Builds before the immutable build identity may report a stale config version; only compare
            # the reported version when the previous build exposed --build-info.
            self._health(prev["version"] if prev.get("build_sha") != "unknown" else "", new=False)
            self.ops.remove_recovery_task()
            self._to("ROLLED_BACK", "previous version, data and configuration restored")
        except Exception as e:
            self.st["recovery_error"] = str(e)[:2000]
            self.log.error("upgrade %s recovery FAILED: %s (backup kept at %s)", self.st["attempt_id"],
                           self.st["recovery_error"], self.st.get("backup_dir"))
            self._to("FAILED", "manual recovery required; verified backup retained")

    def _restore_db(self, pg: Pg, d: dict) -> None:
        name, attempt = d["name"], self.st["attempt_id"]
        if pg.conn.superuser:
            restored, failed = f"{name}_restore_{attempt}", f"{name}_failed_{attempt}"
            if not pg.database_exists(failed):
                owner = pg.query("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s", (name,),
                                 dbname="postgres")[0][0]
                pg.query(f'DROP DATABASE IF EXISTS "{restored}"', dbname="postgres")
                pg.query(f'CREATE DATABASE "{restored}" OWNER "{owner}" TEMPLATE template0', dbname="postgres")
                pg.restore_into(d["file"], restored, clean_single_tx=False)
                if pg.row_counts(restored) != d["counts"]:
                    raise UpgradeError(f"restored copy of {name} does not match the verified backup")
                pg.terminate_connections(name)
                pg.query(f'ALTER DATABASE "{name}" RENAME TO "{failed}"', dbname="postgres")
            if pg.database_exists(restored):
                pg.query(f'ALTER DATABASE "{restored}" RENAME TO "{name}"', dbname="postgres")
        else:
            schemas = sorted({k.split(".", 1)[0] for k in d["counts"]} | {"public"})
            pg.replace_schemas_from_archive(d["file"], name, schemas)
        if pg.row_counts(name) != d["counts"]:
            raise UpgradeError(f"{name} does not match the verified backup after restore")

    def _restore_file(self, f: dict) -> None:
        existed = os.path.exists(f["path"])
        os.makedirs(os.path.dirname(f["path"]), exist_ok=True)
        with open(f["backup"], "rb") as src, open(f["path"], "r+b" if existed else "wb") as dst:
            data = src.read()
            dst.seek(0)
            dst.write(data)
            dst.truncate()
            dst.flush()
            os.fsync(dst.fileno())
        if not existed and f.get("sddl"):
            self.ops.apply_sddl(f["path"], f["sddl"])
        if sha256_file(f["path"]) != f["sha256"]:
            raise UpgradeError("restored configuration file does not match its backup")
