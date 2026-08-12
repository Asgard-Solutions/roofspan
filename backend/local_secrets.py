"""Per-installation local secrets (JWT_SECRET, SECRETS_ENCRYPTION_KEY).

A packaged RoofSpan Office installation must NOT ship one universal secret shared by every customer.
On first start, if a secret is not already provided by the environment (dev/.env keeps precedence), it is
generated with a CSPRNG and persisted to a protected local file under ProgramData, then reused on every
later start. Unique per installation, survives restart/upgrade (lives with customer data, not the
installer), never logged, never committed. No cloud dependency.

Dev/test fallback: if the env already defines a secret (e.g. backend/.env), it is used as-is and nothing
is generated or written. If the persist location is unwritable, the process still runs with an in-memory
value and logs a warning (value never logged).
"""
from __future__ import annotations

import base64
import logging
import os
import secrets as _secrets

log = logging.getLogger("roofspan.secrets")

DEFAULT_SECRETS_DIR = r"C:\ProgramData\RoofSpan\secrets"
SECRETS_FILENAME = "secrets.env"

# name -> generator
_SPECS = {
    "JWT_SECRET": lambda: _secrets.token_urlsafe(48),
    # AES-GCM 256-bit key, urlsafe-base64 (core._enc_key does urlsafe_b64decode -> 32 bytes).
    "SECRETS_ENCRYPTION_KEY": lambda: base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"),
}


def _secrets_path() -> str:
    return os.path.join(os.environ.get("ROOFSPAN_SECRETS_DIR", DEFAULT_SECRETS_DIR), SECRETS_FILENAME)


def _load(path: str) -> dict:
    values: dict = {}
    if not os.path.isfile(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def _persist(path: str, values: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ["# RoofSpan Office per-installation secrets — DO NOT COMMIT, DO NOT SHARE.\n"]
    lines += [f"{k}={v}\n" for k, v in values.items()]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    try:
        os.chmod(path, 0o600)  # POSIX; on Windows ProgramData ACLs (P1-2) protect it
    except OSError:
        pass


def ensure_local_secrets() -> None:
    """Populate os.environ with JWT_SECRET + SECRETS_ENCRYPTION_KEY, generating+persisting any that are
    not already provided by the environment. Idempotent; safe to call once at startup."""
    missing = [k for k in _SPECS if not os.environ.get(k)]
    if not missing:
        return  # environment (dev/.env or service env) already provides them

    path = _secrets_path()
    persisted = _load(path)
    to_write = dict(persisted)
    generated = []
    for k in missing:
        if persisted.get(k):
            os.environ[k] = persisted[k]
        else:
            os.environ[k] = to_write[k] = _SPECS[k]()
            generated.append(k)

    if generated:
        # FAIL CLOSED: newly generated installation secrets MUST persist durably. Continuing with an
        # ephemeral key would invalidate all sessions and make locally-encrypted integration credentials
        # undecryptable on the next restart. Never log the secret values.
        try:
            _persist(path, to_write)
        except OSError as e:
            raise RuntimeError(
                f"RoofSpan could not persist installation secrets to {path} ({e}). Refusing to start with "
                "non-durable keys. Ensure the RoofSpanBackend service account can write the secrets "
                "directory."
            ) from None
        log.info("Generated %d local installation secret(s); persisted to protected storage.", len(generated))
