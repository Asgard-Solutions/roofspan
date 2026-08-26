r"""First-install local PostgreSQL bootstrap for the RoofSpanBackend Windows service.

Runs INSIDE the backend service, BEFORE `server`/`backend.db` are imported. On a brand-new machine it:

  1. waits until PostgreSQL accepts local connections;
  2. decrypts the EDB superuser secret from DPAPI;
  3. provisions the least-privilege `roofspan` role + database;
  4. writes C:\ProgramData\RoofSpan\config\roofspan.env from the installed template;
  5. generates and persists the local JWT + application-secret encryption keys;
  6. loads the installed config before the backend app imports.

Existing provisioned configs are preserved. If an older installed roofspan.env is missing the runtime
secrets introduced later, bootstrap repairs only those missing keys atomically without rotating the DB
credential or touching customer data. Secrets are never logged.

Legacy installs created before pg_super.bin was introduced cannot create the separate Control Plane
database because the runtime `roofspan` role is intentionally NOCREATEDB. For those installs only,
bootstrap uses an isolated `roofspan_control_plane` schema inside the existing RoofSpan business database.
This keeps the runtime role least-privileged and repairs Mobile Access without resetting PostgreSQL auth.
"""
from __future__ import annotations

import base64
import os
import re
import secrets
import string
import time
import traceback

PLACEHOLDER = "__GENERATED_AT_FIRST_RUN__"
JWT_PLACEHOLDER = "__GENERATED_JWT_SECRET__"
SECRETS_KEY_PLACEHOLDER = "__GENERATED_SECRETS_ENCRYPTION_KEY__"
SUPERUSER = "postgres"
APP_ROLE = "roofspan"
APP_DB = "roofspan"
CP_DB = "roofspan_control_plane"  # dedicated embedded Control Plane DB for normal/fresh installs
CP_SCHEMA = "roofspan_control_plane"  # isolated schema fallback for legacy installs with no pg_super.bin
PG_HOST = "127.0.0.1"
PG_PORT = 5432


def generate_db_password(exclude: str = "") -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(32))
        if pw != exclude and any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def generate_jwt_secret() -> str:
    # URL-safe high-entropy signing secret; persisted locally so existing sessions/tokens survive restarts.
    return secrets.token_urlsafe(48)


def generate_secrets_encryption_key() -> str:
    # core._enc_key expects urlsafe-base64-decoded AES-256 material.
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def render_env_from_template(template_text: str, app_password: str) -> str:
    return (
        template_text
        .replace(PLACEHOLDER, app_password)
        .replace(JWT_PLACEHOLDER, generate_jwt_secret())
        .replace(SECRETS_KEY_PLACEHOLDER, generate_secrets_encryption_key())
    )


def _database_url(password: str) -> str:
    return f"postgresql+asyncpg://{APP_ROLE}:{password}@{PG_HOST}:{PG_PORT}/{APP_DB}"


def parse_generated_password(config_text: str):
    m = re.search(r"DATABASE_URL=postgresql\+asyncpg://roofspan:([^@]+)@", config_text)
    if not m:
        return None
    pw = m.group(1)
    if not pw or pw == PLACEHOLDER:
        return None
    return pw


