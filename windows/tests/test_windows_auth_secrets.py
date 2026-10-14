import base64
import os
import sys
from pathlib import Path

WINBUILD = Path(__file__).resolve().parents[1] / "winbuild"
sys.path.insert(0, str(WINBUILD))

import db_bootstrap as boot  # noqa: E402


class _Logger:
    def __init__(self):
        self.errors = []

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, msg, *a, **k):
        self.errors.append(msg % a if a else msg)


def test_generated_runtime_secrets_are_valid():
    jwt_secret = boot.generate_jwt_secret()
    enc = boot.generate_secrets_encryption_key()
    assert len(jwt_secret) >= 48
    assert len(base64.urlsafe_b64decode(enc.encode("ascii"))) == 32


def test_existing_config_repairs_missing_auth_secrets_without_rotating_db_password(tmp_path, monkeypatch):
    cfg = tmp_path / "config" / "roofspan.env"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "DATABASE_URL=postgresql+asyncpg://roofspan:KeepMe9999@127.0.0.1:5432/roofspan\n"
        "ROOFSPAN_VERSION=0.2.0\n",
        encoding="utf-8",
    )

    def _boom(*a, **k):
        raise AssertionError("must not contact PostgreSQL/DPAPI for a provisioned config")

    monkeypatch.setattr(boot, "decrypt_super_password", _boom)
    # Control Plane storage repair (which may contact PostgreSQL) has its own tests; here it is recorded only.
    repairs = []
    monkeypatch.setattr(boot, "repair_control_plane_db", lambda logger, identity_dir, url: repairs.append(url))
    for key in ("DATABASE_URL", "JWT_SECRET", "SECRETS_ENCRYPTION_KEY"):
        monkeypatch.delenv(key, raising=False)

    url = boot.bootstrap(_Logger(), str(tmp_path / "unused-template"), str(cfg), str(tmp_path / "identity"))
    text = cfg.read_text(encoding="utf-8")
    assert repairs == [url], "CP repair must use the preserved business DATABASE_URL"

    assert url.endswith("KeepMe9999@127.0.0.1:5432/roofspan")
    assert text.count("JWT_SECRET=") == 1
    assert text.count("SECRETS_ENCRYPTION_KEY=") == 1
    assert "KeepMe9999" in text
    assert os.environ["JWT_SECRET"]
    assert len(base64.urlsafe_b64decode(os.environ["SECRETS_ENCRYPTION_KEY"].encode("ascii"))) == 32


def test_auth_secret_repair_is_idempotent(tmp_path):
    cfg = tmp_path / "roofspan.env"
    cfg.write_text(
        "DATABASE_URL=postgresql+asyncpg://roofspan:KeepMe9999@127.0.0.1:5432/roofspan\n"
        "JWT_SECRET=keep-jwt\n"
        "SECRETS_ENCRYPTION_KEY=" + base64.urlsafe_b64encode(b"1" * 32).decode("ascii") + "\n",
        encoding="utf-8",
    )
    before = cfg.read_text(encoding="utf-8")
    boot.ensure_required_runtime_secrets(str(cfg), _Logger())
    assert cfg.read_text(encoding="utf-8") == before


def test_template_contains_only_auth_secret_placeholders():
    tpl = (WINBUILD / "config" / "roofspan.env.template").read_text(encoding="utf-8")
    assert "JWT_SECRET=__GENERATED_JWT_SECRET__" in tpl
    assert "SECRETS_ENCRYPTION_KEY=__GENERATED_SECRETS_ENCRYPTION_KEY__" in tpl


def test_control_plane_repair_failure_is_non_fatal_and_secrets_are_still_repaired(tmp_path, monkeypatch):
    cfg = tmp_path / "config" / "roofspan.env"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:KeepMe9999@127.0.0.1:5432/roofspan\n", encoding="utf-8")

    def _pg_down(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(boot, "repair_control_plane_db", _pg_down)
    for key in ("DATABASE_URL", "JWT_SECRET", "SECRETS_ENCRYPTION_KEY"):
        monkeypatch.delenv(key, raising=False)
    log = _Logger()
    url = boot.bootstrap(log, str(tmp_path / "unused-template"), str(cfg), str(tmp_path / "identity"))
    assert url.endswith("KeepMe9999@127.0.0.1:5432/roofspan")
    assert "JWT_SECRET=" in cfg.read_text(encoding="utf-8")
    assert len(log.errors) == 1 and "Control Plane storage repair FAILED" in log.errors[0] and "OSError" in log.errors[0]
