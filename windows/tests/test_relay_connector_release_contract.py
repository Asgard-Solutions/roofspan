"""Static release guards for the hosted Relay connector upgrade contract.

These tests are intentionally Linux-runnable. The Windows workflow separately freezes and executes the
real PyInstaller binary; this suite prevents the source/spec/build gates from drifting apart first.
"""
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]
WIN = REPO / "windows"
WINBUILD = WIN / "winbuild"
INSTALLER = WIN / "installer"
BACKEND = REPO / "backend"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_version_is_newer_than_the_stale_connector_build():
    version = (WIN / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert tuple(map(int, version.split("."))) >= (0, 4, 5)


def test_relay_entry_exposes_machine_readable_hosted_identity_contract():
    source = _text(WINBUILD / "relay_entry.py")
    for token in (
        "--build-info",
        "hosted-installation-identity-v2",
        "/api/relay/connector/identity",
        "/api/relay/installation",
        "ROOFSPAN_BUILD_SHA",
        "ROOFSPAN_VERSION",
    ):
        assert token in source
    assert "private_key, installation_id = get_or_create_identity" not in source


def test_relay_pyinstaller_spec_embeds_the_build_identity_hook():
    spec = _text(WINBUILD / "roofspan-relay-connector.spec")
    assert "ROOFSPAN_BUILD_INFO_HOOK" in spec
    assert "runtime_hooks=RUNTIME_HOOKS" in spec


def test_service_build_fails_on_stale_relay_binary_before_staging():
    script = _text(WINBUILD / "build_exes.ps1")
    for token in (
        "Assert-RelayConnectorBuildInfo",
        "--build-info",
        "hosted-installation-identity-v2",
        "/api/relay/connector/identity",
        "/api/relay/installation",
        "ROOFSPAN_BUILD_SHA",
        "ROOFSPAN_VERSION",
    ):
        assert token in script
    # Validate both the freshly frozen output and the copied stage output.
    assert script.count("Assert-RelayConnectorBuildInfo") >= 3


def test_installer_refuses_old_stage_or_manual_version_drift():
    script = _text(INSTALLER / "build.ps1")
    for token in (
        "Assert-RelayConnectorBuildInfo",
        "--build-info",
        "windows\\VERSION",
        "hosted-installation-identity-v2",
        "Remove _stage and run stage.ps1 again",
    ):
        assert token in script
    assert "version overrides are not allowed" in script


def test_packaged_backend_declares_vector_tile_runtime_dependencies():
    requirements = set(_text(BACKEND / "requirements.txt").splitlines())
    # maptiler.py imports all three at runtime. Keep the mapbox-vector-tile release on the protobuf-5
    # line used by RoofSpan; v2.2 requires protobuf 6 and would conflict with the pinned backend stack.
    assert "mapbox-vector-tile==2.1.0" in requirements
    assert "pyclipper==1.3.0.post6" in requirements
    assert "shapely==2.1.2" in requirements
    assert "protobuf==5.29.6" in requirements


def test_hosted_relay_has_bounded_legacy_connector_compatibility():
    source = _text(BACKEND / "relay" / "server.py")
    assert '@router.websocket("/tunnel")' in source
    assert "_canonical_ed25519_public_pem" in source
    assert "LEGACY_PUBLIC_KEY_MAX_CHARS" in source
    assert "isinstance(key, Ed25519PublicKey)" in source
    assert "Installation.public_key_pem == canonical_pem" in source
    assert "installation_id=claimed_installation_id" in source
    assert "InstallationConn(installation_id, ws)" in source


def test_live_hosted_probe_routes_current_and_legacy_connectors():
    probe = _text(BACKEND / "tests" / "hosted_pairing_probe.py")
    assert 'installation_route="/api/relay/tunnel"' in probe
    assert "installation_claim=public_pem" in probe
    assert 'assert ready["installation_id"] == installation_id' in probe
