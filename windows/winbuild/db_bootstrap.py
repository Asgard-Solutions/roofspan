r"""First-install local PostgreSQL bootstrap for the RoofSpanBackend Windows service.

Runs INSIDE the backend service, BEFORE `server`/`backend.db` are imported (db.py reads DATABASE_URL at
import time). On a brand-new machine it:

  1. waits until PostgreSQL is accepting local connections (the RoofSpanPostgreSQL SCM dependency has
     already started the service; "started" != "accepting connections", so we poll);
  2. decrypts C:\ProgramData\RoofSpan\identity\pg_super.bin with Windows DPAPI (LocalMachine) to recover
     the EDB superuser password the Burn prerequisite generated;
  3. generates a SEPARATE strong password for the least-privilege application role `roofspan`;
  4. idempotently ensures role `roofspan` (LOGIN, NOT superuser) + database `roofspan` (owner roofspan);
  5. writes C:\ProgramData\RoofSpan\config\roofspan.env from the installed template, substituting the
     generated app password into DATABASE_URL;
  6. loads that config into the process environment so db.py/server import cleanly.

Idempotency: if roofspan.env already holds a valid generated credential it is REUSED as-is (no rotation
on restart, no superuser access needed, no data touched). Secrets are NEVER logged.
"""
from __future__ import annotations

import os
import re
import secrets
import string
import time

PLACEHOLDER = "__GENERATED_AT_FIRST_RUN__"
SUPERUSER = "postgres"          # EDB default super account (bundle sets its password via --superpassword)
APP_ROLE = "roofspan"
APP_DB = "roofspan"
PG_HOST = "127.0.0.1"
PG_PORT = 5432


# ---- pure helpers (unit-tested on any platform) -----------------------------------------------------

def generate_db_password(exclude: str = "") -> str:
    """Strong URL-safe (alphanumeric) app-role password; guaranteed != `exclude`."""
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(32))
        if pw != exclude and any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def render_env_from_template(template_text: str, app_password: str) -> str:
    return template_text.replace(PLACEHOLDER, app_password)


def _database_url(password: str) -> str:
    return f"postgresql+asyncpg://{APP_ROLE}:{password}@{PG_HOST}:{PG_PORT}/{APP_DB}"


def parse_generated_password(config_text: str):
    """Return the app password from a roofspan.env DATABASE_URL, or None if unset/placeholder."""
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


def _load_env_file_into_process(config_path: str) -> None:
    """Authoritatively load the installed config into os.environ (override) before server import."""
    for line in _read(config_path).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()


# ---- Windows-only pieces (DPAPI + PostgreSQL) -------------------------------------------------------

def decrypt_super_password(pg_super_bin: str) -> str:
    """Decrypt the DPAPI LocalMachine blob written by the Burn PostgreSQL prerequisite."""
    import win32crypt  # pywin32; Windows-only
    with open(pg_super_bin, "rb") as f:
        blob = f.read()
    # CryptUnprotectData returns (description, data). LocalMachine scope is implicit in the blob.
    _desc, data = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
    return data.decode("utf-8")


async def _ensure_role_and_db(super_password: str, app_password: str, logger) -> None:
    import asyncpg

    conn = await asyncpg.connect(user=SUPERUSER, password=super_password,
                                 host=PG_HOST, port=PG_PORT, database="postgres")
    try:
        # CREATE/ALTER ROLE are utility statements and CANNOT take bind parameters. Quote the password
        # SAFELY server-side via quote_literal() (proper escaping) - never string-concatenate the secret.
        # APP_ROLE is a fixed, code-owned identifier (never user input).
        quoted_pw = await conn.fetchval("SELECT quote_literal($1)", app_password)
        role_exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", APP_ROLE)
        if role_exists:
            logger.info("bootstrap: role '%s' already exists (kept)", APP_ROLE)
            # No valid config existed (else we would not be here), so align the password we will persist.
            await conn.execute(f"ALTER ROLE {APP_ROLE} WITH LOGIN NOSUPERUSER PASSWORD {quoted_pw}")
        else:
            await conn.execute(f"CREATE ROLE {APP_ROLE} WITH LOGIN NOSUPERUSER PASSWORD {quoted_pw}")
            logger.info("bootstrap: created least-privilege role '%s'", APP_ROLE)
        # Least privilege: the role is a normal LOGIN role (NOT superuser) and simply OWNS its own db.
        db_exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", APP_DB)
        if not db_exists:
            await conn.execute(f'CREATE DATABASE {APP_DB} OWNER {APP_ROLE}')
            logger.info("bootstrap: created database '%s' owned by '%s'", APP_DB, APP_ROLE)
        else:
            logger.info("bootstrap: database '%s' already exists (kept)", APP_DB)
    finally:
        await conn.close()

    # Ensure the app role fully controls its own schema (owner-level, still not a superuser).
    conn2 = await asyncpg.connect(user=SUPERUSER, password=super_password,
                                  host=PG_HOST, port=PG_PORT, database=APP_DB)
    try:
        await conn2.execute(f'GRANT ALL ON DATABASE {APP_DB} TO {APP_ROLE}')
        await conn2.execute(f'ALTER SCHEMA public OWNER TO {APP_ROLE}')
    finally:
        await conn2.close()


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


def bootstrap(logger, template_path: str, config_path: str, identity_dir: str,
              wait_timeout: float = 120.0) -> str:
    """Idempotently ensure the local application DB + config exist; returns the DATABASE_URL and loads
    the full config into os.environ. Raises (clearly) on failure so the service never falsely runs."""
    import asyncio

    # Fast, credential-preserving path: a valid generated config already exists -> reuse verbatim.
    if config_is_provisioned(config_path):
        logger.info("bootstrap: existing provisioned roofspan.env found; reusing credentials")
        _load_env_file_into_process(config_path)
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
    # Drop the superuser secret from memory promptly.
    super_password = None  # noqa: F841

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    rendered = render_env_from_template(_read(template_path), app_password)
    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(rendered)
    os.replace(tmp, config_path)
    logger.info("bootstrap: wrote %s (DB credentials generated; not logged)", config_path)

    _load_env_file_into_process(config_path)
    return os.environ["DATABASE_URL"]
