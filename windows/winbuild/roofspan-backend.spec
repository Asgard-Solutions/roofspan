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
        # Business-database Alembic assets. backend/migrations_runner.py resolves these from
        # sys._MEIPASS (the ONEDIR _internal directory when frozen).
        (os.path.join(BACKEND, "alembic.ini"), "."),
        (os.path.join(BACKEND, "alembic"), "alembic"),
        # Embedded Control Plane has its OWN Alembic tree. control_plane/migrations_runner.py resolves
        # _ROOT from its frozen __file__, which is _internal/control_plane, so these assets must preserve
        # that exact relative layout. Without them Mobile Access starts but activation fails because the
        # Control Plane schema/tables (companies, installations, pairing_sessions, etc.) are never created.
        (os.path.join(BACKEND, "control_plane", "alembic.ini"), "control_plane"),
        (os.path.join(BACKEND, "control_plane", "alembic"), os.path.join("control_plane", "alembic")),
    ],
    hiddenimports=[
        "roofspan_service", "db_bootstrap", "migrations_runner", "win32crypt",
        "server", "uvicorn", "uvicorn.logging", "uvicorn.protocols",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on", "asyncpg", "sqlalchemy.dialects.postgresql", "alembic",
        "static_serve", "httpx", "websockets",
        # Property de-duplication and location upgrade/runtime dependencies.
        "property_dedup", "location_upgrade", "mapbox_geocoding",
        # MapTiler remains a separate visualization provider for satellite/building map layers.
        "maptiler", "mapbox_vector_tile", "shapely", "shapely.geometry",
    ] + PYWIN32,
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="roofspan-backend",
          console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="roofspan-backend")
