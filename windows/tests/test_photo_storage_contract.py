r"""Regression contract for RoofSpan Field photo persistence on installed Windows Office.

These tests intentionally cover the production boundary that the mobile-only tests cannot:
RoofSpanBackend runs as NT SERVICE\RoofSpanBackend and therefore needs an explicit, persistent,
writable ProgramData photo directory. Photos must never fall back to the frozen Program Files tree.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WINBUILD = ROOT / "windows" / "winbuild"
sys.path.insert(0, str(WINBUILD))

import roofspan_service as rs  # noqa: E402


def test_runtime_config_defaults_photo_storage_to_persistent_data_root(tmp_path, monkeypatch):
    for key in (
        "PHOTO_STORAGE_DIR",
        "ROOFSPAN_DATA_ROOT",
        "ROOFSPAN_INSTALL_ROOT",
        "ROOFSPAN_STATIC_DIR",
        "INSTALLATION_KEYS_DIR",
        "ROOFSPAN_UPDATE_PUBLIC_KEY",
        "ROOFSPAN_RELAY_WS_URL",
        "ROOFSPAN_LOCAL_API_URL",
        "ROOFSPAN_WINDOWS_UPDATE_MANIFEST_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    install = tmp_path / "install"
    (install / "frontend").mkdir(parents=True)
    data = tmp_path / "data"
    (data / "config").mkdir(parents=True)
    monkeypatch.setenv("ROOFSPAN_INSTALL_ROOT", str(install))
    monkeypatch.setenv("ROOFSPAN_DATA_ROOT", str(data))

    rs.load_runtime_config()

    assert os.environ["PHOTO_STORAGE_DIR"] == str(data / "images")


def test_shipped_template_points_photo_storage_at_programdata():
    template = (WINBUILD / "config" / "roofspan.env.template").read_text(encoding="utf-8")
    assert r"PHOTO_STORAGE_DIR=C:\ProgramData\RoofSpan\images" in template


def test_installer_creates_persistent_images_dir_with_backend_write_acl():
    wxs = (ROOT / "windows" / "installer" / "RoofSpan.wxs").read_text(encoding="utf-8")
    assert '<Directory Id="ImagesDir" Name="images" />' in wxs
    block = re.search(r'<Component Id="ImagesDirAcl".*?</Component>', wxs, flags=re.S)
    assert block, "installer must author an ImagesDirAcl component"
    acl = block.group(0)
    assert 'Directory="ImagesDir"' in acl
    assert 'User="RoofSpanBackend"' in acl and 'Domain="NT SERVICE"' in acl
    assert 'GenericRead="yes"' in acl and 'GenericWrite="yes"' in acl
    assert '<ComponentRef Id="ImagesDirAcl" />' in wxs


def test_object_storage_has_programdata_safe_windows_fallback_and_atomic_write():
    src = (ROOT / "backend" / "services" / "object_storage.py").read_text(encoding="utf-8")
    assert "ROOFSPAN_DATA_ROOT" in src
    assert "PROGRAMDATA" in src
    assert '"images"' in src
    assert "os.replace(" in src, "local photo writes must be atomic"
    assert "os.fsync(" in src, "photo bytes must be flushed before the authoritative path is replaced"


def test_backend_refuses_to_start_when_photo_storage_is_not_writable():
    storage = (ROOT / "backend" / "services" / "object_storage.py").read_text(encoding="utf-8")
    entry = (WINBUILD / "backend_entry.py").read_text(encoding="utf-8")
    assert "def ensure_storage_ready" in storage
    assert "ensure_storage_ready()" in entry
    assert entry.index("ensure_storage_ready()") < entry.index('uvicorn.Config("server:app"'), \
        "photo-storage write probe must run before Office reports the backend ready"
