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
        (os.path.join(BACKEND, "alembic.ini"), "."),
        (os.path.join(BACKEND, "alembic"), "alembic"),
    ],
    hiddenimports=[
        "server", "uvicorn", "uvicorn.logging", "uvicorn.protocols",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on", "asyncpg", "sqlalchemy.dialects.postgresql", "alembic",
        "static_serve", "httpx", "websockets",
    ],
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="roofspan-backend",
          console=True, upx=False, onefile=True)
