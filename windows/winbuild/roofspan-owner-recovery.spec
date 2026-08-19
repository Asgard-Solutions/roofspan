# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for RoofSpanOwnerRecovery.exe — local admin-only Owner password recovery tool.
# NOT a Windows service and NOT auto-started; an operator/recovery utility. HUMAN REQUIRED: build on
# Windows with backend requirements + requirements-windows.txt installed.
import os

BACKEND = os.path.abspath(os.path.join(SPECPATH, "..", "..", "backend"))
WINDOWS = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(SPECPATH, "owner_recovery.py")],
    pathex=[BACKEND, WINDOWS],
    binaries=[],
    datas=[],
    hiddenimports=["core", "models", "db", "asyncpg", "sqlalchemy.dialects.postgresql",
                   "winbuild.winservice", "winservice"],
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="RoofSpanOwnerRecovery",
          console=True, upx=False, onefile=True)
