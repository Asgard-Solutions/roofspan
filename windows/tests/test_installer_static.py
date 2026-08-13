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


def test_python_env_helper_resolves_repo_venv():
    # A single reusable helper resolves the canonical <repo-root>\.venv from $PSScriptRoot (not CWD/PATH).
    helper = os.path.join(PACKAGING, "python_env.ps1")
    assert os.path.isfile(helper)
    env = _read(helper)
    assert 'Join-Path $PSScriptRoot "..\\.."' in env          # repo root relative to the script
    assert 'Join-Path $repo ".venv"' in env
    assert 'Scripts\\python.exe' in env
    assert "Get-RoofSpanBuildPython" in env


def test_build_uses_venv_python_not_path_pyinstaller():
    px = _read(os.path.join(PACKAGING, "build_exes.ps1"))
    # PyInstaller must run through the canonical venv interpreter, NOT a bare PATH command / global install.
    assert "python_env.ps1" in px and "$VenvPython = Get-RoofSpanBuildPython" in px
    assert "& $VenvPython -m PyInstaller" in px
    assert "pyinstaller --clean" not in px                    # no bare PATH pyinstaller invocation
    assert "Get-Command pyinstaller" not in px                # no PATH-based existence gate


def test_bootstrap_installs_backend_and_windows_requirements():
    env = _read(os.path.join(PACKAGING, "python_env.ps1"))
    assert '-m", "venv"' in env or '"-m", "venv"' in env      # creates the venv when missing
    assert "backend\\requirements.txt" in env
    assert "requirements-windows.txt" in env
    assert "& $VenvPython -m pip install -r $backendReq" in env
    assert "& $VenvPython -m pip install -r $winReq" in env


def test_pywin32_and_pyinstaller_validated_via_venv():
    env = _read(os.path.join(PACKAGING, "python_env.ps1"))
    assert '& $VenvPython -c "import PyInstaller"' in env
    assert '& $VenvPython -c "import win32serviceutil"' in env


def test_incomplete_venv_is_repaired_not_failed():
    env = _read(os.path.join(PACKAGING, "python_env.ps1"))
    # An existing-but-incomplete venv is repaired by (re)installing requirements, not by throwing.
    assert "Repairing RoofSpan Windows build virtual environment" in env
    assert "Test-RoofSpanBuildDeps" in env and "Install-RoofSpanBuildDeps" in env


def test_no_manual_venv_activation_required():
    for name in ("python_env.ps1", "build_exes.ps1"):
        txt = _read(os.path.join(PACKAGING, name))
        assert "Activate.ps1" not in txt and "\\activate" not in txt.lower()


def test_stale_exe_protection_preserved_in_build_exes():
    # The pre-existing stale/leftover-exe protection must remain: distpath is cleaned before each spec build.
    px = _read(os.path.join(PACKAGING, "build_exes.ps1"))
    assert "Remove-Item $distRoot -Recurse -Force" in px
    assert "--clean --noconfirm" in px
    assert 'Expected exactly one exe for $spec' in px


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
    # Both shortcuts must EXPLICITLY target the exe, not merely the tools directory (native inspection
    # previously showed TargetPath = ...\tools instead of ...\tools\RoofSpanOffice.exe).
    assert comp.count('Target="[ToolsDir]RoofSpanOffice.exe"') == 2, "both shortcuts must target RoofSpanOffice.exe"
    assert 'Target="[ToolsDir]"' not in comp, "shortcuts must not target only the tools directory"


def test_first_run_launches_desktop_shell_not_browser():
    wxs = _read(os.path.join(INSTALLER, "RoofSpan.wxs"))
    m = re.search(r'<CustomAction Id="LaunchFirstRun".*?/>', wxs, re.S)
    assert m, "LaunchFirstRun custom action not found"
    ca = m.group(0)
    # First-run launches the SAME installed desktop exe as the shortcuts...
    assert 'FileRef="OfficeLauncherExe"' in ca
    # ...and never the old browser-era behaviour.
    assert "http://127.0.0.1:8001" not in ca
    assert "cmd.exe /c start" not in ca
    assert "cmd.exe" not in ca
    # No browser URL launch anywhere in the installer authoring.
    assert "cmd.exe /c start" not in wxs


