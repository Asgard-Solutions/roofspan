# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for roofspan-update-service.exe (12h signed-update checker).
import os

BACKEND = os.path.abspath(os.path.join(SPECPATH, "..", "..", "backend"))
WINDOWS = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(SPECPATH, "update_service_entry.py")],
    pathex=[BACKEND, WINDOWS],
    binaries=[],
    datas=[],
    hiddenimports=["updater.manifest", "updater.signing", "updater.service",
                   "updater.orchestrator", "httpx",
                   # Windows service host (pywin32 SCM integration) + reusable runner.
                   "winbuild.winservice", "winservice",
                   "win32serviceutil", "win32service", "win32event", "servicemanager", "win32timezone"],
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="roofspan-update-service",
          console=True, upx=False, onefile=True)
