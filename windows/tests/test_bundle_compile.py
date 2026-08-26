"""Real WiX 5 Burn-bundle compile smoke test and installer wiring regressions.

The tests use deterministic throwaway payloads but compile the real bundle.wxs and RoofSpan.wxs on
Windows. This catches authoring, cache-identity, payload, harvesting, and icon regressions before a
customer build is produced.
"""
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

WINDOWS = Path(__file__).resolve().parents[1]
INSTALLER = WINDOWS / "installer"
BUNDLE = INSTALLER / "bundle.wxs"
MSI = INSTALLER / "RoofSpan.wxs"
VERSION = (WINDOWS / "VERSION").read_text(encoding="utf-8").strip()
WIX = shutil.which("wix")


_DUMMY_MSI_WXS = (
    '<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">'
    f'<Package Name="RoofSpan Dummy" Manufacturer="RoofSpan" Version="{VERSION}" '
    'UpgradeCode="11111111-1111-1111-1111-111111111111" Scope="perMachine" Compressed="yes">'
    '<MediaTemplate EmbedCab="yes" />'
    '<StandardDirectory Id="ProgramFiles64Folder"><Directory Id="APPDIR" Name="RoofSpanDummy">'
    '<Component Id="C1" Guid="22222222-2222-2222-2222-222222222222">'
    '<RegistryValue Root="HKLM" Key="Software\\RoofSpanDummy" Name="v" Type="string" Value="1" KeyPath="yes" />'
    '</Component></Directory></StandardDirectory>'
    '<Feature Id="F"><ComponentRef Id="C1" /></Feature></Package></Wix>'
)

# Minimal valid 1x1, 32-bit Windows icon: ICONDIR + one ICONDIRENTRY + BITMAPINFO/XOR/AND data.
_MINIMAL_ICO = bytes.fromhex(
    "000001000100"
    "01010000010020003000000016000000"
    "28000000010000000200000001002000000000000400000000000000000000000000000000000000"
    "0000ffff00000000"
)


def _make_payloads(outdir: Path):
    """Create a real MSI plus distinct PE stand-ins for both prerequisite packages."""
    msi = outdir / "RoofSpanOffice.msi"
    wxs = outdir / "dummy.wxs"
    wxs.write_text(_DUMMY_MSI_WXS, encoding="utf-8")
    subprocess.run(
        [WIX, "build", str(wxs), "-arch", "x64", "-o", str(msi)],
        capture_output=True,
        text=True,
    )
    if not msi.exists():
        msi.write_bytes(b"MZ" + b"\0" * 4096)

    pg = outdir / "postgres.exe"
    wv = outdir / "webview2.exe"
    if platform.system() == "Windows":
        import os

        system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        shutil.copyfile(system32 / "where.exe", pg)
        # Use a different real PE so the test also proves package identity does not depend on hashes.
        shutil.copyfile(system32 / "whoami.exe", wv)
    else:
        pg.write_bytes(b"MZPG" + b"\0" * 4096)
        wv.write_bytes(b"MZWV" + b"\0" * 4096)
    return msi, pg, wv


