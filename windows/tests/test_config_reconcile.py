"""Configuration ownership rules applied to an EXISTING roofspan.env (config_reconcile.py)."""
import os
import sys
from pathlib import Path

import pytest

WINBUILD = Path(__file__).resolve().parents[1] / "winbuild"
if str(WINBUILD) not in sys.path:
    sys.path.insert(0, str(WINBUILD))

import config_reconcile as cr

TEMPLATE = WINBUILD / "config" / "roofspan.env.template"
SECRET_LINES = [
    "DATABASE_URL=postgresql+asyncpg://roofspan:Keep%40Me9999@127.0.0.1:5442/roofspan",
    "JWT_SECRET=keep-this-jwt-secret-value",
    "SECRETS_ENCRYPTION_KEY=MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=",
    "CONTROL_PLANE_DATABASE_URL=postgresql+asyncpg://roofspan:Keep%40Me9999@127.0.0.1:5442/roofspan",
]
CUSTOMER_LINES = [
    "# customer comment kept",
    "CONTROL_PLANE_BASE_URL=https://cp.customer-proxy.example",
    "ROOFSPAN_OFFSITE_BACKUP_DIR=\\\\NAS\\Share\\RoofSpan",
    "INSTALLATION_KEYS_DIR=D:\\RoofSpanData\\identity",
    "SOME_UNKNOWN_FUTURE_KEY=keep me",
]


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a):
        self.lines.append(msg % a if a else msg)


def _install(tmp_path):
    root = tmp_path / "Program Files" / "RoofSpan Office"
    (root / "frontend").mkdir(parents=True)
    (root / "config-templates").mkdir()
    (root / "config-templates" / "update_public_key.pem").write_text("pub")
    return root


def _write(path, lines, eol="\n", bom=False):
    data = eol.join(lines) + eol
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data.encode("utf-8"))


@pytest.mark.parametrize("eol,bom", [("\n", False), ("\r\n", True)])
def test_reconcile_applies_ownership_rules(tmp_path, eol, bom):
    install = _install(tmp_path)
    cfg = tmp_path / "roofspan.env"
    existing_static = tmp_path / "custom-frontend"
    existing_static.mkdir()
    _write(cfg, SECRET_LINES + CUSTOMER_LINES + [
        "ROOFSPAN_VERSION=0.4.5",
        "ROOFSPAN_BUILD_SHA=" + "0" * 40,
        f"ROOFSPAN_STATIC_DIR={existing_static}",                         # still exists -> preserved
        "ROOFSPAN_UPDATE_PUBLIC_KEY=C:\\Old Location\\update_public_key.pem",  # gone -> refreshed
    ], eol=eol, bom=bom)
    log = _Log()

    changes = cr.reconcile(str(cfg), str(TEMPLATE), str(install), log)
    raw = cfg.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") == bom
    text = raw.decode("utf-8-sig")
    lines = text.split(eol)

    # Build identity: removed.
    assert changes["removed"] == ["ROOFSPAN_VERSION", "ROOFSPAN_BUILD_SHA"]
    assert "ROOFSPAN_VERSION" not in text and "ROOFSPAN_BUILD_SHA" not in text
    # Secrets, DB credentials, customer settings, unknown keys and comments: byte-for-byte.
    for line in SECRET_LINES + CUSTOMER_LINES:
        assert line in lines, line
        if "=" in line:
            assert sum(1 for x in lines if x.startswith(line.split("=")[0] + "=")) == 1, line
    # Installation-owned paths: refreshed only when the saved path is gone.
    assert f"ROOFSPAN_STATIC_DIR={existing_static}" in lines
    assert f"ROOFSPAN_UPDATE_PUBLIC_KEY={install / 'config-templates' / 'update_public_key.pem'}" in lines
    assert changes["refreshed"] == ["ROOFSPAN_UPDATE_PUBLIC_KEY"]
    # Missing supported defaults: added; generated placeholders and secrets never added.
    for key in ("PHOTO_STORAGE_DIR", "ROOFSPAN_BACKUP_DIR", "ROOFSPAN_PG_BIN", "ROOFSPAN_WINDOWS_UPDATE_MANIFEST_URL"):
        assert key in changes["added"], key
        assert sum(1 for x in lines if x.startswith(key + "=")) == 1
    assert "__GENERATED" not in text
    for key in ("JWT_SECRET", "SECRETS_ENCRYPTION_KEY", "DATABASE_URL", "INSTALLATION_KEYS_DIR",
                "CONTROL_PLANE_BASE_URL", "ROOFSPAN_OFFSITE_BACKUP_DIR"):
        assert key not in changes["added"], key
    # Line endings stay consistent; no temp file left behind (atomic replace).
    if eol == "\r\n":
        assert "\n" not in text.replace("\r\n", "")
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())
    # Only key names are logged.
    logged = "\n".join(log.lines)
    assert "keep-this-jwt-secret-value" not in logged and "Keep%40Me9999" not in logged and "0.4.5" not in logged


def test_reconcile_is_idempotent(tmp_path):
    install = _install(tmp_path)
    cfg = tmp_path / "roofspan.env"
    _write(cfg, SECRET_LINES + ["ROOFSPAN_VERSION=0.4.5"])
    cr.reconcile(str(cfg), str(TEMPLATE), str(install), _Log())
    first = cfg.read_bytes()
    mtime = os.stat(cfg).st_mtime_ns
    log = _Log()
    changes = cr.reconcile(str(cfg), str(TEMPLATE), str(install), log)
    assert changes == {"removed": [], "refreshed": [], "added": []}
    assert cfg.read_bytes() == first and os.stat(cfg).st_mtime_ns == mtime and not log.lines


def test_reconcile_does_not_refresh_when_installed_path_is_missing(tmp_path):
    cfg = tmp_path / "roofspan.env"
    _write(cfg, SECRET_LINES + ["ROOFSPAN_STATIC_DIR=C:\\Gone\\frontend"])
    changes = cr.reconcile(str(cfg), str(TEMPLATE), str(tmp_path / "not-installed"), _Log())
    assert "ROOFSPAN_STATIC_DIR=C:\\Gone\\frontend" in cfg.read_text().splitlines()
    assert "ROOFSPAN_STATIC_DIR" not in changes["refreshed"]


def test_first_install_is_left_to_bootstrap(tmp_path):
    cfg = tmp_path / "missing.env"
    assert cr.reconcile(str(cfg), str(TEMPLATE), str(tmp_path), _Log()) == {"removed": [], "refreshed": [], "added": []}
    assert not cfg.exists()


def test_reconcile_then_bootstrap_rotates_nothing(tmp_path, monkeypatch):
    import db_bootstrap as boot
    install = _install(tmp_path)
    cfg = tmp_path / "config" / "roofspan.env"
    cfg.parent.mkdir()
    _write(cfg, SECRET_LINES + ["ROOFSPAN_VERSION=0.4.5"])
    monkeypatch.setattr(boot, "decrypt_super_password", lambda *a: pytest.fail("no DPAPI for a provisioned config"))
    monkeypatch.setattr(boot, "repair_control_plane_db", lambda *a, **k: None)
    for k in ("DATABASE_URL", "JWT_SECRET", "SECRETS_ENCRYPTION_KEY", "CONTROL_PLANE_DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    cr.reconcile(str(cfg), str(TEMPLATE), str(install), _Log())
    boot.bootstrap(_Log(), str(TEMPLATE), str(cfg), str(tmp_path / "identity"))
    lines = cfg.read_text().splitlines()
    for line in SECRET_LINES:
        assert line in lines
        k, v = line.split("=", 1)
        assert os.environ[k] == v
