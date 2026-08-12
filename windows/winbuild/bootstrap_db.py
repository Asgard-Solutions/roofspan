"""First-install local PostgreSQL + deployed-config bootstrap for RoofSpan Office.

Runs ONCE during installation (WiX deferred custom action `RoofSpanBootstrap`, sequenced BEFORE
StartServices), so RoofSpanBackend never starts before its database credentials exist. It:

  1. resolves the PostgreSQL *superuser* (bootstrap) credential used only to provision:
       - Enterprise / external PostgreSQL  -> a hidden/secure `PgSuperPassword` MUST be supplied
         (Burn -> MSI PG_SUPERPASSWORD -> deferred CA argv). Empty here => FAIL CLOSED.
       - RoofSpan-managed local PostgreSQL  -> no DBA input required: a cryptographically random
         *temporary* bootstrap password is generated locally. It is used only for provisioning and
         is neither persisted to RoofSpan config nor logged nor reused as the application password.
  2. generates a SEPARATE, unique, random local DB *application* password (never committed/logged),
  3. creates/configures the least-privilege `roofspan` role + `roofspan` database,
  4. renders the shipped roofspan.env TEMPLATE into the DEPLOYED
     C:\\ProgramData\\RoofSpan\\config\\roofspan.env with the real local DATABASE_URL — ONLY after
     provisioning succeeds.

Fail-closed: any provisioning error (or a missing required credential) returns a non-zero exit code so
the MSI custom action fails and the install rolls back; the deployed config is never written on failure.
Idempotent / upgrade-safe: if a deployed config already exists it is PRESERVED (neither credential is
regenerated). The temporary bootstrap password is not retained after provisioning (only PostgreSQL itself
may retain the postgres account password). Native psql/role/db execution is HUMAN REQUIRED; the pure
decision/render logic below is unit-tested in-container.
"""
from __future__ import annotations

import argparse
import logging
import os
import secrets
import subprocess
import sys

log = logging.getLogger("roofspan.bootstrap")

PLACEHOLDER = "__GENERATED_AT_FIRST_RUN__"
DEFAULT_TEMPLATE = r"C:\Program Files\RoofSpan Office\config-templates\roofspan.env"
DEFAULT_DEPLOYED = r"C:\ProgramData\RoofSpan\config\roofspan.env"
DB_NAME = "roofspan"
DB_ROLE = "roofspan"
# RoofSpan installs its own dedicated PostgreSQL service (bundle.wxs --servicename). We only ever
# provision a PostgreSQL instance we recognise as RoofSpan-managed; an unrelated existing PostgreSQL is
# NEVER silently adopted (an explicit superuser credential is required for that).
ROOFSPAN_PG_SERVICE = "RoofSpanPostgreSQL"


class BootstrapError(RuntimeError):
    """Raised for fail-closed conditions (missing required credential, provisioning failure)."""


# --------------------------------------------------------------------------------------------------
# Credential logic (pure, unit-tested)
# --------------------------------------------------------------------------------------------------
def generate_db_password(nbytes: int = 32) -> str:
    """Random, unique-per-installation local DB *application* password (URL-safe, no shell-hostile chars)."""
    return secrets.token_urlsafe(nbytes)


def generate_bootstrap_password(nbytes: int = 32) -> str:
    """Random *temporary* PostgreSQL superuser/bootstrap password for a fresh RoofSpan-managed instance.

    Distinct from the application password, used only for provisioning, never persisted to RoofSpan
    config and never logged."""
    return secrets.token_urlsafe(nbytes)


def resolve_bootstrap_password(supplied_super_pw: str, roofspan_managed: bool) -> tuple[str, bool]:
    """Return (bootstrap_superuser_password, generated_flag) under the hybrid model.

    - A supplied (enterprise/override) credential always wins, regardless of managed/unmanaged.
    - RoofSpan-managed fresh install with NO supplied credential -> generate a temporary one.
    - External/enterprise PostgreSQL with NO supplied credential -> FAIL CLOSED (BootstrapError).
    """
    supplied = (supplied_super_pw or "").strip()
    if supplied:
        return supplied, False
    if roofspan_managed:
        return generate_bootstrap_password(), True
    raise BootstrapError(
        "no PostgreSQL superuser credential supplied and no RoofSpan-managed PostgreSQL instance "
        "detected; supply PgSuperPassword for the existing PostgreSQL instance"
    )


