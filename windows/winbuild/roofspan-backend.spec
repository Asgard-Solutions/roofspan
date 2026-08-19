# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for roofspan-backend.exe - RoofSpanBackend Windows SCM service.
# ONEDIR (COLLECT): reliable for pywin32 services - SCM launches the real service exe directly (no
# onefile bootloader child process that would break the SCM start handshake). pywin32 service modules
# are packaged explicitly so the frozen exe can host the Service Control dispatcher.
# HUMAN REQUIRED: run on Windows with pyinstaller + backend requirements + pywin32 installed.
import os

BACKEND = os.path.abspath(os.path.join(SPECPATH, "..", "..", "backend"))
WINDOWS = os.path.abspath(os.path.join(SPECPATH, ".."))

PYWIN32 = ["win32serviceutil", "win32service", "win32event", "servicemanager",
           "pywintypes", "win32api", "win32con", "winerror", "win32timezone"]

a = Analysis(
    [os.path.join(SPECPATH, "backend_entry.py")],
    pathex=[BACKEND, WINDOWS],
    binaries=[],
    datas=[
        (os.path.join(BACKEND, "alembic.ini"), "."),
        (os.path.join(BACKEND, "alembic"), "alembic"),
    ],
    hiddenimports=[
        "roofspan_service",
        "server", "uvicorn", "uvicorn.logging", "uvicorn.protocols",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on", "asyncpg", "sqlalchemy.dialects.postgresql", "alembic",
        "static_serve", "httpx", "websockets",
    ] + PYWIN32,
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="roofspan-backend",
          console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="roofspan-backend")
