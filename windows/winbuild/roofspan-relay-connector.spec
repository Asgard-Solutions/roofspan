# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for roofspan-relay-connector.exe (outbound-only Secure Relay tunnel).
import os

BACKEND = os.path.abspath(os.path.join(SPECPATH, "..", "..", "backend"))
WINDOWS = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(SPECPATH, "relay_entry.py")],
    pathex=[BACKEND, WINDOWS],
    binaries=[],
    datas=[],
    hiddenimports=["relay.tunnel_client", "relay.protocol", "licensing.identity",
                   "licensing.reqsig", "httpx", "websockets"],
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="roofspan-relay-connector",
          console=True, upx=False, onefile=True)
