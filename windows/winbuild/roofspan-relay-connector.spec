# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for roofspan-relay-connector.exe - RoofSpanRelayConnector Windows SCM service.
# ONEDIR (COLLECT) + explicit pywin32 service modules (see roofspan-backend.spec for rationale).
import os

BACKEND = os.path.abspath(os.path.join(SPECPATH, "..", "..", "backend"))
WINDOWS = os.path.abspath(os.path.join(SPECPATH, ".."))

PYWIN32 = ["win32serviceutil", "win32service", "win32event", "servicemanager",
           "pywintypes", "win32api", "win32con", "winerror", "win32timezone"]

a = Analysis(
    [os.path.join(SPECPATH, "relay_entry.py")],
    pathex=[BACKEND, WINDOWS],
    binaries=[],
    datas=[],
    hiddenimports=["roofspan_service", "relay.tunnel_client", "relay.protocol",
                   "licensing.identity", "licensing.reqsig", "httpx", "websockets"] + PYWIN32,
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="roofspan-relay-connector",
          console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="roofspan-relay-connector")
