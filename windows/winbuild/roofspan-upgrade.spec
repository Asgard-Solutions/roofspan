# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for roofspan-upgrade.exe - transactional upgrade coordinator (ONEFILE, console).
# Shipped as a Burn bundle payload (never inside the MSI) and copied to ProgramData for boot recovery.
import os

BACKEND = os.path.abspath(os.path.join(SPECPATH, "..", "..", "backend"))
WINDOWS = os.path.abspath(os.path.join(SPECPATH, ".."))
BUILD_INFO_HOOK = os.environ.get("ROOFSPAN_BUILD_INFO_HOOK", "")
RUNTIME_HOOKS = [BUILD_INFO_HOOK] if BUILD_INFO_HOOK and os.path.isfile(BUILD_INFO_HOOK) else []

PYWIN32 = ["win32serviceutil", "win32service", "win32security", "win32crypt", "win32com.client",
           "pywintypes", "win32api", "win32con", "winerror"]

a = Analysis(
    [os.path.join(SPECPATH, "upgrade_entry.py")],
    pathex=[BACKEND, WINDOWS],
    binaries=[],
    datas=[],
    hiddenimports=["build_identity", "_roofspan_build_identity", "db_bootstrap", "upgrade.coordinator",
                   "upgrade.pgops", "upgrade.winops", "psycopg", "psycopg_binary"] + PYWIN32,
    runtime_hooks=RUNTIME_HOOKS,
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="roofspan-upgrade",
          debug=False, strip=False, upx=False, console=True, uac_admin=True)