def config_is_provisioned(config_path: str) -> bool:
    if not os.path.isfile(config_path):
        return False
    return parse_generated_password(_read(config_path)) is not None


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def _parse_env_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _write_atomic(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def ensure_required_runtime_secrets(config_path: str, logger) -> None:
    """Backfill missing per-installation app secrets without rotating anything that already exists."""
    text = _read(config_path)
    values = _parse_env_text(text)
    additions: list[str] = []

    jwt_secret = values.get("JWT_SECRET", "")
    if not jwt_secret or jwt_secret == JWT_PLACEHOLDER:
        additions.append(f"JWT_SECRET={generate_jwt_secret()}")

    encryption_key = values.get("SECRETS_ENCRYPTION_KEY", "")
    if not encryption_key or encryption_key == SECRETS_KEY_PLACEHOLDER:
        additions.append(f"SECRETS_ENCRYPTION_KEY={generate_secrets_encryption_key()}")

    if additions:
        repaired = text.rstrip("\r\n") + "\n\n# Per-installation application secrets (generated locally; never shipped).\n" + "\n".join(additions) + "\n"
        _write_atomic(config_path, repaired)
        logger.info("bootstrap: repaired missing local application secrets in roofspan.env")


def _load_env_file_into_process(config_path: str) -> None:
    for line in _read(config_path).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()


def decrypt_super_password(pg_super_bin: str) -> str:
    import win32crypt
    with open(pg_super_bin, "rb") as f:
        blob = f.read()
    _desc, data = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
    return data.decode("utf-8")


async def _create_db_if_missing(conn, db_name: str, owner: str, logger) -> bool:
    """Create `db_name` OWNED BY `owner` if absent. Returns True if it was created. The CREATE runs on
    the SUPERUSER connection, so the runtime `roofspan` role never needs CREATEDB."""
    exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", db_name)
    if exists:
        logger.info("bootstrap: database '%s' already exists (kept)", db_name)
        return False
    await conn.execute(f'CREATE DATABASE {db_name} OWNER {owner}')
    logger.info("bootstrap: created database '%s' owned by '%s'", db_name, owner)
    return True


async def _own_public_schema(super_password: str, db_name: str, owner: str) -> None:
    """Ensure `owner` owns the public schema of `db_name` (PG15+ locks it down for non-owners)."""
    import asyncpg

    conn = await asyncpg.connect(user=SUPERUSER, password=super_password,
                                 host=PG_HOST, port=PG_PORT, database=db_name)
    try:
        await conn.execute(f'GRANT ALL ON DATABASE {db_name} TO {owner}')
        await conn.execute(f'ALTER SCHEMA public OWNER TO {owner}')
    finally:
        await conn.close()


async def _ensure_role_and_db(super_password: str, app_password: str, logger) -> None:
    import asyncpg

    conn = await asyncpg.connect(user=SUPERUSER, password=super_password,
                                 host=PG_HOST, port=PG_PORT, database="postgres")
    try:
        quoted_pw = await conn.fetchval("SELECT quote_literal($1)", app_password)
        role_exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", APP_ROLE)
        if role_exists:
            logger.info("bootstrap: role '%s' already exists (kept)", APP_ROLE)
            # Explicitly enforce least privilege (revokes CREATEDB/SUPERUSER if a prior build granted them).
            await conn.execute(f"ALTER ROLE {APP_ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB PASSWORD {quoted_pw}")
        else:
            await conn.execute(f"CREATE ROLE {APP_ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB PASSWORD {quoted_pw}")
            logger.info("bootstrap: created least-privilege role '%s'", APP_ROLE)
        # Both databases are created BY the superuser and OWNED BY the least-privilege roofspan role.
        await _create_db_if_missing(conn, APP_DB, APP_ROLE, logger)
        await _create_db_if_missing(conn, CP_DB, APP_ROLE, logger)
    finally:
        await conn.close()

    await _own_public_schema(super_password, APP_DB, APP_ROLE)
    await _own_public_schema(super_password, CP_DB, APP_ROLE)


async def _ensure_cp_db_only(super_password: str, logger) -> bool:
    """Idempotent: create ONLY the Control Plane DB (owned by roofspan) if missing. Used to repair
    already-provisioned installs. Never touches the role, the business DB, or existing data."""
    import asyncpg

    conn = await asyncpg.connect(user=SUPERUSER, password=super_password,
                                 host=PG_HOST, port=PG_PORT, database="postgres")
    try:
        created = await _create_db_if_missing(conn, CP_DB, APP_ROLE, logger)
    finally:
        await conn.close()
    if created:
        await _own_public_schema(super_password, CP_DB, APP_ROLE)
    return created


async def _ensure_cp_schema_fallback(app_password: str, logger) -> None:
    """Create an isolated CP schema using only the existing least-privilege application role.

    This is intentionally a LEGACY fallback for machines whose PostgreSQL existed before RoofSpan began
    retaining pg_super.bin. It does not grant server-level privileges and does not modify PostgreSQL auth.
    """
    import asyncpg

    conn = await asyncpg.connect(user=APP_ROLE, password=app_password,
                                 host=PG_HOST, port=PG_PORT, database=APP_DB)
    try:
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS {CP_SCHEMA} AUTHORIZATION {APP_ROLE}')
    finally:
        await conn.close()
    os.environ["CONTROL_PLANE_DATABASE_URL"] = _database_url(app_password)
    os.environ["CONTROL_PLANE_SCHEMA"] = CP_SCHEMA
    logger.warning(
        "bootstrap: pg_super.bin is unavailable; using isolated Control Plane schema '%s' in database '%s'",
        CP_SCHEMA, APP_DB,
    )


async def _wait_for_postgres(super_password: str, logger, timeout: float) -> None:
    import asyncpg

    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            conn = await asyncpg.connect(user=SUPERUSER, password=super_password,
                                         host=PG_HOST, port=PG_PORT, database="postgres")
            await conn.close()
            logger.info("bootstrap: PostgreSQL is accepting local connections")
            return
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2)
    raise TimeoutError(f"PostgreSQL not accepting connections within {timeout}s: {type(last).__name__}")


