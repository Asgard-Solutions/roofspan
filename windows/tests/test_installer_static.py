"""Static validation of the Windows installer build path — runs in-container (no WiX/Windows needed).

Guards against the reported blockers regressing: bundle.wxs must exist, WiX GUIDs must be valid, WiX
service exes must match what the build produces, release filenames must stay consistent, VERSION must be
valid, CloudFront URLs must be correct, and the public download must remain disabled.
"""
import os
import re

import version as ver
from winbuild.targets import SERVICE_EXES, SERVICE_TARGETS
from release import publish

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # windows/
INSTALLER = os.path.join(HERE, "installer")
PACKAGING = os.path.join(HERE, "winbuild")

GUID_RE = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")


def _read(path):
    with open(path) as f:
        return f.read()


def test_bundle_and_installer_files_exist():
    for f in ("RoofSpan.wxs", "bundle.wxs", "constants.wxi", "build.ps1", "stage.ps1"):
        assert os.path.isfile(os.path.join(INSTALLER, f)), f"missing installer/{f}"


def test_wix_guids_are_valid_and_not_placeholder():
    wxi = _read(os.path.join(INSTALLER, "constants.wxi"))
    guids = dict(re.findall(r'define\s+(\w+)\s*=\s*"([^"]+)"', wxi))
    for key in ("RoofSpanUpgradeCode", "BundleUpgradeCode"):
        assert key in guids, f"{key} not defined in constants.wxi"
        assert GUID_RE.match(guids[key]), f"{key} is not a valid GUID: {guids[key]}"
    assert guids["RoofSpanUpgradeCode"] != guids["BundleUpgradeCode"]
    # the old invalid placeholder must be gone everywhere
    for f in ("RoofSpan.wxs", "bundle.wxs", "constants.wxi"):
        assert "RS0FSPAN" not in _read(os.path.join(INSTALLER, f))


# WIX0104: XML comments must not contain "--". Parse every WiX source as XML AND explicitly reject any
# comment body containing "--" (the runtime command-line flags live in attributes, not comments).
_XML_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.S)


def _wix_sources():
    import glob
    return sorted(glob.glob(os.path.join(INSTALLER, "*.wxs")) + glob.glob(os.path.join(INSTALLER, "*.wxi")))


def test_wix_sources_are_well_formed_xml():
    import xml.etree.ElementTree as ET
    for path in _wix_sources():
        try:
            ET.parse(path)
        except ET.ParseError as e:
            raise AssertionError(f"{os.path.basename(path)} is not well-formed XML: {e}")


def test_no_xml_comment_contains_double_hyphen():
    offenders = []
    for path in _wix_sources():
        text = _read(path)
        for m in _XML_COMMENT_RE.finditer(text):
            if "--" in m.group(1):
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{os.path.basename(path)}:{line}")
    assert not offenders, f"XML comment(s) containing '--' (WIX0104): {offenders}"


# WIX0230: a component whose effective KeyPath is a directory (CreateFolder, no other explicit KeyPath)
# CANNOT use Guid="*". Guard so directory-keypath ACL components never regress to an auto GUID.
_COMPONENT_RE = re.compile(r"<Component\b(?P<attrs>[^>]*)>(?P<body>.*?)</Component>", re.S)


def _dir_keypath_components(wxs):
    """Yield (component_id, attrs, guid) for components whose effective KeyPath is a CreateFolder."""
    for m in _COMPONENT_RE.finditer(wxs):
        attrs, body = m.group("attrs"), m.group("body")
        has_createfolder = "<CreateFolder" in body
        has_explicit_keypath = 'KeyPath="yes"' in body  # File/RegistryValue keypath overrides the folder
        if has_createfolder and not has_explicit_keypath:
            cid = re.search(r'Id="([^"]+)"', attrs)
            guid = re.search(r'Guid="([^"]*)"', attrs)
            yield (cid.group(1) if cid else "?", attrs, guid.group(1) if guid else None)


def test_no_directory_keypath_component_uses_wildcard_guid():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    offenders = [cid for cid, _attrs, guid in _dir_keypath_components(wxs) if guid == "*"]
    assert not offenders, f"directory-keypath component(s) using Guid='*' (would trigger WIX0230): {offenders}"


def test_acl_components_have_stable_unique_guids():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    guids = {}
    for cid in ("AclConfig", "AclIdentity", "AclLogs", "AclSecrets"):
        m = re.search(rf'<Component Id="{cid}"[^>]*Guid="([^"]+)"', wxs)
        assert m, f"component {cid} not found"
        g = m.group(1)
        assert g != "*" and GUID_RE.match(g), f"{cid} must have a fixed valid GUID, got {g!r}"
        guids[cid] = g
    assert len(set(guids.values())) == 4, f"ACL component GUIDs must be unique: {guids}"


def test_installer_uses_permanent_upgradecode_and_version_var():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    assert 'UpgradeCode="$(var.RoofSpanUpgradeCode)"' in wxs
    assert 'Version="$(var.Version)"' in wxs
    assert "constants.wxi" in wxs


def test_payload_is_harvested_not_empty_scaffold():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    # WiX v4 <Files> harvesting for the bulk payload, not an empty AppFiles group.
    assert wxs.count("<Files Include=") >= 3
    for tree in ("frontend", "runtime", "config-templates"):
        assert f"$(var.StageDir)\\{tree}\\**" in wxs


