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
    "roofspan-update-broker": "update_broker_entry.py",
}

# Produced executables (Windows).
SERVICE_EXES = [f"{name}.exe" for name in SERVICE_TARGETS]

# Windows service names authored in RoofSpan.wxs (for cross-checks / docs).
WINDOWS_SERVICES = ["RoofSpanBackend", "RoofSpanRelayConnector", "RoofSpanUpdateService", "RoofSpanUpdateBroker"]

# Written by build_exes.ps1 next to the staged services; build.ps1 and Test-InstallerArtifact.ps1 verify
# that the staged and the MSI-packaged executables are byte-identical to what that build produced.
SERVICES_BUILD_MANIFEST = "services-build-manifest.json"
