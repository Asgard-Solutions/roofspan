# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for RoofSpanOffice.exe -- the Desktop/Start-Menu launcher that opens the local
# RoofSpan Office UI in the default browser. Windowless (console=False) so no console flashes. NOT a
# service and NOT auto-started. HUMAN REQUIRED: build on Windows.
import os

WINDOWS = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(WINDOWS, "installer", "RoofSpanOffice.ico")

a = Analysis(
    [os.path.join(SPECPATH, "office_launcher.py")],
    pathex=[WINDOWS],
    binaries=[],
    datas=[],
    hiddenimports=[],
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="RoofSpanOffice",
          console=False, upx=False, onefile=True,
          icon=(ICON if os.path.isfile(ICON) else None))