def repair_control_plane_db(logger, identity_dir: str, app_password: str, wait_timeout: float = 60.0) -> None:
    """Repair already-provisioned installs without elevating the runtime database role.

    Preferred path: use the DPAPI-protected postgres credential to create the dedicated CP database.
    Legacy path: if that credential does not exist, use an isolated schema in the existing business DB.
    """
    import asyncio

    pg_super_bin = os.path.join(identity_dir, "pg_super.bin")
    if not os.path.isfile(pg_super_bin):
        asyncio.run(_ensure_cp_schema_fallback(app_password, logger))
        return

    super_password = decrypt_super_password(pg_super_bin)
    try:
        asyncio.run(_wait_for_postgres(super_password, logger, wait_timeout))
        created = asyncio.run(_ensure_cp_db_only(super_password, logger))
        if created:
            logger.info("bootstrap: repaired missing Control Plane database '%s' (owner '%s')", CP_DB, APP_ROLE)
        else:
            logger.info("bootstrap: Control Plane database '%s' already present (no repair needed)", CP_DB)
    finally:
        super_password = None  # noqa: F841


def bootstrap(logger, template_path: str, config_path: str, identity_dir: str,
              wait_timeout: float = 120.0) -> str:
    import asyncio

    if config_is_provisioned(config_path):
        logger.info("bootstrap: existing provisioned roofspan.env found; reusing credentials")
        ensure_required_runtime_secrets(config_path, logger)
        app_password = parse_generated_password(_read(config_path))
        _load_env_file_into_process(config_path)
        # Repair path: older installs provisioned only the business DB. Ensure CP storage is available so
        # Mobile Access pairing works. Non-fatal (Office stays resilient) but logs full detail.
        try:
            repair_control_plane_db(logger, identity_dir, app_password)
        except Exception:
            logger.error("bootstrap: Control Plane storage repair FAILED (Mobile pairing may be unavailable):\n%s",
                         traceback.format_exc())
        return os.environ["DATABASE_URL"]

    logger.info("bootstrap: first-install provisioning starting")
    pg_super_bin = os.path.join(identity_dir, "pg_super.bin")
    if not os.path.isfile(pg_super_bin):
        raise FileNotFoundError(f"missing PostgreSQL superuser secret at {pg_super_bin}")
    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"missing config template at {template_path}")

    super_password = decrypt_super_password(pg_super_bin)
    app_password = generate_db_password(exclude=super_password)

    asyncio.run(_wait_for_postgres(super_password, logger, wait_timeout))
    asyncio.run(_ensure_role_and_db(super_password, app_password, logger))
    super_password = None  # noqa: F841

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    rendered = render_env_from_template(_read(template_path), app_password)
    _write_atomic(config_path, rendered)
    ensure_required_runtime_secrets(config_path, logger)
    logger.info("bootstrap: wrote %s (local credentials/secrets generated; not logged)", config_path)

    _load_env_file_into_process(config_path)
    return os.environ["DATABASE_URL"]
