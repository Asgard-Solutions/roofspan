# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for roofspan-update-service.exe - RoofSpanUpdateService Windows SCM service.
# ONEDIR (COLLECT) + explicit pywin32 service modules (see roofspan-backend.spec for rationale).
import os

BACKEND = os.path.abspath(os.path.join(SPECPATH, "..", "..", "backend"))
WINDOWS = os.path.abspath(os.path.join(SPECPATH, ".."))
BUILD_INFO_HOOK = os.environ.get("ROOFSPAN_BUILD_INFO_HOOK", "")
RUNTIME_HOOKS = [BUILD_INFO_HOOK] if BUILD_INFO_HOOK and os.path.isfile(BUILD_INFO_HOOK) else []

PYWIN32 = ["win32serviceutil", "win32service", "win32event", "servicemanager",
           "pywintypes", "win32api", "win32con", "winerror", "win32timezone"]

a = Analysis(
    [os.path.join(SPECPATH, "update_service_entry.py")],
    pathex=[BACKEND, WINDOWS],
    binaries=[],
    datas=[],
    hiddenimports=["roofspan_service", "build_identity", "_roofspan_build_identity", "updater.manifest", "updater.signing", "updater.service",
                   "updater.orchestrator", "httpx"] + PYWIN32,
    runtime_hooks=RUNTIME_HOOKS,
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="roofspan-update-service",
          console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="roofspan-update-service")
