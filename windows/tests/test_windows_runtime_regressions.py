from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WINBUILD = ROOT / "windows" / "winbuild"
BACKEND = ROOT / "backend"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_windows_backend_preapplies_migrations_before_uvicorn():
    src = _read(WINBUILD / "backend_entry.py")
    assert "from migrations_runner import run_migrations" in src
    assert src.index("run_migrations()") < src.index('uvicorn.Config("server:app"')
    assert 'os.environ["ROOFSPAN_MIGRATIONS_PREAPPLIED"] = "1"' in src
    assert "log_config=None" in src
    assert "use_colors=False" in src


def test_fastapi_skips_second_migration_when_windows_preapplied():
    src = _read(BACKEND / "server.py")
    assert 'os.environ.get("ROOFSPAN_MIGRATIONS_PREAPPLIED") != "1"' in src
    assert "await asyncio.to_thread(run_migrations)" in src


def test_programmatic_alembic_does_not_replace_service_logging():
    runner = _read(BACKEND / "migrations_runner.py")
    env = _read(BACKEND / "alembic" / "env.py")
    assert 'cfg.attributes["configure_logger"] = False' in runner
    assert 'config.attributes.get("configure_logger", True)' in env
    assert "ScriptDirectory.from_config(cfg)" in runner
    assert 'logger.exception("Alembic migration failed")' in runner


def test_service_logger_is_consoleless_safe_and_nonduplicating():
    src = _read(WINBUILD / "roofspan_service.py")
    assert "log.propagate = False" in src
    assert "if sys.stderr is not None:" in src
    assert "logging.StreamHandler(sys.stderr)" in src


def test_freeze_cleans_stale_alembic_bytecode_and_old_outputs():
    src = _read(WINBUILD / "build_exes.ps1")
    assert 'Filter "__pycache__"' in src
    assert "*.pyc,*.pyo" in src
    assert 'Join-Path $PSScriptRoot "dist"' in src
    assert 'Join-Path $PSScriptRoot "build"' in src
    assert "Stale Alembic bytecode remains after cleanup" in src


def test_backend_spec_pins_migration_runner():
    src = _read(WINBUILD / "roofspan-backend.spec")
    assert '"migrations_runner"' in src


def test_released_orphaned_revision_is_explicitly_reconciled():
    src = _read(BACKEND / "migrations_runner.py")
    assert 'LEGACY_ORPHANED_REVISIONS = {"c1d2e3f4a5b6"}' in src
    assert "_infer_legacy_revision_from_schema" in src
    assert "_reconcile_orphaned_released_revision" in src
    assert "BASELINE_SCHEMA_TABLES" in src
    assert "UPDATE alembic_version SET version_num=%s WHERE version_num=%s" in src
    # Never silently accept arbitrary unknown migration ids (message is split across two string literals).
    assert "will not " in src
    assert "guess or rewrite migration history for an unrecognized database" in src
    # Reconciliation must happen before Alembic attempts the normal upgrade.
    assert src.index("_reconcile_orphaned_released_revision(script)") < src.index('command.upgrade(cfg, "head")')
