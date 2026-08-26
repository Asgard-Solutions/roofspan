"""Static release guards for the packaged Control Plane/Mobile Access payload."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WINBUILD = REPO / "windows" / "winbuild"
STAGE = REPO / "windows" / "installer" / "stage.ps1"


def test_backend_spec_packages_control_plane_migrations_and_readiness_modules():
    spec = (WINBUILD / "roofspan-backend.spec").read_text(encoding="utf-8")
    assert '(os.path.join(BACKEND, "control_plane", "alembic.ini"), "control_plane")' in spec
    assert 'os.path.join("control_plane", "alembic")' in spec
    assert '"control_plane.bootstrap"' in spec
    assert '"control_plane.readiness"' in spec
    assert 'runtime_hooks=RUNTIME_HOOKS' in spec


def test_build_fails_when_cp_migration_payload_or_git_sha_is_missing():
    build = (WINBUILD / "build_exes.ps1").read_text(encoding="utf-8")
    for required in (
        "control_plane\\alembic.ini",
        "control_plane\\alembic\\env.py",
        "control_plane\\alembic\\versions",
        "Verified business + Control Plane Alembic assets",
        "ROOFSPAN_BUILD_INFO_HOOK",
        "git -C $repoRoot rev-parse HEAD",
    ):
        assert required in build


def test_stage_validates_control_plane_migration_payload():
    stage = STAGE.read_text(encoding="utf-8")
    for required in (
        "roofspan-backend\\_internal\\control_plane\\alembic.ini",
        "roofspan-backend\\_internal\\control_plane\\alembic\\env.py",
        "roofspan-backend\\_internal\\control_plane\\alembic\\versions",
    ):
        assert required in stage


def test_packaged_backend_uses_writable_control_plane_key_mirror():
    build = (WINBUILD / "build_exes.ps1").read_text(encoding="utf-8")
    assert "CP_DEV_SIGNING_KEYS_DIR" in build
    assert "C:\\ProgramData\\RoofSpan\\identity\\cp-signing-keys" in build
