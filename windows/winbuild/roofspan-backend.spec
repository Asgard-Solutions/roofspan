# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for roofspan-backend.exe (local RoofSpan Office API + Office UI).
# HUMAN REQUIRED: run on Windows with `pip install pyinstaller` + the backend requirements installed.
# Tune hiddenimports/datas on the first native build if a lazy import is missed.
import os

BACKEND = os.path.abspath(os.path.join(SPECPATH, "..", "..", "backend"))
WINDOWS = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(SPECPATH, "backend_entry.py")],
    pathex=[BACKEND, WINDOWS],
    binaries=[],
    datas=[
        # migrations_runner.py loads alembic.ini + the alembic/ tree from its own directory (== the
        # PyInstaller _MEIPASS root at runtime), so mirror that layout: alembic.ini at the root and the
        # real backend/alembic package (env.py, script.py.mako, versions/*.py) under "alembic".
        (os.path.join(BACKEND, "alembic.ini"), "."),
        (os.path.join(BACKEND, "alembic"), "alembic"),
    ],
    hiddenimports=[
        "server", "uvicorn", "uvicorn.logging", "uvicorn.protocols",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on", "asyncpg", "sqlalchemy.dialects.postgresql", "alembic",
        "static_serve", "httpx", "websockets",
        # Windows service host (pywin32 SCM integration) + reusable runner.
        "winbuild.winservice", "winservice",
        "win32serviceutil", "win32service", "win32event", "servicemanager", "win32timezone",
    ],
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="roofspan-backend",
          console=True, upx=False, onefile=True)
