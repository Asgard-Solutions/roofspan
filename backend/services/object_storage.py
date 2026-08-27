"""Photo object storage for mobile photo upload/retrieval.

Two backends, selected automatically so both self-hosted and cloud installs work:

1. LOCAL FILESYSTEM (self-hosted Office): used when ``PHOTO_STORAGE_DIR`` is set, or whenever the
   Emergent object-storage proxy is not configured. Windows Office data belongs under
   ``C:\\ProgramData\\RoofSpan\\images`` (never inside Program Files) so the virtual service account can
   write it and upgrades cannot replace it.

2. EMERGENT MANAGED PROXY (hosted preview/cloud): used only when ``EMERGENT_LLM_KEY`` is present and
   ``PHOTO_STORAGE_DIR`` is unset.

This is deliberately separate from backup off-site copies (a plain filesystem copy that never uses a
cloud API).
"""
import os
import uuid

import requests
from dotenv import load_dotenv

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

_storage_key = None


# ---- Backend selection -------------------------------------------------------------------------
def _self_hosted_dir() -> str:
    """Return a persistent writable photo root for self-hosted Office."""
    data_root = os.environ.get("ROOFSPAN_DATA_ROOT")
    if data_root:
        return os.path.join(data_root, "images")
    if os.name == "nt":
        program_data = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
        return os.path.join(program_data, "RoofSpan", "images")
    # Dev/Linux fallback keeps current local-development behavior.
    return os.path.join(_BACKEND_DIR, "data", "photos")


def _local_dir() -> str | None:
    """Return the local photo directory when local storage should be used, else None (use proxy)."""
    configured = (os.environ.get("PHOTO_STORAGE_DIR") or "").strip()
    if configured:
        return os.path.abspath(os.path.expandvars(configured))
    # Self-hosted fallback: if the managed proxy is not configured, never depend on a cloud service.
    if not os.environ.get("EMERGENT_LLM_KEY"):
        return _self_hosted_dir()
    return None


def _local_path(base: str, path: str) -> str:
    """Resolve a relative object path under ``base``, blocking path traversal."""
    rel = (path or "").replace("\\", "/").strip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".", "..")]
    base_abs = os.path.abspath(base)
    full = os.path.abspath(os.path.normpath(os.path.join(base_abs, *parts)))
    try:
        if os.path.commonpath([base_abs, full]) != base_abs:
            raise ValueError("invalid object path")
    except ValueError:
        raise ValueError("invalid object path") from None
    return full


def ensure_storage_ready() -> str | None:
    """Prove the configured local photo directory is writable before Office reports ready.

    The Windows service runs as ``NT SERVICE\\RoofSpanBackend``. A missing/incorrect ACL previously
    surfaced only when a field rep uploaded a photo, producing HTTP 502 and an endlessly Pending queue
    item. This probe converts that hidden runtime failure into a deterministic Office startup error.
    Hosted preview/proxy mode returns ``None`` because it has no local directory to probe.
    """
    base = _local_dir()
    if not base:
        return None
    os.makedirs(base, exist_ok=True)
    probe = os.path.join(base, f".roofspan-photo-storage-probe-{uuid.uuid4().hex}")
    try:
        with open(probe, "wb") as f:
            f.write(b"roofspan-photo-storage-ok")
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        raise RuntimeError(f"RoofSpan photo storage is not writable: {base}") from exc
    finally:
        try:
            if os.path.exists(probe):
                os.remove(probe)
        except OSError:
            pass
    return base


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
        parent = os.path.dirname(full)
        os.makedirs(parent, exist_ok=True)
        # Write-then-replace prevents a process/service interruption from leaving a partial image at
        # the authoritative object path. The temp file is on the same volume so os.replace is atomic.
        tmp = f"{full}.tmp-{uuid.uuid4().hex}"
        try:
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, full)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
        return {"path": path, "bytes": len(data), "backend": "local", "dir": base}
    key = init_storage()
    url = f"{_base()}/objects/{path}"
    resp = requests.put(url, headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=180)
    if resp.status_code == 404:
        key = init_storage(force=True)
        resp = requests.put(url, headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=180)
    resp.raise_for_status()
    return resp.json()


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
