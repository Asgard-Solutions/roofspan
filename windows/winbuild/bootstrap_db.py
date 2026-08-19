"""First-install local PostgreSQL provisioning + deployed-config bootstrap for RoofSpan Office.

Runs ONCE during installation (WiX deferred custom action `RoofSpanBootstrap`, sequenced BEFORE
StartServices), so RoofSpanBackend never starts before its database credentials exist.

CREDENTIAL FLOW (corrected — the superuser credential must exist BEFORE PostgreSQL is installed):
  * The RoofSpan Burn bootstrapper (BAFunctions hook, `windows/bafunctions/`) generates a cryptographically
    random PostgreSQL *superuser/bootstrap* password into the Hidden Burn variable `PgSuperPassword`
    BEFORE the EDB PostgreSQL ExePackage runs, for a NEW RoofSpan-managed install; an enterprise/external
    PostgreSQL supplies its own explicit `PgSuperPassword`. The SAME hidden value is handed to (a) the EDB
    installer via `--superpassword` and (b) this MSI via `PG_SUPERPASSWORD` -> deferred-CA argv.
  * This bootstrap therefore RECEIVES an already-established superuser credential and uses it ONLY to
    authenticate and provision. It NEVER invents a brand-new postgres credential after PostgreSQL is
    installed (that circular superuser-reset path has been removed), and if the credential is
    unexpectedly missing it FAILS CLOSED.

It then:
  1. generates a SEPARATE, unique, random local DB *application* password (never committed/logged),
  2. creates the least-privilege `roofspan` role + `roofspan` database (authenticating as postgres),
  3. renders the shipped roofspan.env TEMPLATE into the DEPLOYED
     C:\\ProgramData\\RoofSpan\\config\\roofspan.env with the real local DATABASE_URL — ONLY after
     provisioning succeeds.

Fail-closed: a missing required credential or any provisioning error returns a non-zero exit code so the
MSI custom action fails and the install rolls back; the deployed config is never written on failure. The
bootstrap/superuser password is NEVER persisted to RoofSpan config or logged (only PostgreSQL itself may
retain the postgres account password). Idempotent / upgrade-safe: if a deployed config already exists it
is PRESERVED (neither credential is regenerated). Native psql/role/db execution is HUMAN REQUIRED; the
pure decision/render logic below is unit-tested in-container.
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
DEFAULT_TEMPLATE = r"C:\Program Files\RoofSpan Office\config-templates\roofspan.env.template"
DEFAULT_DEPLOYED = r"C:\ProgramData\RoofSpan\config\roofspan.env"
# Machine-protected (DPAPI, LOCAL_MACHINE) store where the Burn BAFunctions hook persists the generated
# PostgreSQL bootstrap superpassword so a failed/rolled-back first install is recoverable on rerun. This
# script deletes it after the roofspan role/db + deployed config are provisioned (it is no longer needed).
DEFAULT_BOOTSTRAP_SECRET = r"C:\ProgramData\RoofSpan\bootstrap\pgsuper.bin"
DB_NAME = "roofspan"
DB_ROLE = "roofspan"
DB_HOST = "127.0.0.1"
# Dedicated RoofSpan-owned localhost PostgreSQL port. RoofSpan installs its OWN PostgreSQL service even
# when an unrelated PostgreSQL is present, so it must NOT assume 5432 is free. Kept consistent with the
# EDB `--serverport` (bundle.wxs PgPort) and the deployed DATABASE_URL (roofspan.env.template).
DEFAULT_PG_PORT = 5442


class BootstrapError(RuntimeError):
    """Raised for fail-closed conditions (missing required credential, provisioning failure).

    `code` is the process exit code the deferred CA returns so install-time logs identify the NON-SECRET
    cause without ever printing the password."""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------------------------------
# Credential logic (pure, unit-tested)
# --------------------------------------------------------------------------------------------------
def generate_db_password(nbytes: int = 32) -> str:
    """Random, unique-per-installation local DB *application* password (URL-safe, no shell-hostile chars).

    Separate from the superuser/bootstrap credential; this is the ONLY password persisted (in the
    deployed DATABASE_URL for the least-privilege `roofspan` role)."""
    return secrets.token_urlsafe(nbytes)


def require_bootstrap_password(supplied_super_pw: str) -> str:
    """Return the PostgreSQL superuser/bootstrap credential handed off by the installer.

    It is REQUIRED: Burn generates+supplies it for a RoofSpan-managed install (before EDB runs) and an
    external PostgreSQL supplies an explicit DBA credential. If it is missing/empty we FAIL CLOSED rather
    than attempt to invent a new superuser credential after PostgreSQL is already installed."""
    pw = (supplied_super_pw or "").strip()
    if not pw:
        raise BootstrapError(
            "PostgreSQL bootstrap credential unavailable: none was handed off by the installer. On a "
            "fresh install the Burn bootstrapper generates + persists it (DPAPI) before PostgreSQL; if an "
            "earlier attempt was interrupted, simply rerun RoofSpanSetup.exe to recover it. For an external "
            "PostgreSQL, supply PgSuperPassword.",
            code=2,
        )
    return pw


def purge_bootstrap_secret(path: str) -> None:
    """Best-effort secure removal of the DPAPI bootstrap-secret file once provisioning has succeeded (the
    superuser credential is no longer needed; the app uses the least-privilege roofspan password). Never
    raises — a leftover machine-protected blob must not fail an otherwise-successful install."""
    try:
        if path and os.path.isfile(path):
            try:
                with open(path, "r+b") as f:
                    f.write(b"\x00" * os.path.getsize(path))
                    f.flush()
                    os.fsync(f.fileno())
            except OSError:
                pass
            os.remove(path)
    except OSError:
        pass


# --------------------------------------------------------------------------------------------------
# Deployed config rendering (pure, unit-tested)
# --------------------------------------------------------------------------------------------------
def render_deployed_env(template_text: str, db_password: str) -> str:
    rendered = template_text.replace(PLACEHOLDER, db_password)
    if PLACEHOLDER in rendered:
        raise ValueError("template placeholder was not fully substituted")
    return rendered


def write_deployed_config(template_path: str, deployed_path: str, db_password: str,
                          installed_version: str | None = None) -> str:
    """Fresh install: render template -> deployed config with the real DATABASE_URL. Upgrade/repair: keep
    the existing deployed config (preserve credentials). Returns the deployed path."""
    if os.path.isfile(deployed_path):
        return deployed_path  # preserve customer creds across upgrade/repair
    with open(template_path, "r", encoding="utf-8") as f:
        rendered = render_deployed_env(f.read(), db_password)
    if installed_version:
        rendered = set_env_version(rendered, installed_version)
    os.makedirs(os.path.dirname(deployed_path), exist_ok=True)
    with open(deployed_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    try:
        os.chmod(deployed_path, 0o600)
    except OSError:
        pass
    return deployed_path


# --------------------------------------------------------------------------------------------------
# Upgrade config reconciliation (pure, unit-tested)
# --------------------------------------------------------------------------------------------------
# Keys that are secret and/or machine-specific: NEVER add-from-template and NEVER overwrite on upgrade.
# (DATABASE_URL carries the generated app password; JWT_SECRET/SECRETS_ENCRYPTION_KEY live in secrets.env
# but are guarded here defensively.)
PRESERVE_ONLY_KEYS = {"DATABASE_URL", "JWT_SECRET", "SECRETS_ENCRYPTION_KEY"}


def _env_keys(text: str) -> set:
    keys = set()
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            keys.add(s.split("=", 1)[0].strip())
    return keys


def set_env_version(text: str, version: str) -> str:
    """Return `text` with ROOFSPAN_VERSION set to `version` (updating the existing line or appending)."""
    out, found = [], False
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and s.split("=", 1)[0].strip() == "ROOFSPAN_VERSION":
            out.append(f"ROOFSPAN_VERSION={version}")
            found = True
        else:
            out.append(line)
    result = "\n".join(out)
    if not found:
        if result and not result.endswith("\n"):
            result += "\n"
        result += f"ROOFSPAN_VERSION={version}\n"
        return result
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result


def reconcile_deployed_env(existing_text: str, template_text: str,
                           installed_version: str | None = None) -> tuple[str, bool]:
    """Upgrade-safe merge. ADDS any new NON-SECRET template keys missing from the deployed config (e.g.
    LICENSING_CONTROL_PLANE_URL introduced in a newer release) and updates ROOFSPAN_VERSION to the
    installed version. NEVER overwrites an existing value and NEVER touches secret/machine-specific keys
    (DATABASE_URL, generated secrets, installation keypair path). Returns (new_text, changed)."""
    existing_keys = _env_keys(existing_text)
    additions = []
    for line in template_text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        key = key.strip()
        if key in existing_keys or key in PRESERVE_ONLY_KEYS or key == "ROOFSPAN_VERSION":
            continue
        if PLACEHOLDER in val:
            continue  # never introduce an unrendered placeholder (e.g. a fresh DATABASE_URL)
        additions.append(f"{key}={val.strip()}")

    new_text = existing_text
    changed = False
    if additions:
        if new_text and not new_text.endswith("\n"):
            new_text += "\n"
        new_text += "# --- added by upgrade (new non-secret config keys) ---\n"
        new_text += "\n".join(additions) + "\n"
        changed = True
    if installed_version:
        before = new_text
        new_text = set_env_version(new_text, installed_version)
        if new_text != before:
            changed = True
    return new_text, changed


def reconcile_upgrade_config(deployed_path: str, template_path: str,
                             installed_version: str | None = None) -> bool:
    """Upgrade/repair: merge NEW non-secret keys from the shipped template + update the version, while
    PRESERVING every existing secret/credential/identity/customer value. No-op when nothing changes;
    never provisions the database. Returns True if the deployed config was updated."""
    if not os.path.isfile(deployed_path) or not os.path.isfile(template_path):
        return False
    with open(deployed_path, "r", encoding="utf-8") as f:
        existing = f.read()
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()
    new_text, changed = reconcile_deployed_env(existing, template, installed_version)
    if changed:
        with open(deployed_path, "w", encoding="utf-8") as f:
            f.write(new_text)
        try:
            os.chmod(deployed_path, 0o600)
        except OSError:
            pass
    return changed


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
                            svc = ""
                            try:
                                svc, _ = winreg.QueryValueEx(sk, "Service ID")
                            except OSError:
                                pass
                            psql = psql_path_from_base_dir(base)
                            if os.path.isfile(psql):
                                # The RoofSpan-managed instance (service RoofSpanPostgreSQL) sorts first.
                                (candidates.insert(0, psql) if "roofspan" in (svc + base).lower()
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
            "psql.exe not found: no PostgreSQL installation registered under "
            "HKLM\\SOFTWARE\\PostgreSQL\\Installations.",
            code=4,
        )
    return psql


# --------------------------------------------------------------------------------------------------
# Provisioning (native; HUMAN REQUIRED). No superuser password reset — EDB already established the
# superuser password during installation; we merely authenticate with it.
# --------------------------------------------------------------------------------------------------
def _psql(psql_path: str, host: str, port: int, super_password: str, sql: str,
          dbname: str = "postgres") -> None:  # pragma: no cover (native)
    env = {**os.environ, "PGPASSWORD": super_password}
    subprocess.run([psql_path, "-h", host, "-p", str(port), "-U", "postgres", "-d", dbname,
                    "-v", "ON_ERROR_STOP=1", "-c", sql], check=True, env=env)


def provision_database(*, psql_path: str, host: str, port: int, super_password: str,
                       db_password: str) -> None:  # pragma: no cover (native)
    """Create the least-privilege `roofspan` role + database if absent, authenticating as the existing
    postgres superuser. HUMAN REQUIRED on Windows."""
    _psql(psql_path, host, port, super_password,
          f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{DB_ROLE}') "
          f"THEN CREATE ROLE {DB_ROLE} LOGIN PASSWORD '{db_password}'; END IF; END $$;")
    _psql(psql_path, host, port, super_password, f"ALTER ROLE {DB_ROLE} WITH PASSWORD '{db_password}';")
    exists = subprocess.run([psql_path, "-h", host, "-p", str(port), "-U", "postgres", "-tAc",
                             f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}'"],
                            env={**os.environ, "PGPASSWORD": super_password}, capture_output=True, text=True)
    if exists.stdout.strip() != "1":
        _psql(psql_path, host, port, super_password, f"CREATE DATABASE {DB_NAME} OWNER {DB_ROLE};")


# --------------------------------------------------------------------------------------------------
# Orchestration (testable via injected provision_fn)
# --------------------------------------------------------------------------------------------------
def run_bootstrap(*, supplied_super_pw: str, deployed_path: str, template_path: str, psql_path: str,
                  port: int = DEFAULT_PG_PORT, host: str = DB_HOST,
                  bootstrap_secret_path: str = DEFAULT_BOOTSTRAP_SECRET,
                  installed_version: str | None = None,
                  provision_fn=provision_database) -> int:
    """Provision the DB then render the deployed config. FAIL CLOSED: config is written ONLY after
    successful provisioning. Upgrade/repair (deployed config present) preserves all existing
    credentials/identity and only RECONCILES new non-secret keys + the version (regenerates nothing).
    On success the recoverable DPAPI bootstrap secret is securely purged."""
    if os.path.isfile(deployed_path):
        # upgrade/repair: preserve creds + identity; add new non-secret keys + update version only.
        reconcile_upgrade_config(deployed_path, template_path, installed_version)
        return 0

    if not os.path.isfile(template_path):
        raise BootstrapError(f"config template missing: {template_path}", code=5)

    super_pw = require_bootstrap_password(supplied_super_pw)  # fail-closed if missing (recover by rerun)
    db_pw = generate_db_password()
    if db_pw == super_pw:  # defensive: the two credentials must never coincide
        raise BootstrapError("bootstrap and application passwords must be distinct", code=3)

    # Provision FIRST. Only render the deployed DATABASE_URL if provisioning succeeded.
    provision_fn(psql_path=psql_path, host=host, port=port, super_password=super_pw, db_password=db_pw)
    write_deployed_config(template_path, deployed_path, db_pw, installed_version)
    # Provisioning + config both succeeded -> the recoverable superuser secret is no longer needed.
    purge_bootstrap_secret(bootstrap_secret_path)
    return 0


def parse_args(argv) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="RoofSpanBootstrap", add_help=False)
    # Handed off from Burn -> MSI PG_SUPERPASSWORD -> here. REQUIRED at provisioning time (empty fails closed).
    ap.add_argument("--pg-superpassword", dest="pg_superpassword", default="")
    ap.add_argument("--pg-port", dest="pg_port", type=int, default=DEFAULT_PG_PORT)
    ap.add_argument("--template", default=os.environ.get("ROOFSPAN_CONFIG_TEMPLATE", DEFAULT_TEMPLATE))
    ap.add_argument("--deployed", default=os.environ.get("ROOFSPAN_DEPLOYED_CONFIG", DEFAULT_DEPLOYED))
    ap.add_argument("--bootstrap-secret-path",
                    default=os.environ.get("ROOFSPAN_BOOTSTRAP_SECRET", DEFAULT_BOOTSTRAP_SECRET))
    # Authoritative installed version (WiX passes windows\VERSION). Used to update ROOFSPAN_VERSION on
    # fresh install AND to reconcile the version on upgrade (so it never stays 0.1.0).
    ap.add_argument("--roofspan-version", dest="roofspan_version",
                    default=os.environ.get("ROOFSPAN_VERSION", ""))
    return ap.parse_args(argv)


def main(argv=None) -> int:  # pragma: no cover (native install-time orchestration)
    args = parse_args(argv if argv is not None else sys.argv[1:])
    version = (args.roofspan_version or "").strip() or None
    if os.path.isfile(args.deployed):
        # upgrade/repair: reconcile new non-secret keys + version; never provision, preserve secrets.
        try:
            reconcile_upgrade_config(args.deployed, args.template, version)
        except Exception as e:  # non-fatal: a reconcile hiccup must not fail an upgrade
            log.error("RoofSpan config reconcile skipped (non-fatal): %s", type(e).__name__)
        return 0
    try:
        psql_path = discover_psql()
        return run_bootstrap(supplied_super_pw=args.pg_superpassword, deployed_path=args.deployed,
                             template_path=args.template, psql_path=psql_path, port=args.pg_port,
                             bootstrap_secret_path=args.bootstrap_secret_path,
                             installed_version=version)
    except BootstrapError as e:
        # Non-secret cause is logged with a distinct exit code (2=credential, 4=psql, 5=template, 3=other).
        log.error("RoofSpan DB bootstrap failed (exit %d, fail-closed): %s", e.code, e)
        return e.code
    except Exception as e:  # provisioning / IO error -> fail closed, MSI rolls back
        log.error("RoofSpan DB bootstrap error (fail-closed): %s", type(e).__name__)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
