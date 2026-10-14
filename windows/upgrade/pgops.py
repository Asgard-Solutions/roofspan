"""PostgreSQL operations for the transactional upgrade: discovery, custom-format backup, verification, restore.

Secrets never appear on a command line or in a log: passwords go to a PGPASSFILE inside the protected
attempt directory (deleted afterwards) and every captured tool message is redacted before logging.
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

CP_DB = "roofspan_control_plane"
CP_SCHEMA = "roofspan_control_plane"
_SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")


class UpgradeError(RuntimeError):
    """A failure with an operator-safe message (never contains secrets)."""


@dataclass
class Conn:
    host: str
    port: int
    user: str
    password: str
    dbname: str
    superuser: bool

    def with_db(self, dbname: str) -> Conn:
        return Conn(self.host, self.port, self.user, self.password, dbname, self.superuser)


def parse_database_url(url: str) -> dict:
    u = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if u.scheme != "postgresql" or not u.hostname or not u.username or not u.path.strip("/"):
        raise UpgradeError("DATABASE_URL in roofspan.env is not a usable PostgreSQL URL")
    return {"host": u.hostname, "port": u.port or 5432, "user": unquote(u.username),
            "password": unquote(u.password or ""), "dbname": u.path.lstrip("/")}


def pg_bin_from_image_path(image_path: str) -> str:
    """`"C:\\...\\bin\\pg_ctl.exe" runservice -N ... -D ...` -> the bin directory holding pg_dump."""
    image_path = (image_path or "").strip()
    if image_path.startswith('"'):
        exe = image_path[1:image_path.index('"', 1)]
    else:
        exe = shlex.split(image_path, posix=False)[0] if image_path else ""
    if not exe.lower().endswith("pg_ctl.exe"):
        raise UpgradeError("RoofSpanPostgreSQL service image path is not pg_ctl.exe")
    return os.path.dirname(exe)


def redact(text: str, secrets) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return re.sub(r"(postgres(?:ql)?(?:\+asyncpg)?://[^:/@\s]+:)[^@\s]+@", r"\1***@", text)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Pg:
    def __init__(self, conn: Conn, bin_dir: str, work_dir: str, log):
        self.conn, self.bin_dir, self.work_dir, self.log = conn, bin_dir, work_dir, log
        self._passfile = os.path.join(work_dir, "pgpass.conf")

    def __enter__(self):
        with open(self._passfile, "w", encoding="ascii", newline="\n") as f:
            esc = self.conn.password.replace("\\", "\\\\").replace(":", "\\:")
            f.write(f"{self.conn.host}:{self.conn.port}:*:{self.conn.user}:{esc}\n")
        try:
            os.chmod(self._passfile, 0o600)
        except OSError:
            pass
        return self

    def __exit__(self, *exc):
        try:
            os.remove(self._passfile)
        except FileNotFoundError:
            pass

    # -- SQL ------------------------------------------------------------------------------------------
    def connect(self, dbname: str | None = None, autocommit: bool = True):
        import psycopg
        c = self.conn
        return psycopg.connect(host=c.host, port=c.port, user=c.user, password=c.password,
                               dbname=dbname or c.dbname, connect_timeout=10, autocommit=autocommit)

    def query(self, sql: str, params=(), dbname: str | None = None):
        with self.connect(dbname) as cx:
            cur = cx.execute(sql, params)
            return cur.fetchall() if cur.description else []

    def database_exists(self, name: str) -> bool:
        return bool(self.query("SELECT 1 FROM pg_database WHERE datname=%s", (name,), dbname="postgres"
                               if self.conn.superuser else None))

    def schema_exists(self, dbname: str, schema: str) -> bool:
        return bool(self.query("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,), dbname=dbname))

    def database_size(self, dbname: str) -> int:
        return int(self.query("SELECT pg_database_size(%s)", (dbname,), dbname=dbname)[0][0])

    def server_version_num(self) -> int:
        return int(self.query("SHOW server_version_num")[0][0])

    def row_counts(self, dbname: str) -> dict:
        tables = self.query(
            "SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE c.relkind IN ('r','p') AND NOT (n.nspname = ANY(%s)) AND n.nspname NOT LIKE 'pg_temp%%' "
            "ORDER BY 1,2", (list(_SYSTEM_SCHEMAS),), dbname=dbname)
        from psycopg import sql as S
        out = {}
        with self.connect(dbname) as cx:
            for schema, table in tables:
                q = S.SQL("SELECT count(*) FROM {}.{}").format(S.Identifier(schema), S.Identifier(table))
                out[f"{schema}.{table}"] = int(cx.execute(q).fetchone()[0])
        return out

    def alembic_revision(self, dbname: str, schema: str = "public"):
        try:
            rows = self.query(f'SELECT version_num FROM "{schema}".alembic_version', dbname=dbname)
        except Exception:
            return None
        return rows[0][0] if len(rows) == 1 else None

    def terminate_connections(self, dbname: str) -> None:
        self.query("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()",
                   (dbname,), dbname="postgres")

    # -- tools ----------------------------------------------------------------------------------------
    def _tool(self, name: str) -> str:
        exe = os.path.join(self.bin_dir, name + (".exe" if os.name == "nt" else ""))
        if not os.path.isfile(exe):
            raise UpgradeError(f"PostgreSQL tool {name} not found in the service's bin directory")
        return exe

    def _env(self):
        env = dict(os.environ, PGPASSFILE=self._passfile, PGCONNECT_TIMEOUT="10")
        env.pop("PGPASSWORD", None)
        return env

    def _base(self, dbname: str) -> list:
        c = self.conn
        return ["-h", c.host, "-p", str(c.port), "-U", c.user, "-d", dbname, "--no-password"]

    def run(self, name: str, args: list, what: str, stdout=None) -> None:
        p = subprocess.run([self._tool(name)] + args, env=self._env(), stdout=stdout or subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=6 * 3600, check=False)
        err = redact((p.stderr or b"").decode("utf-8", "replace"), [self.conn.password])[-2000:]
        if p.returncode != 0:
            raise UpgradeError(f"{what} failed ({name} exit {p.returncode}): {err.strip()}")

    def dump(self, dbname: str, path: str) -> str:
        partial = path + ".partial"
        self.run("pg_dump", self._base(dbname) + ["-Fc", "-Z", "6", "-f", partial], f"backup of {dbname}")
        with open(partial, "rb+") as f:
            os.fsync(f.fileno())
        os.replace(partial, path)
        return sha256_file(path)

    def replay_counts(self, path: str) -> dict:
        """Stream the WHOLE archive through pg_restore (no database) and count COPY rows per table."""
        p = subprocess.Popen([self._tool("pg_restore"), "-f", "-", path], env=self._env(),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        counts, current = {}, None
        copy_re = re.compile(r'^COPY ("?[^".\s]+"?)\.("?[^".\s]+"?) .* FROM stdin;$')
        for raw in p.stdout:
            line = raw.rstrip(b"\r\n")
            if current is None:
                m = copy_re.match(line.decode("utf-8", "replace"))
                if m:
                    current = f"{m.group(1).strip(chr(34))}.{m.group(2).strip(chr(34))}"
                    counts[current] = 0
            elif line == b"\\.":
                current = None
            else:
                counts[current] += 1
        err = p.stderr.read().decode("utf-8", "replace")
        if p.wait() != 0:
            raise UpgradeError(f"backup archive is not fully readable: {redact(err, [self.conn.password])[-500:]}")
        return counts

    def restore_into(self, path: str, dbname: str, clean_single_tx: bool) -> None:
        args = self._base(dbname) + ["--exit-on-error"]
        if clean_single_tx:
            args += ["--clean", "--if-exists", "--single-transaction"]
        self.run("pg_restore", args + [path], f"restore into {dbname}")

    def replace_schemas_from_archive(self, path: str, dbname: str, schemas: list) -> None:
        """Legacy (owner, no superuser): drop + recreate the dumped schemas and replay the archive in ONE
        transaction (psql --single-transaction, ON_ERROR_STOP). Any error leaves the database unchanged."""
        sql_path = os.path.join(self.work_dir, f"restore-{dbname}.sql")
        with open(sql_path, "wb") as out:
            out.writelines(f'DROP SCHEMA IF EXISTS "{s}" CASCADE;\n'.encode() for s in schemas)
            out.write(b'CREATE SCHEMA IF NOT EXISTS "public";\n')
            out.flush()
            self.run("pg_restore", ["-f", "-", path], "archive replay", stdout=out)
        try:
            self.run("psql", self._base(dbname) + ["-X", "-q", "-v", "ON_ERROR_STOP=1", "--single-transaction",
                                                  "-f", sql_path], f"restore of {dbname}")
        finally:
            os.remove(sql_path)