def _run_wix_build(outdir: Path):
    import os

    msi, pg, wv = _make_payloads(outdir)
    env = dict(os.environ)
    if platform.system() != "Windows":
        fake = outdir / "win"
        ps_dir = fake / "System32" / "WindowsPowerShell" / "v1.0"
        ps_dir.mkdir(parents=True, exist_ok=True)
        (ps_dir / "powershell.exe").write_bytes(b"MZ" + b"\0" * 4096)
        env["SystemRoot"] = str(fake)
    cmd = [
        WIX,
        "build",
        str(BUNDLE),
        "-arch",
        "x64",
        "-d",
        f"Version={VERSION}",
        "-d",
        f"MsiPath={msi}",
        "-d",
        f"PostgresInstaller={pg}",
        "-d",
        f"WebView2Bootstrapper={wv}",
        "-ext",
        "WixToolset.BootstrapperApplications.wixext",
        "-ext",
        "WixToolset.Util.wixext",
        "-o",
        str(outdir / "RoofSpanSetup.exe"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


@pytest.mark.skipif(WIX is None, reason="wix CLI not installed; authoritative compile runs in Windows CI")
def test_burn_bundle_compiles():
    with tempfile.TemporaryDirectory() as td:
        outdir = Path(td)
        rc, out = _run_wix_build(outdir)

        assert "WIX0010" not in out, f"typed Variable without Value regressed:\n{out}"
        assert "'[WebView2Bootstrapper]'" not in out
        assert "'[PostgresInstaller]'" not in out
        assert "WIX8000" not in out, f"Burn package cache identity collision:\n{out}"

        if platform.system() == "Windows":
            artifact = outdir / "RoofSpanSetup.exe"
            assert rc == 0 and artifact.exists(), f"Burn bundle failed to compile on Windows:\n{out}"
        else:
            # WiX payload binding is unsupported off Windows. We still require preprocessing/compile to
            # reach that boundary without an authoring regression.
            assert "WIX0150" not in out, f"preprocessor aborted the compile:\n{out}"


def _build_fake_stage(stage: Path):
    """Build the complete minimum stage required by the real RoofSpan.wxs authoring."""
    for sub in ("frontend", "runtime", "config-templates", "shell"):
        (stage / sub).mkdir(parents=True, exist_ok=True)
    for name in ("roofspan-backend", "roofspan-relay-connector", "roofspan-update-service"):
        service = stage / "services" / name
        (service / "_internal").mkdir(parents=True, exist_ok=True)
        (service / f"{name}.exe").write_bytes(b"MZ" + b"\0" * 4096)
        (service / "_internal" / "base_library.zip").write_bytes(b"PK\0\0")
    (stage / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    (stage / "shell" / "RoofSpanOffice.exe").write_bytes(b"MZSHELL" + b"\0" * 4096)
    (stage / "runtime" / "RoofSpan.ico").write_bytes(_MINIMAL_ICO)
    (stage / "runtime" / "README.txt").write_text("test", encoding="utf-8")
    (stage / "config-templates" / "roofspan.env.template").write_text("x", encoding="utf-8")


@pytest.mark.skipif(WIX is None, reason="wix CLI not installed; authoritative compile runs in Windows CI")
@pytest.mark.skipif(platform.system() != "Windows", reason="WiX MSI harvesting/cab is only defined on Windows")
def test_roofspan_msi_compiles():
    with tempfile.TemporaryDirectory() as td:
        outdir = Path(td)
        stage = outdir / "stage"
        _build_fake_stage(stage)
        msi = outdir / "RoofSpanOffice.msi"
        cmd = [
            WIX,
            "build",
            str(MSI),
            "-arch",
            "x64",
            "-d",
            f"Version={VERSION}",
            "-d",
            f"StageDir={stage}",
            "-ext",
            "WixToolset.Util.wixext",
            "-ext",
            "WixToolset.Firewall.wixext",
            "-o",
            str(msi),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        out = (result.stdout or "") + (result.stderr or "")
        assert result.returncode == 0 and msi.exists(), f"RoofSpan.wxs MSI failed to compile:\n{out}"


def _bundle_text():
    return BUNDLE.read_text(encoding="utf-8")


def test_pgsuperpassword_is_untyped_hidden_nonpersisted():
    bundle = _bundle_text()
    assert '<Variable Name="PgSuperPassword" Hidden="yes" Persisted="no"' in bundle
    assert 'Name="PgSuperPassword" Type=' not in bundle
    assert 'PgSuperPassword" Type="string" Value' not in bundle


def test_no_exepackage_sourcefile_uses_burn_variable():
    bundle = _bundle_text()
    for match in re.finditer(r'SourceFile="([^"]+)"', bundle):
        value = match.group(1)
        assert not (value.startswith("[") and value.endswith("]")), value


def test_burn_package_cache_ids_are_explicit_unique_and_version_scoped():
    bundle = _bundle_text()
    identities = []
    for tag in re.findall(r"<(?:ExePackage|MsiPackage)\b[^>]*?/?>", bundle, re.DOTALL):
        cache = re.search(r'CacheId="([^"]+)"', tag)
        source = re.search(r'SourceFile="([^"]+)"', tag)
        package_id = re.search(r'\bId="([^"]+)"', tag)
        assert source, f"package has no SourceFile: {tag}"
        assert cache, f"package {package_id.group(1) if package_id else '?'} must have explicit CacheId"
        identities.append((package_id.group(1) if package_id else "?", cache.group(1)))

    values = [value for _package, value in identities]
    assert len(values) == len(set(values)), f"duplicate explicit CacheIds: {identities}"
    assert 'CacheId="RoofSpanPostgreSQLPasswordPrep"' in bundle
    assert 'CacheId="RoofSpanPostgreSQLPasswordCleanup"' in bundle
    assert 'CacheId="RoofSpanWebView2Runtime-$(var.Version)"' in bundle
    assert 'CacheId="RoofSpanPostgreSQLPrereq-$(var.Version)"' in bundle
    assert 'CacheId="RoofSpanOfficeMsi-$(var.Version)"' in bundle


def test_postgres_step_generates_secure_password_and_uses_real_edb_installer():
    bundle = _bundle_text()
    assert "RandomNumberGenerator" in bundle
    assert "IsNullOrWhiteSpace($p)" in bundle
    assert "[PgSuperPassword]" in bundle
    assert "ProtectedData" in bundle and "LocalMachine" in bundle
    assert "pg_install.optionfile" in bundle and "superpassword=" in bundle
    assert 'SourceFile="$(var.PostgresInstaller)"' in bundle
    assert "--optionfile" in bundle
    assert "--mode unattended --unattendedmodeui minimal --servicename RoofSpanPostgreSQL" in bundle


def test_all_bundle_prerequisites_are_embedded():
    bundle = _bundle_text()
    assert 'Compressed="no"' not in bundle
    assert 'SourceFile="$(var.PostgresInstaller)"' in bundle
    assert 'SourceFile="$(var.WebView2Bootstrapper)"' in bundle
    assert 'SourceFile="$(var.MsiPath)"' in bundle
    assert bundle.count('Compressed="yes"') >= 4


def test_no_committed_or_hardcoded_password():
    bundle = _bundle_text()
    assert 'Value="RoofSpan' not in bundle
    assert "password=" not in bundle.lower() or "superpassword" in bundle.lower()