DESKTOP = os.path.join(HERE, "desktop")
SHELL_PROJ = os.path.join(DESKTOP, "RoofSpanOffice")


def test_python_browser_launcher_removed():
    # The old browser launcher must be fully gone (not left installed alongside the WebView2 shell).
    assert not os.path.exists(os.path.join(PACKAGING, "office_launcher.py"))
    assert not os.path.exists(os.path.join(PACKAGING, "roofspan-office-launcher.spec"))
    from winbuild.targets import TOOL_TARGETS
    assert "RoofSpanOffice" not in TOOL_TARGETS, "RoofSpanOffice must not be a PyInstaller tool target"
    build_exes = _read(os.path.join(PACKAGING, "build_exes.ps1"))
    assert "roofspan-office-launcher.spec" not in build_exes


def test_webview2_shell_project_present_and_configured():
    csproj = _read(os.path.join(SHELL_PROJ, "RoofSpanOffice.csproj"))
    # Real Microsoft Edge WebView2 SDK (not Electron/Tauri/CEF/bundled Chromium).
    assert 'Include="Microsoft.Web.WebView2"' in csproj
    assert "<UseWindowsForms>true</UseWindowsForms>" in csproj
    # Single self-contained exe so WiX packages exactly one file; static loader = no separate loader DLL.
    assert "<PublishSingleFile>true</PublishSingleFile>" in csproj
    assert "<SelfContained>true</SelfContained>" in csproj
    assert "<WebView2LoaderPreference>Static</WebView2LoaderPreference>" in csproj
    assert "RoofSpanOffice.ico" in csproj  # branded exe icon
    assert "<AssemblyName>RoofSpanOffice</AssemblyName>" in csproj  # executable identity preserved


def _shell_sources():
    import glob
    return "\n".join(_read(p) for p in glob.glob(os.path.join(SHELL_PROJ, "*.cs")))


def test_webview2_shell_hosts_local_ui_not_browser():
    src = _shell_sources()
    # Uses a real WebView2 host, navigates to the LOCAL default URL, keeps the ROOFSPAN_OFFICE_URL override,
    # and titles the window "RoofSpan Office". Must NOT launch the system browser to show the app.
    assert "EnsureCoreWebView2Async" in src and "CoreWebView2Environment" in src
    assert "http://127.0.0.1:8001/" in src
    assert "ROOFSPAN_OFFICE_URL" in src
    assert '"RoofSpan Office"' in src
    assert "webbrowser" not in src and "Process.Start(new ProcessStartInfo(AppConfig.BaseUrl" not in src


def test_webview2_shell_backend_readiness_is_bounded_by_overall_deadline():
    src = _shell_sources()
    # Polls the EXISTING health endpoint, but bounded by a REAL overall deadline (not attempt-count x delay):
    # a linked CancellationTokenSource with CancelAfter(overall timeout) plus a short per-probe timeout.
    assert "api/health" in src
    assert "ReadinessOverallTimeoutMs" in src
    assert "CreateLinkedTokenSource" in src
    assert "CancelAfter(AppConfig.ReadinessOverallTimeout)" in src
    assert "CancelAfter(AppConfig.HealthRequestTimeout)" in src
    # No infinite retry loop, and readiness is NOT derived from a fixed attempt count any more.
    assert "while (true)" not in src
    assert "ReadinessMaxAttempts" not in src


def test_webview2_shell_separates_backend_and_display_errors():
    src = _shell_sources()
    # Two DISTINCT customer-facing failure states with their own headline + detail (not one hard-coded
    # backend headline concatenated with every failure).
    assert "ShowBackendError" in src and "ShowDisplayError" in src
    assert "could not connect to the local RoofSpan service." in src
    assert "could not start its desktop display." in src
    assert "Microsoft Edge WebView2 Runtime could not be initialized" in src
    # Backend readiness failure -> backend error; WebView2 init failure -> display error.
    assert "ShowDisplayError();" in src
    # Never leak exception text / stack traces to the customer error UI.
    assert "ex.Message" not in src and "StackTrace" not in src