def test_service_exes_match_build_outputs():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    referenced = set(re.findall(r"services\\([\w.-]+\.exe)", wxs))
    assert referenced == set(SERVICE_EXES), f"WiX exes {referenced} != build outputs {set(SERVICE_EXES)}"
    # every referenced exe has an entry script + a PyInstaller spec that produces it
    for name, entry in SERVICE_TARGETS.items():
        assert os.path.isfile(os.path.join(PACKAGING, entry)), f"missing entry {entry}"
        spec = os.path.join(PACKAGING, f"{name}.spec")
        assert os.path.isfile(spec), f"missing spec {name}.spec"
        assert f'name="{name}"' in _read(spec)


def test_bundle_chains_postgres_prereq_and_msi():
    b = _read(os.path.join(INSTALLER, "bundle.wxs"))
    assert 'UpgradeCode="$(var.BundleUpgradeCode)"' in b
    assert "<MsiPackage" in b and "$(var.MsiPath)" in b
    assert "<ExePackage" in b and "PostgreSQL" in b
    # Detection is keyed to the DEDICATED RoofSpan-managed service (not any PostgreSQL install).
    assert 'DetectCondition="RoofSpanPgPresent"' in b and 'InstallCondition="NOT RoofSpanPgPresent"' in b
    assert "PostgresInstaller" in b
    # no committed secrets
    assert "superpassword " not in b.lower() or "PgSuperPassword" in b


def test_bafunctions_payload_uses_v5_bal_attribute():
    b = _read(os.path.join(INSTALLER, "bundle.wxs"))
    # WiX v5 Payload attribute is bal:BAFunctions; the v4-era bal:IsBAFunctions is rejected (WIX0004).
    assert 'bal:BAFunctions="yes"' in b
    assert "bal:IsBAFunctions" not in b


def test_pgsuperpassword_variable_is_initially_unset_no_secret():
    b = _read(os.path.join(INSTALLER, "bundle.wxs"))
    m = re.search(r"<Variable\b[^>]*Name=\"PgSuperPassword\"[^>]*/>", b)
    assert m, "PgSuperPassword Variable not found"
    decl = m.group(0)
    # WIX0010: Type without Value is invalid; and no hard-coded/placeholder secret may be committed.
    assert "Type=" not in decl, "PgSuperPassword must not declare Type (would require a Value)"
    assert "Value=" not in decl, "PgSuperPassword must have NO committed Value (BAFunctions seeds it)"
    # security-critical attributes preserved
    for attr in ('Hidden="yes"', 'Persisted="no"', 'bal:Overridable="yes"'):
        assert attr in decl, f"PgSuperPassword lost required attribute {attr}"


def test_build_script_uses_v5_bootstrapper_applications_extension():
    ps = _read(os.path.join(INSTALLER, "build.ps1"))
    # wix.exe v5 extension name for BAL; the old WixToolset.Bal.wixext must not be passed to wix build.
    assert "WixToolset.BootstrapperApplications.wixext" in ps
    assert "WixToolset.Bal.wixext" not in ps


def test_build_script_is_fail_fast_and_builds_bundle():
    ps = _read(os.path.join(INSTALLER, "build.ps1"))
    assert "bundle.wxs" in ps and "RoofSpan.wxs" in ps
    assert ps.count("throw") >= 4  # fail-fast on missing tooling/staging/prereq
    assert "PostgresInstaller" in ps
    assert "RoofSpanSetup.exe" in ps and "RoofSpanOffice-$Version.msi" in ps


def test_release_filenames_consistent():
    assert publish.stable_name() == "RoofSpanSetup.exe"
    assert publish.versioned_name("0.1.0") == "RoofSpanSetup-0.1.0.exe"
    ps = _read(os.path.join(INSTALLER, "build.ps1"))
    assert "RoofSpanSetup-$Version.exe" in ps
    assert "RoofSpanOffice-$Version.msi" in ps


def test_version_is_valid_semver():
    assert ver.is_valid_version(ver.ROOFSPAN_VERSION)
    assert ver.DISPLAY_VERSION == "0.1.0-dev"  # NOT a stable 1.0.0 yet


def test_cloudfront_urls_correct():
    assert publish.stable_url() == "https://downloads.roofspan.io/latest/RoofSpanSetup.exe"
    assert publish.versioned_url("0.1.0") == "https://downloads.roofspan.io/releases/RoofSpanSetup-0.1.0.exe"


def test_update_cadence_is_12h():
    from updater.service import CHECK_INTERVAL_SECONDS
    assert CHECK_INTERVAL_SECONDS == 12 * 60 * 60


def test_public_website_download_reflects_approved_availability():
    # Product decision (approved): the public RoofSpan Office download is ENABLED. This static test
    # tracks that approved state so it can't silently regress the website behavior.
    env = _read(os.path.join(os.path.dirname(HERE), "roofspan-website", ".env"))
    assert "REACT_APP_WINDOWS_INSTALLER_AVAILABLE=true" in env
    assert "downloads.roofspan.io/latest/RoofSpanSetup.exe" in env
