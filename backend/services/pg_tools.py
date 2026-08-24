"""Locate the PostgreSQL client executables (pg_dump / pg_restore / psql) explicitly.

RoofSpan Office bundles EDB PostgreSQL on Windows, which installs to
``C:\\Program Files\\PostgreSQL\\<major>\\bin`` (major 16 for the shipped build). Backup/restore
MUST invoke those executables by full path and NEVER rely on the Windows PATH (the RoofSpan
service account often has a minimal PATH, and multiple PostgreSQL versions may be present).

Resolution order:
  1. Per-tool env override      (ROOFSPAN_PG_DUMP / ROOFSPAN_PG_RESTORE / ROOFSPAN_PSQL)
  2. Explicit bin dir override  (ROOFSPAN_PG_BIN)
  3. Windows: Program Files\\PostgreSQL\\<major>\\bin (newest first) + registry installations
  4. System PATH               (shutil.which) — primarily for POSIX/dev
If none is found, a clear, actionable error is raised (naming the expected location).
"""
from __future__ import annotations

import os
import shutil

# Newest first. RoofSpan ships PostgreSQL 16; others are accepted if present.
_PG_MAJORS = ("17", "16", "15", "14", "13")
# The version RoofSpan expects/ships — used only to build a helpful error message.
EXPECTED_PG_VERSION = os.environ.get("ROOFSPAN_PG_VERSION", "16")

_PER_TOOL_ENV = {
    "pg_dump": "ROOFSPAN_PG_DUMP",
    "pg_restore": "ROOFSPAN_PG_RESTORE",
    "psql": "ROOFSPAN_PSQL",
}


def _exe_name(tool: str) -> str:
    return f"{tool}.exe" if os.name == "nt" else tool


def _program_files_roots() -> list[str]:
    roots = [
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        r"C:\Program Files",
        r"C:\Program Files (x86)",
    ]
    seen, out = set(), []
    for r in roots:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _registry_bin_dirs() -> list[str]:
    """Read PostgreSQL install locations declared under HKLM\\SOFTWARE\\PostgreSQL\\Installations."""
    if os.name != "nt":
        return []
    dirs: list[str] = []
    try:
        import winreg  # type: ignore
        for root in (winreg.HKEY_LOCAL_MACHINE,):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    base = winreg.OpenKey(root, r"SOFTWARE\PostgreSQL\Installations", 0,
                                          winreg.KEY_READ | view)
                except OSError:
                    continue
                try:
                    i = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(base, i)
                        except OSError:
                            break
                        i += 1
                        try:
                            k = winreg.OpenKey(base, sub, 0, winreg.KEY_READ | view)
                            loc, _ = winreg.QueryValueEx(k, "Base Directory")
                            if loc:
                                dirs.append(os.path.join(loc, "bin"))
                        except OSError:
                            continue
                finally:
                    winreg.CloseKey(base)
    except Exception:
        return dirs
    return dirs


def _windows_bin_dirs() -> list[str]:
    dirs: list[str] = []
    for major in _PG_MAJORS:
        for root in _program_files_roots():
            dirs.append(os.path.join(root, "PostgreSQL", major, "bin"))
    dirs.extend(_registry_bin_dirs())
    return dirs


def expected_location() -> str:
    if os.name == "nt":
        root = _program_files_roots()[0]
        return os.path.join(root, "PostgreSQL", EXPECTED_PG_VERSION, "bin")
    return "the system PATH"


def resolve_executable(tool: str) -> str:
    """Return an absolute path to the requested PostgreSQL executable, or raise a clear error."""
    if tool not in _PER_TOOL_ENV:
        raise ValueError(f"Unknown PostgreSQL tool '{tool}'")
    exe = _exe_name(tool)

    # 1. Per-tool explicit override.
    override = os.environ.get(_PER_TOOL_ENV[tool])
    if override and os.path.isfile(override):
        return override

    # 2. Explicit bin directory override.
    bin_dir = os.environ.get("ROOFSPAN_PG_BIN")
    if bin_dir:
        cand = os.path.join(bin_dir, exe)
        if os.path.isfile(cand):
            return cand

    # 3. Windows well-known install locations + registry (newest version first).
    if os.name == "nt":
        for d in _windows_bin_dirs():
            cand = os.path.join(d, exe)
            if os.path.isfile(cand):
                return cand

    # 4. System PATH (POSIX/dev, and Windows as a last resort).
    found = shutil.which(tool) or (shutil.which(exe) if exe != tool else None)
    if found:
        return found

    raise RuntimeError(
        f"PostgreSQL backup tools could not be located. RoofSpan expected PostgreSQL "
        f"{EXPECTED_PG_VERSION} at {expected_location()} (could not find {exe}). "
        f"Set ROOFSPAN_PG_BIN to the PostgreSQL 'bin' folder if it is installed elsewhere."
    )
