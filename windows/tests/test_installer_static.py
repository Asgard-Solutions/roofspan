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


_SERVICEINSTALL_RE = re.compile(r"<ServiceInstall\b([^>]*)>", re.S)
_PERMEX_RE = re.compile(r'<util:PermissionEx\s+User="([^"]+)"\s+Domain="NT SERVICE"')


def _services(wxs):
    """Return {service_name: nt_service_account_name} for each ServiceInstall."""
    out = {}
    for attrs in _SERVICEINSTALL_RE.findall(wxs):
        name = re.search(r'Name="([^"]+)"', attrs)
        acct = re.search(r'Account="NT SERVICE\\([^"]+)"', attrs)
        if name:
            out[name.group(1)] = acct.group(1) if acct else None
    return out


def test_service_virtual_accounts_match_service_names():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    svcs = _services(wxs)
    assert svcs, "no ServiceInstall elements found"
    mismatches = {n: a for n, a in svcs.items() if a is not None and a != n}
    assert not mismatches, f"NT SERVICE virtual account must equal the service Name; mismatches: {mismatches}"
    # the three known RoofSpan services must all be present and self-consistent
    for expected in ("RoofSpanBackend", "RoofSpanRelayConnector", "RoofSpanUpdateService"):
        assert svcs.get(expected) == expected, f"{expected} account/name mismatch: {svcs.get(expected)!r}"


def test_acl_identities_use_canonical_service_names():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    canonical = set(_services(wxs))  # canonical service names
    users = set(_PERMEX_RE.findall(wxs))
    unknown = users - canonical
    assert not unknown, f"ACL PermissionEx identities not matching a service Name: {unknown}"
    # legacy identities must be gone (exact-match check, not substring of the corrected names)
    for legacy in ("RoofSpanRelay", "RoofSpanUpdate"):
        assert legacy not in users, f"legacy ACL identity still present: NT SERVICE\\{legacy}"


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
    # ExePackage/@SourceFile is resolved at BUILD TIME -> must use $(var.PostgresInstaller), not the Burn
    # runtime form [PostgresInstaller] (WIX0103). No SourceFile may use Burn runtime [Variable] syntax.
    assert 'SourceFile="$(var.PostgresInstaller)"' in b
    assert 'SourceFile="[PostgresInstaller]"' not in b
    assert not re.search(r'SourceFile="\[[^"]*\]"', b), "SourceFile must not use Burn runtime [Variable] syntax"
    # PostgreSQL prerequisite must be EMBEDDED (Compressed="yes") so RoofSpanSetup.exe is self-contained;
    # Compressed="no" would make it an external payload the customer must place next to the setup exe.
    assert re.search(r'<ExePackage\b[^>]*Compressed="yes"', b, re.S), "PostgreSQL ExePackage must be embedded (Compressed=\"yes\")"
    assert 'Compressed="no"' not in b, "no bundle payload may be external (Compressed=\"no\")"
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


def test_build_script_resolves_bal_extension_dll_dynamically():
    ps = _read(os.path.join(INSTALLER, "build.ps1"))
    # Resolve the actual BAL DLL from the local WiX cache and pass its PATH to -ext (robust to the
    # v4/v5 package-id + folder/DLL name mismatch that causes WIX0144 on real installs).
    assert "WixToolset.BootstrapperApplications.wixext.dll" in ps
    assert 'Join-Path $base ".wix\\extensions"' in ps
    assert "Resolve-BalExtension" in ps
    assert '-ext "$balExt"' in ps
    # Both known package ids may be attempted as a fallback for `wix extension add`.
    assert "WixToolset.BootstrapperApplications.wixext/5.0.2" in ps


def test_build_script_does_not_hardcode_user_path():
    ps = _read(os.path.join(INSTALLER, "build.ps1"))
    # No hard-coded Windows username or absolute user profile path (must use env/$HOME).
    assert "C:\\Users\\" not in ps
    assert "army_" not in ps
    # The extension cache root is derived from environment, not literals.
    assert "$env:USERPROFILE" in ps


def test_build_script_checks_exit_code_and_fresh_output():
    ps = _read(os.path.join(INSTALLER, "build.ps1"))
    # Root cause of the false-success: wix.exe is native, so a non-zero exit does not throw. The script
    # must check $LASTEXITCODE and confirm the artifact was freshly (re)produced after the build started.
    assert "$LASTEXITCODE" in ps
    assert "Assert-FreshBuild" in ps
    assert "LastWriteTimeUtc" in ps
    assert "$buildStart" in ps


