r"""Targeted, atomic, idempotent reconciliation of an EXISTING C:\ProgramData\RoofSpan\config\roofspan.env.

Runs in the RoofSpanBackend service before first-run bootstrap reuses a saved configuration. Ownership:

  build identity             ROOFSPAN_VERSION, ROOFSPAN_BUILD_SHA     -> removed (the executable is authoritative)
  generated secrets          JWT_SECRET, SECRETS_ENCRYPTION_KEY       -> preserved byte-for-byte
  database credentials       DATABASE_URL, CONTROL_PLANE_DATABASE_URL -> preserved byte-for-byte
  installation-owned paths   ROOFSPAN_STATIC_DIR, ROOFSPAN_UPDATE_PUBLIC_KEY
                             -> refreshed ONLY when the saved path no longer exists and the installed one does
  customer settings / data paths / unknown keys                       -> preserved byte-for-byte
  missing supported defaults (template keys without a generated placeholder) -> appended

Every untouched line keeps its exact bytes; no secret value is logged (key names only); nothing is written
when nothing changes. Missing secrets are generated separately by db_bootstrap.ensure_required_runtime_secrets.
"""
from __future__ import annotations

import os

import build_identity

GENERATED_SECRETS = ("JWT_SECRET", "SECRETS_ENCRYPTION_KEY")
DATABASE_CREDENTIALS = ("DATABASE_URL", "CONTROL_PLANE_DATABASE_URL")
INSTALLATION_PATHS = {
    "ROOFSPAN_STATIC_DIR": ("frontend",),
    "ROOFSPAN_UPDATE_PUBLIC_KEY": ("config-templates", "update_public_key.pem"),
}
_PLACEHOLDER_MARK = "__GENERATED"


def classify(key: str) -> str:
    if key in build_identity.IDENTITY_KEYS:
        return "build_identity"
    if key in GENERATED_SECRETS:
        return "generated_secret"
    if key in DATABASE_CREDENTIALS:
        return "database_credential"
    if key in INSTALLATION_PATHS:
        return "installation_path"
    return "customer_setting"


def _key(line: str):
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        return None
    return s.split("=", 1)[0].strip()


def _value(line: str) -> str:
    return line.split("=", 1)[1].strip()


def _template_defaults(template_path: str) -> list[tuple[str, str]]:
    if not os.path.isfile(template_path):
        return []
    with open(template_path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    out = []
    for line in lines:
        k = _key(line)
        if not k or classify(k) in ("build_identity", "generated_secret", "database_credential"):
            continue
        v = _value(line)
        if _PLACEHOLDER_MARK not in v:
            out.append((k, v))
    return out


def _write_atomic(path: str, data: bytes) -> None:
    tmp = path + ".reconcile.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def reconcile(config_path: str, template_path: str, install_root: str, logger) -> dict:
    """Reconcile a saved config in place. Returns {'removed','refreshed','added'} key-name lists."""
    changes = {"removed": [], "refreshed": [], "added": []}
    if not os.path.isfile(config_path):
        return changes  # first install: db_bootstrap renders the config from the template
    with open(config_path, "rb") as f:
        raw = f.read()
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    text = raw[len(bom):].decode("utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    installed = {k: os.path.join(install_root, *parts) for k, parts in INSTALLATION_PATHS.items()}

    kept, present = [], set()
    for line in text.splitlines(keepends=True):
        k = _key(line)
        if k is None:
            kept.append(line)
            continue
        cls = classify(k)
        if cls == "build_identity":
            changes["removed"].append(k)
            continue
        present.add(k)
        if cls == "installation_path":
            saved = _value(line)
            if not os.path.exists(saved) and os.path.exists(installed[k]):
                ending = line[len(line.rstrip("\r\n")):] or eol
                kept.append(f"{k}={installed[k]}{ending}")
                changes["refreshed"].append(k)
                continue
        kept.append(line)

    additions = []
    for k, v in _template_defaults(template_path):
        if k in present or k in (a[0] for a in additions):
            continue
        additions.append((k, installed.get(k, v)))
    if additions:
        if kept and not kept[-1].endswith(("\n", "\r")):
            kept.append(eol)
        kept.append(f"{eol}# Supported defaults added by RoofSpan configuration reconciliation.{eol}")
        kept.extend(f"{k}={v}{eol}" for k, v in additions)
        changes["added"] = [k for k, _ in additions]

    if not any(changes.values()):
        return changes
    _write_atomic(config_path, bom + "".join(kept).encode("utf-8"))
    logger.info("config reconcile: removed=%s refreshed=%s added=%s (values not logged)",
                ",".join(changes["removed"]) or "-", ",".join(changes["refreshed"]) or "-",
                ",".join(changes["added"]) or "-")
    return changes
