# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for roofspan-backend.exe - RoofSpanBackend Windows SCM service.
import os

BACKEND = os.path.abspath(os.path.join(SPECPATH, "..", "..", "backend"))
WINDOWS = os.path.abspath(os.path.join(SPECPATH, ".."))
BUILD_INFO_HOOK = os.environ.get("ROOFSPAN_BUILD_INFO_HOOK", "")
RUNTIME_HOOKS = [BUILD_INFO_HOOK] if BUILD_INFO_HOOK and os.path.isfile(BUILD_INFO_HOOK) else []

PYWIN32 = [
    "win32serviceutil", "win32service", "win32event", "servicemanager",
    "pywintypes", "win32api", "win32con", "winerror", "win32timezone",
]

a = Analysis(
    [os.path.join(SPECPATH, "backend_entry.py")],
    pathex=[BACKEND, WINDOWS],
    binaries=[],
    datas=[
        # Business-database Alembic assets.
        (os.path.join(BACKEND, "alembic.ini"), "."),
        (os.path.join(BACKEND, "alembic"), "alembic"),
        # Embedded Control Plane has its own Alembic tree. Preserve the relative layout expected by
        # control_plane/migrations_runner.py in the frozen _internal/control_plane directory.
        (os.path.join(BACKEND, "control_plane", "alembic.ini"), "control_plane"),
        (os.path.join(BACKEND, "control_plane", "alembic"), os.path.join("control_plane", "alembic")),
    ],
    hiddenimports=[
        "roofspan_service", "db_bootstrap", "migrations_runner", "win32crypt",
        "server", "uvicorn", "uvicorn.logging", "uvicorn.protocols",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on", "asyncpg", "sqlalchemy.dialects.postgresql", "alembic",
        "static_serve", "httpx", "websockets",
        "control_plane.bootstrap", "control_plane.readiness", "control_plane.migrations_runner",
        # Property de-duplication and location upgrade/runtime dependencies.
        "property_dedup", "location_upgrade", "mapbox_geocoding",
        # MapTiler remains a separate visualization provider for satellite/building map layers.
        "maptiler", "mapbox_vector_tile", "shapely", "shapely.geometry",
    ] + PYWIN32,
    runtime_hooks=RUNTIME_HOOKS,
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="roofspan-backend",
    console=True,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="roofspan-backend")