def test_build_script_clears_stale_outputs_before_building():
    ps = _read(os.path.join(INSTALLER, "build.ps1"))
    # Target outputs are deleted before building so a stale artifact from a previous successful build can
    # never be mistaken for a fresh success (reported: stale RoofSpanSetup-0.1.0.exe masking a failure).
    assert "Remove-Item -LiteralPath $out -Force" in ps
    # deletion happens before the wix build invocations
    del_at = ps.index("Remove-Item -LiteralPath $out -Force")
    build_at = ps.index("wix build .\\RoofSpan.wxs")
    assert del_at < build_at


def test_build_script_is_fail_fast_and_builds_bundle():
    ps = _read(os.path.join(INSTALLER, "build.ps1"))
    assert "bundle.wxs" in ps and "RoofSpan.wxs" in ps
    assert ps.count("throw") >= 4  # fail-fast on missing tooling/staging/prereq
    assert "PostgresInstaller" in ps
    assert "RoofSpanSetup.exe" in ps and "RoofSpanOffice-$Version.msi" in ps


def test_desktop_and_start_menu_shortcuts_launch_office():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    # A Desktop directory must exist for the desktop icon.
    assert '<StandardDirectory Id="DesktopFolder"' in wxs
    # The launcher component packages RoofSpanOffice.exe and defines BOTH a Desktop and a Start Menu
    # shortcut named "RoofSpan Office" (the Start Menu entry is what makes it appear in Windows Search).
    m = re.search(r'<Component Id="App_Launcher".*?</Component>', wxs, re.S)
    assert m, "App_Launcher component (Desktop/Start-Menu launcher) not found"
    comp = m.group(0)
    assert 'tools\\RoofSpanOffice.exe' in comp, "launcher must package tools\\RoofSpanOffice.exe"
    assert 'Directory="DesktopFolder"' in comp and 'Name="RoofSpan Office"' in comp, "missing desktop shortcut"
    assert 'Directory="StartMenuRoofSpan"' in comp, "missing Start Menu shortcut"
    assert comp.count('Name="RoofSpan Office"') >= 2, "both shortcuts should be named 'RoofSpan Office'"


def test_office_launcher_is_built_and_packaged():
    # Launcher entry script + spec exist and are wired into the build.
    assert os.path.isfile(os.path.join(PACKAGING, "office_launcher.py"))
    assert os.path.isfile(os.path.join(PACKAGING, "roofspan-office-launcher.spec"))
    from winbuild.targets import TOOL_TARGETS
    assert TOOL_TARGETS.get("RoofSpanOffice") == "office_launcher.py"
    # The build script builds the launcher spec into the staged tools dir.
    build_exes = _read(os.path.join(PACKAGING, "build_exes.ps1"))
    assert "roofspan-office-launcher.spec" in build_exes
    # A branded Windows icon is committed for the launcher exe + shortcuts.
    assert os.path.isfile(os.path.join(INSTALLER, "RoofSpanOffice.ico"))
    # build.ps1 fails fast if the launcher wasn't staged.
    ps = _read(os.path.join(INSTALLER, "build.ps1"))
    assert "tools\\RoofSpanOffice.exe" in ps


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



def test_powershell_build_scripts_are_ascii_only():
    # Windows PowerShell 5.1 reads a BOM-less .ps1 as the system ANSI codepage; non-ASCII chars (e.g. an
    # em-dash in a throw string) then mangle or break parsing. Keep every build script pure ASCII so it
    # runs identically under Windows PowerShell 5.1 and PowerShell 7 with no manual encoding workaround.
    scripts = [
        os.path.join(INSTALLER, "stage.ps1"),
        os.path.join(INSTALLER, "build.ps1"),
        os.path.join(PACKAGING, "build_exes.ps1"),
        os.path.join(HERE, "bafunctions", "build_bafunctions.ps1"),
    ]
    for s in scripts:
        raw = open(s, "rb").read()
        bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        assert not bad, f"{os.path.basename(s)} has non-ASCII byte(s) at {bad[:5]}"


def test_stage_script_resolves_stagedir_absolute_before_pushlocation():
    # A relative -StageDir must not break the frontend copy: step 2 runs inside Push-Location (CWD changes
    # to the frontend dir), so StageDir/derived paths must be resolved to ABSOLUTE first.
    ps = _read(os.path.join(INSTALLER, "stage.ps1"))
    assert "(Resolve-Path -LiteralPath $StageDir).Path" in ps
    # StageDir must be made absolute BEFORE it is used to build the sub-dirs and BEFORE Push-Location.
    resolve_at = ps.index("(Resolve-Path -LiteralPath $StageDir).Path")
    services_at = ps.index('$services = Join-Path $StageDir "services"')
    push_at = ps.index("Push-Location $FrontendDir")
    assert resolve_at < services_at < push_at
    # FrontendDir is also resolved to absolute (honors an absolute override; anchors a relative default).
    assert "[System.IO.Path]::IsPathRooted($FrontendDir)" in ps
    assert "(Resolve-Path -LiteralPath $FrontendDir).Path" in ps
