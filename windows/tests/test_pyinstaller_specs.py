"""Guards the Windows PyInstaller specs against stale data paths.

Every source path referenced in a spec's `datas=[...]` MUST exist in the current repo, and the backend
spec MUST package the real Alembic layout that migrations_runner.py loads at runtime (alembic.ini at the
bundle root + the alembic/ tree under "alembic"). Fails fast so a repo layout change (e.g. migrations/ ->
alembic/) can never silently ship a broken installer.
"""
import glob
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # windows/
WINBUILD = os.path.join(HERE, "winbuild")
REPO = os.path.dirname(HERE)
BACKEND_DIR = os.path.join(REPO, "backend")
WINDOWS_DIR = HERE

BASES = {"BACKEND": BACKEND_DIR, "WINDOWS": WINDOWS_DIR}

# Matches:  (os.path.join(BACKEND, "a", "b"), "dest")
_DATA_TUPLE = re.compile(
    r"\(\s*os\.path\.join\(\s*(BACKEND|WINDOWS)\s*,\s*(.*?)\)\s*,\s*(['\"].*?['\"])\s*\)",
    re.S,
)
_QUOTED = re.compile(r"""['\"]([^'\"]*)['\"]""")


def _spec_files():
    return sorted(glob.glob(os.path.join(WINBUILD, "*.spec")))


def _read(p):
    with open(p) as f:
        return f.read()


def _data_entries(spec_text):
    """Return [(abs_source_path, dest)] for every os.path.join(BASE, ...) data source in the spec."""
    entries = []
    for base, join_tail, dest in _DATA_TUPLE.findall(spec_text):
        parts = _QUOTED.findall(join_tail)
        src = os.path.join(BASES[base], *parts)
        entries.append((src, _QUOTED.findall(dest)[0]))
    return entries


def test_all_spec_data_source_paths_exist():
    missing = []
    for spec in _spec_files():
        for src, _dest in _data_entries(_read(spec)):
            if not os.path.exists(src):
                missing.append(f"{os.path.basename(spec)} -> {src}")
    assert not missing, "stale PyInstaller data source path(s): " + "; ".join(missing)


def test_no_spec_references_removed_migrations_dir():
    # backend/migrations was renamed to backend/alembic; no spec may still point at the old folder.
    assert not os.path.isdir(os.path.join(BACKEND_DIR, "migrations"))
    for spec in _spec_files():
        text = _read(spec)
        assert '"migrations"' not in text and "'migrations'" not in text, (
            f"{os.path.basename(spec)} still references the removed 'migrations' folder"
        )


def test_backend_spec_packages_real_alembic_layout():
    spec = os.path.join(WINBUILD, "roofspan-backend.spec")
    entries = dict((os.path.relpath(src, BACKEND_DIR), dest) for src, dest in _data_entries(_read(spec)))
    # alembic.ini shipped at the bundle root; the alembic tree under "alembic".
    assert entries.get("alembic.ini") == "."
    assert entries.get("alembic") == "alembic"


def test_packaged_alembic_layout_matches_runtime_runner():
    # migrations_runner.py builds Config(join(root, "alembic.ini")) + script_location join(root, "alembic").
    runner = _read(os.path.join(BACKEND_DIR, "migrations_runner.py"))
    assert 'os.path.join(root, "alembic.ini")' in runner
    assert 'os.path.join(root, "alembic")' in runner
    # Everything the runner needs must exist in the source tree that the spec bundles.
    assert os.path.isfile(os.path.join(BACKEND_DIR, "alembic.ini"))
    assert os.path.isfile(os.path.join(BACKEND_DIR, "alembic", "env.py"))
    assert os.path.isfile(os.path.join(BACKEND_DIR, "alembic", "script.py.mako"))
    versions = glob.glob(os.path.join(BACKEND_DIR, "alembic", "versions", "*.py"))
    assert versions, "no Alembic version files found to package"
