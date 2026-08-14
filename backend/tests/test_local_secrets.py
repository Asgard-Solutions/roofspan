"""P1-4a: per-installation local secrets + double-gated Owner seed."""
import base64
import importlib
import os

import pytest

import local_secrets


@pytest.fixture
def secret_env(tmp_path):
    keys = ["JWT_SECRET", "SECRETS_ENCRYPTION_KEY", "ROOFSPAN_SECRETS_DIR"]
    saved = {k: os.environ.get(k) for k in keys}
    for k in ("JWT_SECRET", "SECRETS_ENCRYPTION_KEY"):
        os.environ.pop(k, None)
    os.environ["ROOFSPAN_SECRETS_DIR"] = str(tmp_path)
    yield tmp_path
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_generates_and_persists_when_missing(secret_env):
    local_secrets.ensure_local_secrets()
    assert os.environ["JWT_SECRET"]
    assert len(base64.urlsafe_b64decode(os.environ["SECRETS_ENCRYPTION_KEY"])) == 32  # AES-256 key
    assert (secret_env / "secrets.env").is_file()


def test_reused_across_restart(secret_env):
    local_secrets.ensure_local_secrets()
    jwt1, enc1 = os.environ["JWT_SECRET"], os.environ["SECRETS_ENCRYPTION_KEY"]
    # simulate a restart: clear env, load again -> SAME persisted values (not regenerated)
    del os.environ["JWT_SECRET"], os.environ["SECRETS_ENCRYPTION_KEY"]
    local_secrets.ensure_local_secrets()
    assert os.environ["JWT_SECRET"] == jwt1
    assert os.environ["SECRETS_ENCRYPTION_KEY"] == enc1


def test_environment_wins_and_is_not_persisted(secret_env):
    os.environ["JWT_SECRET"] = "provided-by-env"
    os.environ["SECRETS_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
    local_secrets.ensure_local_secrets()
    assert os.environ["JWT_SECRET"] == "provided-by-env"
    # nothing missing -> no file written
    assert not (secret_env / "secrets.env").exists()


def test_fail_closed_when_persist_fails(secret_env):
    # point secrets dir at an unwritable location -> generation must FAIL CLOSED (never ephemeral)
    os.environ["ROOFSPAN_SECRETS_DIR"] = "/proc/roofspan-cannot-write"
    with pytest.raises(RuntimeError):
        local_secrets.ensure_local_secrets()


def test_upgrade_does_not_regenerate_existing_secrets(secret_env, caplog):
    """P0 req 5: an in-place upgrade (secrets.env already present under preserved ProgramData) must
    reuse the persisted secrets and NOT regenerate them (regenerating SECRETS_ENCRYPTION_KEY would
    make locally-encrypted integration credentials undecryptable)."""
    local_secrets.ensure_local_secrets()
    jwt1, enc1 = os.environ["JWT_SECRET"], os.environ["SECRETS_ENCRYPTION_KEY"]
    # simulate the upgraded backend starting fresh: env cleared, same persisted secrets.env present
    del os.environ["JWT_SECRET"], os.environ["SECRETS_ENCRYPTION_KEY"]
    with caplog.at_level("INFO", logger="roofspan.secrets"):
        local_secrets.ensure_local_secrets()
    assert os.environ["JWT_SECRET"] == jwt1
    assert os.environ["SECRETS_ENCRYPTION_KEY"] == enc1
    assert "Generated" not in caplog.text  # no new-secret generation on upgrade


def test_only_missing_secret_is_generated_others_preserved(secret_env):
    """If one persistent secret already exists, only the genuinely-missing one is generated; the
    existing value is preserved (idempotent merge)."""
    (secret_env / "secrets.env").write_text("JWT_SECRET=preserved-jwt\n")
    local_secrets.ensure_local_secrets()
    assert os.environ["JWT_SECRET"] == "preserved-jwt"          # kept as-is
    assert os.environ["SECRETS_ENCRYPTION_KEY"]                 # generated
    body = (secret_env / "secrets.env").read_text()
    assert "JWT_SECRET=preserved-jwt" in body and "SECRETS_ENCRYPTION_KEY=" in body



def test_owner_seed_double_gated(monkeypatch):
    import server
    from licensing import config as lc
    # production licensing mode: impossible even if the flag is set
    monkeypatch.setattr(lc, "LICENSING_MODE", "http")
    monkeypatch.setenv("ROOFSPAN_OWNER_SEED", "enabled")
    assert server._owner_seed_enabled() is False
    # dev mode: requires the explicit opt-in
    monkeypatch.setattr(lc, "LICENSING_MODE", "dev")
    monkeypatch.setenv("ROOFSPAN_OWNER_SEED", "enabled")
    assert server._owner_seed_enabled() is True
    monkeypatch.delenv("ROOFSPAN_OWNER_SEED", raising=False)
    assert server._owner_seed_enabled() is False