def test_webview2_shell_external_navigation_and_new_windows():
    src = _shell_sources()
    # Internal 127.0.0.1 origin stays in-app; external links open in the system browser; new-window
    # requests are intercepted (no popup WebView, external not allowed to replace the main window).
    assert "NavigationStarting" in src and "NewWindowRequested" in src
    assert "IsInternal" in src
    assert "UseShellExecute = true" in src
    assert "e.Cancel = true" in src


def test_webview2_shell_per_user_data_and_hardening():
    src = _shell_sources()
    # WebView2 profile is per-user (LOCALAPPDATA\RoofSpan\Office), never Program Files; DevTools + password
    # autosave disabled.
    assert "LocalApplicationData" in src
    assert '"RoofSpan"' in src and '"Office"' in src and '"WebView2"' in src
    assert "SpecialFolder.ProgramFiles" not in src   # never write WebView2 state into Program Files
    assert "AreDevToolsEnabled = false" in src
    assert "IsPasswordAutosaveEnabled = false" in src


def test_webview2_shell_single_instance():
    src = _shell_sources()
    assert "Mutex" in src
    assert "RegisterWindowMessage" in src
    assert "SetForegroundWindow" in src


def test_shell_build_pipeline_dotnet_and_staging():
    bs = _read(os.path.join(DESKTOP, "build_shell.ps1"))
    assert "dotnet publish" in bs and "--self-contained" in bs
    assert "$LASTEXITCODE" in bs                       # fail on non-zero dotnet exit
    assert "LastWriteTimeUtc -lt $buildStart" in bs    # fail closed on a stale exe
    assert 'Copy-Item $exe (Join-Path $ToolsDir "RoofSpanOffice.exe")' in bs
    # stage.ps1 invokes the shell build so a fresh tools\RoofSpanOffice.exe is always produced.
    stage = _read(os.path.join(INSTALLER, "stage.ps1"))
    assert "build_shell.ps1" in stage
    # build.ps1 still fails fast if the shell exe was not staged.
    ps = _read(os.path.join(INSTALLER, "build.ps1"))
    assert "tools\\RoofSpanOffice.exe" in ps
    # A branded Windows icon is committed for the shell exe + shortcuts.
    assert os.path.isfile(os.path.join(INSTALLER, "RoofSpanOffice.ico"))


def test_bundle_chains_webview2_runtime():
    b = _read(os.path.join(INSTALLER, "bundle.wxs"))
    # WebView2 runtime is accounted for by the installer: detected via the EdgeUpdate client GUID at BOTH
    # HKLM (per-machine) and HKCU (per-user) per Microsoft's guidance, treating "0.0.0.0" as not installed;
    # when absent it installs Microsoft's official bootstrapper (embedded so setup stays self-contained).
    assert "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" in b   # WebView2 Runtime client GUID
    assert 'Variable="WebView2RuntimePvHklm"' in b and 'Root="HKLM"' in b
    assert 'Variable="WebView2RuntimePvHkcu"' in b and 'Root="HKCU"' in b
    assert 'Value="pv"' in b                                # read the version value, not mere key existence
    assert "0.0.0.0" in b                                   # 0.0.0.0 treated as not-installed
    assert "InstallCondition=" in b and "DetectCondition=" in b
    assert "$(var.WebView2Bootstrapper)" in b
    # build.ps1 requires + validates + passes the bootstrapper.
    ps = _read(os.path.join(INSTALLER, "build.ps1"))
    assert "WebView2Bootstrapper" in ps
    assert 'Mandatory=$true)][string]$WebView2Bootstrapper' in ps


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
        os.path.join(PACKAGING, "python_env.ps1"),
        os.path.join(HERE, "bafunctions", "build_bafunctions.ps1"),
        os.path.join(HERE, "desktop", "build_shell.ps1"),
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
