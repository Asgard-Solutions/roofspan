from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "windows" / "installer"


def _read(name: str) -> str:
    return (INSTALLER / name).read_text(encoding="utf-8")


def test_stage_generates_canonical_roofspan_icon():
    stage = _read("stage.ps1")
    assert 'public\\brand\\roofspan-appicon.png' in stage
    assert 'RoofSpan.ico' in stage
    assert 'System.Drawing' in stage
    assert 'Failed to generate RoofSpan.ico' in stage


def test_msi_owns_desktop_start_menu_and_installed_apps_icon():
    wxs = _read("RoofSpan.wxs")
    assert '<Icon Id="RoofSpanIcon"' in wxs
    assert '<Property Id="ARPPRODUCTICON" Value="RoofSpanIcon" />' in wxs
    assert 'Id="RoofSpanDesktopShortcut"' in wxs
    assert 'Directory="DesktopFolder"' in wxs
    assert 'Id="RoofSpanStartMenuShortcut"' in wxs
    assert 'Directory="ProgramMenuFolder"' in wxs
    assert wxs.count('Name="RoofSpan Office"') >= 2
    assert wxs.count('Icon="RoofSpanIcon"') >= 2
    assert 'Target="[WindowsFolder]explorer.exe"' in wxs
    assert 'Arguments="http://127.0.0.1:8001/"' in wxs
    assert '<ComponentRef Id="ShellShortcuts" />' in wxs
