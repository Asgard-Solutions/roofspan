# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for RoofSpanBootstrap.exe — first-install DB + deployed-config bootstrap tool.
# Runs once at install time (WiX custom action, before StartServices). NOT a service. HUMAN REQUIRED build.
import os

BACKEND = os.path.abspath(os.path.join(SPECPATH, "..", "..", "backend"))
WINDOWS = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(SPECPATH, "bootstrap_db.py")],
    pathex=[BACKEND, WINDOWS],
    binaries=[], datas=[], hiddenimports=[], excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="RoofSpanBootstrap",
          console=True, upx=False, onefile=True)
