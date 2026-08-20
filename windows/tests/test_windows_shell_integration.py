from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "windows" / "installer"
SHELL = ROOT / "windows" / "shell"


def _read_installer(name: str) -> str:
    return (INSTALLER / name).read_text(encoding="utf-8")


def test_stage_generates_icon_and_native_shell():
    stage = _read_installer("stage.ps1")
    assert 'public\\brand\\roofspan-appicon.png' in stage
    assert 'RoofSpan.ico' in stage
    assert 'System.Drawing' in stage
    assert 'Failed to generate RoofSpan.ico' in stage
    assert 'RoofSpanOfficeShell.csproj' in stage
    assert 'dotnet publish' in stage
    assert '--self-contained true' in stage
    assert 'RoofSpanOffice.exe' in stage


def test_native_shell_project_uses_webview2_and_local_app_origin():
    project = (SHELL / "RoofSpanOfficeShell.csproj").read_text(encoding="utf-8")
    program = (SHELL / "Program.cs").read_text(encoding="utf-8")
    assert 'Microsoft.Web.WebView2' in project
    assert '<OutputType>WinExe</OutputType>' in project
    assert '<SelfContained>true</SelfContained>' in project
    assert 'http://127.0.0.1:8001/' in program
    assert 'new() { Dock = DockStyle.Fill }' in program
    assert 'WaitForBackendAsync' in program
    assert 'uri.Host == "127.0.0.1" && uri.Port == 8001' in program
    assert 'UseShellExecute = true' in program  # external links only


def test_msi_shortcuts_and_first_run_target_native_shell_not_browser():
    wxs = _read_installer("RoofSpan.wxs")
    assert '<Icon Id="RoofSpanIcon"' in wxs
    assert '<Property Id="ARPPRODUCTICON" Value="RoofSpanIcon" />' in wxs
    assert 'Id="ShellExe"' in wxs
    assert 'Source="$(var.StageDir)\\shell\\RoofSpanOffice.exe"' in wxs
    assert 'Id="RoofSpanDesktopShortcut"' in wxs
    assert 'Directory="DesktopFolder"' in wxs
    assert 'Id="RoofSpanStartMenuShortcut"' in wxs
    assert 'Directory="ProgramMenuFolder"' in wxs
    assert wxs.count('Target="[#ShellExe]"') == 2
    assert '<ComponentGroupRef Id="ShellFiles" />' in wxs
    assert '<ComponentRef Id="ShellLauncher" />' in wxs
    assert 'explorer.exe' not in wxs
    assert 'Arguments="http://127.0.0.1:8001/"' not in wxs
    assert 'start &quot;&quot; &quot;[#ShellExe]&quot;' in wxs


def test_build_refuses_stage_without_native_shell():
    build = _read_installer("build.ps1")
    assert 'shell\\RoofSpanOffice.exe' in build