# --------------------------------------------------------------------------------------------------
# Deployed config rendering (pure, unit-tested)
# --------------------------------------------------------------------------------------------------
def render_deployed_env(template_text: str, db_password: str) -> str:
    rendered = template_text.replace(PLACEHOLDER, db_password)
    if PLACEHOLDER in rendered:
        raise ValueError("template placeholder was not fully substituted")
    return rendered


def write_deployed_config(template_path: str, deployed_path: str, db_password: str) -> str:
    """Fresh install: render template -> deployed config with the real DATABASE_URL. Upgrade/repair: keep
    the existing deployed config (preserve credentials). Returns the deployed path."""
    if os.path.isfile(deployed_path):
        return deployed_path  # preserve customer creds across upgrade/repair
    with open(template_path, "r", encoding="utf-8") as f:
        rendered = render_deployed_env(f.read(), db_password)
    os.makedirs(os.path.dirname(deployed_path), exist_ok=True)
    with open(deployed_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    try:
        os.chmod(deployed_path, 0o600)
    except OSError:
        pass
    return deployed_path


# --------------------------------------------------------------------------------------------------
# Deterministic psql.exe discovery (registry-based; parsing is unit-tested)
# --------------------------------------------------------------------------------------------------
def psql_path_from_base_dir(base_dir: str) -> str:
    """Deterministic psql.exe location for a PostgreSQL install 'Base Directory'."""
    return os.path.join(base_dir, "bin", "psql.exe")


def _psql_from_registry() -> str | None:  # pragma: no cover (native winreg)
    """Locate psql.exe via HKLM\\SOFTWARE\\PostgreSQL\\Installations\\*\\'Base Directory' (deterministic;
    does NOT rely on PATH). Prefers the RoofSpan-managed instance when identifiable."""
    import winreg

    root = r"SOFTWARE\PostgreSQL\Installations"
    candidates: list[str] = []
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root, 0, winreg.KEY_READ | view) as k:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(k, sub, 0, winreg.KEY_READ | view) as sk:
                            base, _ = winreg.QueryValueEx(sk, "Base Directory")
                            psql = psql_path_from_base_dir(base)
                            if os.path.isfile(psql):
                                # RoofSpan-branded install dirs sort first.
                                (candidates.insert(0, psql) if "roofspan" in base.lower()
                                 else candidates.append(psql))
                    except OSError:
                        continue
        except OSError:
            continue
    return candidates[0] if candidates else None


def discover_psql() -> str:  # pragma: no cover (native)
    psql = _psql_from_registry()
    if not psql:
        raise BootstrapError(
            "could not locate psql.exe from HKLM\\SOFTWARE\\PostgreSQL\\Installations; no usable "
            "PostgreSQL installation was found"
        )
    return psql


# --------------------------------------------------------------------------------------------------
# RoofSpan-managed instance detection (native)
# --------------------------------------------------------------------------------------------------
def detect_roofspan_managed_pg() -> bool:  # pragma: no cover (native SCM query)
    """True only if the dedicated RoofSpan-managed PostgreSQL service exists. An unrelated pre-existing
    PostgreSQL is NOT treated as RoofSpan-managed (so it is never silently adopted)."""
    try:
        r = subprocess.run(["sc", "query", ROOFSPAN_PG_SERVICE], capture_output=True, text=True)
        return r.returncode == 0
    except OSError:
        return False


# --------------------------------------------------------------------------------------------------
# Provisioning (native; HUMAN REQUIRED)
# --------------------------------------------------------------------------------------------------
def _psql(psql_path: str, super_password: str, sql: str, dbname: str = "postgres") -> None:  # pragma: no cover
    env = {**os.environ, "PGPASSWORD": super_password}
    subprocess.run([psql_path, "-h", "127.0.0.1", "-U", "postgres", "-d", dbname,
                    "-v", "ON_ERROR_STOP=1", "-c", sql], check=True, env=env)


