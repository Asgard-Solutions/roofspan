"""Photo object storage for mobile photo upload/retrieval.

Two backends, selected automatically so both self-hosted and cloud installs work:

1. LOCAL FILESYSTEM (self-hosted Office, e.g. Windows `C:\\Program Files\\RoofSpan Office\\Images`):
   used when `PHOTO_STORAGE_DIR` is set, OR whenever the Emergent object-storage proxy is not
   configured (no `EMERGENT_LLM_KEY`). Photos are written under that directory using the same
   relative object path stored on the Photo row, so nothing else in the app changes.

2. EMERGENT MANAGED PROXY (hosted preview/cloud): used only when `EMERGENT_LLM_KEY` is present and
   `PHOTO_STORAGE_DIR` is unset.

This is deliberately separate from backup off-site copies (a plain filesystem copy that never uses a
cloud API).
"""
import os

import requests
from dotenv import load_dotenv

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

_storage_key = None


# ---- Backend selection -------------------------------------------------------------------------
def _local_dir() -> str | None:
    """Return the local photo directory when local storage should be used, else None (use proxy)."""
    configured = os.environ.get("PHOTO_STORAGE_DIR")
    if configured:
        return configured
    # Self-hosted fallback: if the managed proxy is not configured, never depend on a cloud service —
    # keep photos on local disk so field uploads always land somewhere the Office can serve.
    if not os.environ.get("EMERGENT_LLM_KEY"):
        return os.path.join(_BACKEND_DIR, "data", "photos")
    return None


def _local_path(base: str, path: str) -> str:
    """Resolve a relative object path under `base`, blocking path traversal."""
    rel = (path or "").replace("\\", "/").strip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".", "..")]
    full = os.path.normpath(os.path.join(base, *parts))
    base_abs = os.path.abspath(base)
    if not os.path.abspath(full).startswith(base_abs):
        raise ValueError("invalid object path")
    return full


# ---- Emergent managed proxy --------------------------------------------------------------------
def _base() -> str:
    return (os.environ.get("INTEGRATION_PROXY_URL") or "https://integrations.emergentagent.com").rstrip("/") \
        + "/objstore/api/v1/storage"


def init_storage(force: bool = False) -> str:
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    resp = requests.post(f"{_base()}/init",
                         json={"emergent_key": os.environ.get("EMERGENT_LLM_KEY")}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


# ---- Public API (backend-agnostic) -------------------------------------------------------------
def put_object(path: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
    base = _local_dir()
    if base:
        full = _local_path(base, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)
        return {"path": path, "bytes": len(data), "backend": "local", "dir": base}
    key = init_storage()
    url = f"{_base()}/objects/{path}"
    resp = requests.put(url, headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=180)
    if resp.status_code == 404:
        key = init_storage(force=True)
        resp = requests.put(url, headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=180)
    resp.raise_for_status()
    return resp.json()


def put_upload(path: str, data: bytes, local_base: str | None = None,
               content_type: str = "application/octet-stream") -> dict:
    """Persist a user-uploaded file through the same dual-mode storage as photos.

    Self-hosted (a `local_base` is given, e.g. the Office backup directory, or the managed proxy is
    not configured) -> local disk with an atomic rename. Hosted installs (managed proxy configured,
    no local base) -> Emergent managed object store, so uploads are never pinned to ephemeral
    pod-only storage. Mirrors `put_object` so both deployment shapes are covered by one path.
    """
    base = local_base or _local_dir()
    if base:
        full = _local_path(base, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        tmp = full + ".partial"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, full)
        return {"path": path, "bytes": len(data), "backend": "local", "dir": base, "full": full}
    res = put_object(path, data, content_type)
    res.setdefault("backend", "proxy")
    return res


def get_object(path: str) -> bytes:
    base = _local_dir()
    if base:
        with open(_local_path(base, path), "rb") as f:
            return f.read()
    key = init_storage()
    url = f"{_base()}/objects/{path}"
    resp = requests.get(url, headers={"X-Storage-Key": key}, timeout=120)
    if resp.status_code == 404:
        key = init_storage(force=True)
        resp = requests.get(url, headers={"X-Storage-Key": key}, timeout=120)
    resp.raise_for_status()
    return resp.content
