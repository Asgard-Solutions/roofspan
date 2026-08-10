r"""Canonical RoofSpan Office packaging targets — the SINGLE source of the service executable names.

Referenced by the PyInstaller specs, winbuild\build_exes.ps1, installer\RoofSpan.wxs (via the staged
services dir), and validated against the WiX authoring by windows/tests/test_installer_static.py so a
WiX-referenced exe can never drift from what the build actually produces.
"""

# name -> PyInstaller entry script (in windows/packaging/)
SERVICE_TARGETS = {
    "roofspan-backend": "backend_entry.py",
    "roofspan-relay-connector": "relay_entry.py",
    "roofspan-update-service": "update_service_entry.py",
}

# Produced executables (Windows).
SERVICE_EXES = [f"{name}.exe" for name in SERVICE_TARGETS]

# Windows service names authored in RoofSpan.wxs (for cross-checks / docs).
WINDOWS_SERVICES = ["RoofSpanBackend", "RoofSpanRelayConnector", "RoofSpanUpdateService"]
