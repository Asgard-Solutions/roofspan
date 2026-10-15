"""Static contract: services never start inside a coordinated upgrade MSI; Burn routes upgrades via the coordinator."""
import re
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "installer"
MSI = (INSTALLER / "RoofSpan.wxs").read_text(encoding="utf-8")
BUNDLE = (INSTALLER / "bundle.wxs").read_text(encoding="utf-8")


def test_service_start_is_conditional_on_not_coordinated():
    starts = re.findall(r"<ServiceControl[^>]*Start=\"install\"[^>]*/>", MSI)
    assert len(starts) == 3
    block = MSI[MSI.index('<Component Id="Svc_StartOnInstall"'):MSI.index("</Component>", MSI.index('<Component Id="Svc_StartOnInstall"'))]
    assert 'Condition="NOT ROOFSPAN_COORDINATED"' in block and all(s in block for s in starts)
    assert 'Condition="NOT Installed AND NOT ROOFSPAN_COORDINATED"' in MSI


def test_bundle_routes_fresh_installs_to_msi_and_upgrades_to_coordinator():
    assert 'InstallCondition="NOT RoofSpanOfficeInstalledVersion OR RoofSpanOfficeInstalledVersion = v0.0.0.0 OR RoofSpanOfficeInstalledVersion = WixBundleVersion"' in BUNDLE
    coord = BUNDLE[BUNDLE.index('<ExePackage Id="RoofSpanUpgradeCoordinator"'):BUNDLE.index("</ExePackage>", BUNDLE.index('<ExePackage Id="RoofSpanUpgradeCoordinator"'))]
    assert 'Vital="yes"' in coord and 'SourceFile="$(var.UpgradeExe)"' in coord
    assert 'InstallCondition="RoofSpanOfficeInstalledVersion AND RoofSpanOfficeInstalledVersion &gt; v0.0.0.0 AND RoofSpanOfficeInstalledVersion &lt; WixBundleVersion"' in coord
    assert 'run --msi' in coord and '[PREVIOUSMSI]' in coord and 'UninstallArguments="uninstall"' in coord
    assert BUNDLE.index('Id="PostgreSQLVerify"') < BUNDLE.index('Id="RoofSpanUpgradeCoordinator"')
    assert '<Variable Name="PREVIOUSMSI"' in BUNDLE