def provision_database(*, psql_path: str, super_password: str, db_password: str,
                       set_superuser: bool = False) -> None:  # pragma: no cover (native)
    """Create the least-privilege role + database if absent. For a freshly RoofSpan-provisioned instance
    (set_superuser) the generated temporary superuser password is applied first. HUMAN REQUIRED on Windows."""
    if set_superuser:
        _psql(psql_path, super_password, f"ALTER USER postgres WITH PASSWORD '{super_password}';")
    _psql(psql_path, super_password,
          f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{DB_ROLE}') "
          f"THEN CREATE ROLE {DB_ROLE} LOGIN PASSWORD '{db_password}'; END IF; END $$;")
    _psql(psql_path, super_password, f"ALTER ROLE {DB_ROLE} WITH PASSWORD '{db_password}';")
    exists = subprocess.run([psql_path, "-h", "127.0.0.1", "-U", "postgres", "-tAc",
                             f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}'"],
                            env={**os.environ, "PGPASSWORD": super_password}, capture_output=True, text=True)
    if exists.stdout.strip() != "1":
        _psql(psql_path, super_password, f"CREATE DATABASE {DB_NAME} OWNER {DB_ROLE};")


# --------------------------------------------------------------------------------------------------
# Orchestration (testable via injected provision_fn)
# --------------------------------------------------------------------------------------------------
def run_bootstrap(*, supplied_super_pw: str, deployed_path: str, template_path: str,
                  roofspan_managed: bool, psql_path: str, provision_fn=provision_database) -> int:
    """Provision the DB then render the deployed config. FAIL CLOSED: config is written ONLY after
    successful provisioning. Upgrade/repair (deployed config present) preserves both credentials."""
    if os.path.isfile(deployed_path):
        return 0  # upgrade/repair: preserve creds + config; regenerate nothing

    super_pw, generated = resolve_bootstrap_password(supplied_super_pw, roofspan_managed)
    db_pw = generate_db_password()
    if db_pw == super_pw:  # defensive: the two credentials must never coincide
        raise BootstrapError("bootstrap and application passwords must be distinct")

    # Provision FIRST. Only render the deployed DATABASE_URL if provisioning succeeded.
    provision_fn(psql_path=psql_path, super_password=super_pw, db_password=db_pw,
                 set_superuser=generated)
    write_deployed_config(template_path, deployed_path, db_pw)
    return 0


def parse_args(argv) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="RoofSpanBootstrap", add_help=False)
    # Empty default is VALID for a RoofSpan-managed fresh install (bootstrap self-generates); it is
    # invalid for an external PostgreSQL (resolve_bootstrap_password fails closed).
    ap.add_argument("--pg-superpassword", dest="pg_superpassword", default="")
    ap.add_argument("--template", default=os.environ.get("ROOFSPAN_CONFIG_TEMPLATE", DEFAULT_TEMPLATE))
    ap.add_argument("--deployed", default=os.environ.get("ROOFSPAN_DEPLOYED_CONFIG", DEFAULT_DEPLOYED))
    return ap.parse_args(argv)


def main(argv=None) -> int:  # pragma: no cover (native install-time orchestration)
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if os.path.isfile(args.deployed):
        return 0  # upgrade/repair short-circuit (no detection / psql discovery needed)
    try:
        managed = detect_roofspan_managed_pg()
        psql_path = discover_psql()
        return run_bootstrap(supplied_super_pw=args.pg_superpassword, deployed_path=args.deployed,
                             template_path=args.template, roofspan_managed=managed, psql_path=psql_path)
    except BootstrapError as e:
        log.error("RoofSpan DB bootstrap failed (fail-closed): %s", e)  # never log secret values
        return 2
    except Exception as e:  # provisioning / IO error -> fail closed, MSI rolls back
        log.error("RoofSpan DB bootstrap error (fail-closed): %s", type(e).__name__)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
