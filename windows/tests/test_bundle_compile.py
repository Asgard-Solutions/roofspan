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


def _run_wix_build(outdir: Path, cwd: Path | None = None):
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
        f"WebView2StandaloneInstaller={wv}",
        "-ext",
        "WixToolset.BootstrapperApplications.wixext",
        "-ext",
        "WixToolset.Util.wixext",
        "-o",
        str(outdir / "RoofSpanSetup.exe"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(cwd) if cwd else None)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


@pytest.mark.skipif(WIX is None, reason="wix CLI not installed; authoritative compile runs in Windows CI")
def test_burn_bundle_compiles():
    with tempfile.TemporaryDirectory() as td:
        outdir = Path(td)
        rc, out = _run_wix_build(outdir)

        assert "WIX0010" not in out, f"typed Variable without Value regressed:\n{out}"
        assert "'[WebView2StandaloneInstaller]'" not in out
        assert "'[PostgresInstaller]'" not in out
        assert "WIX8000" not in out, f"Burn package cache identity collision:\n{out}"

        if platform.system() == "Windows":
            artifact = outdir / "RoofSpanSetup.exe"
            assert rc == 0 and artifact.exists(), f"Burn bundle failed to compile on Windows:\n{out}"
        else:
            # WiX payload binding is unsupported off Windows. We still require preprocessing/compile to
            # reach that boundary without an authoring regression.
            assert "WIX0150" not in out, f"preprocessor aborted the compile:\n{out}"


@pytest.mark.skipif(WIX is None, reason="wix CLI not installed; authoritative compile runs in Windows CI")
def test_bundle_compiles_from_repo_root_and_installer_dir():
    """The script payloads are anchored to the bundle's own directory ($(sys.SOURCEFILEDIR)), so the
    bundle must resolve them and compile identically whether invoked from the repo root or installer\\.
    The previous relative 'scripts\\...' payload path caused WIX0103 (file not found) from the repo root."""
    repo_root = WINDOWS.parent
    for cwd in (repo_root, INSTALLER):
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            _rc, out = _run_wix_build(outdir, cwd=cwd)
            assert "WIX0103" not in out, f"payload file not found when building from {cwd}:\n{out}"
            assert "WIX0150" not in out, f"preprocessor aborted from {cwd}:\n{out}"
            if platform.system() == "Windows":
                assert (outdir / "RoofSpanSetup.exe").exists(), f"bundle did not build from {cwd}:\n{out}"


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


def _prep_script_text():
    return (INSTALLER / "scripts" / "Prepare-PostgreSQL.ps1").read_text(encoding="utf-8")


def _prep_install_arguments():
    """The InstallArguments string of the PostgreSQLPasswordPrep ExePackage (Burn-formatted at runtime)."""
    bundle = _bundle_text()
    tag = re.search(r'<ExePackage\b[^>]*\bId="PostgreSQLPasswordPrep".*?</ExePackage>', bundle, re.DOTALL)
    assert tag, "PostgreSQLPasswordPrep ExePackage not found"
    args = re.search(r'InstallArguments="([^"]*)"', tag.group(0))
    assert args, "PostgreSQLPasswordPrep has no InstallArguments"
    return args.group(1)


def test_postgres_step_generates_secure_password_and_uses_real_edb_installer():
    # The password logic now lives in the checked-in, bundle-embedded PowerShell PAYLOAD, not inline.
    script = _prep_script_text()
    assert "RandomNumberGenerator" in script
    assert "IsNullOrWhiteSpace($pw)" in script
    assert "ProtectedData" in script and "LocalMachine" in script
    assert "pg_install.optionfile" in script and "superpassword=" in script
    # The bundle carries the script as an embedded, directory-anchored payload with an explicit Name and
    # still runs the REAL EDB installer.
    bundle = _bundle_text()
    assert 'SourceFile="$(sys.SOURCEFILEDIR)scripts\\Prepare-PostgreSQL.ps1"' in bundle
    assert 'Name="Prepare-PostgreSQL.ps1"' in bundle
    assert '-File Prepare-PostgreSQL.ps1' in bundle
    assert 'SourceFile="$(var.PostgresInstaller)"' in bundle
    assert "--optionfile" in bundle
    assert "--mode unattended --unattendedmodeui minimal --servicename RoofSpanPostgreSQL" in bundle


def test_prep_script_handles_postgres_states_and_preserves_existing_secret():
    """The prep step must validate ownership, refuse to touch other services, and never overwrite an
    existing stored superuser password."""
    script = _prep_script_text()
    # RoofSpan-managed detection uses BOTH the service and the DPAPI credential.
    assert "RoofSpanPostgreSQL" in script
    assert "pg_super.bin" in script
    # Port 5432 conflict handling that does NOT modify another service.
    assert "5432" in script
    assert "Get-NetTCPConnection" in script
    # Actionable stop path (non-zero exit) rather than damaging existing data.
    assert "ROOFSPAN-PREREQ-ERROR" in script and "exit 1" in script
    # The existing secret is only written on the clean branch: the DPAPI write must be guarded by a
    # prior "secret present" check so an existing password is never overwritten.
    assert "$secretPresent = Test-Path $pgSuperBin" in script
    assert script.index("$secretPresent = Test-Path $pgSuperBin") < script.index("WriteAllBytes($pgSuperBin")
    # Transient plaintext option file is cleaned up on handled failure paths.
    assert "Remove-OptionFileQuietly" in script


def test_bundle_detects_managed_install_by_service_and_secret_and_is_permachine():
    bundle = _bundle_text()
    # RoofSpan-managed = service present AND RoofSpan credential present (service alone is insufficient).
    assert 'Key="SYSTEM\\CurrentControlSet\\Services\\RoofSpanPostgreSQL"' in bundle
    assert 'Variable="PgServicePresent"' in bundle
    assert 'pg_super.bin' in bundle and 'Variable="PgSecretPresent"' in bundle
    assert 'InstallCondition="NOT (PgServicePresent AND PgSecretPresent)"' in bundle
    assert 'DetectCondition="PgServicePresent AND PgSecretPresent"' in bundle
    # Every package is PerMachine so a double-click elevates (UAC) without "Run as administrator".
    for pkg_id in ("WebView2Runtime", "PostgreSQLPasswordPrep", "PostgreSQLPrereq", "PostgreSQLPasswordCleanup"):
        tag = re.search(rf'<ExePackage\b[^>]*\bId="{pkg_id}".*?(?:/>|</ExePackage>)', bundle, re.DOTALL)
        assert tag, f"missing ExePackage {pkg_id}"
        assert 'PerMachine="yes"' in tag.group(0), f"{pkg_id} must be PerMachine"


# The confirmed clean-computer 0x1 failure: Burn formats '[...]' tokens in InstallArguments, stripping
# PowerShell type accelerators. These MUST NOT reappear inside any ExePackage InstallArguments.
_BURN_FORMATTING_TRAPS = [
    "[string]", "[Convert]", "[IO.File]", "[Text.Encoding]", "[Security.Cryptography",
    "RandomNumberGenerator", "ProtectedData", "IsNullOrWhiteSpace", "ToBase64String",
    "-replace", "WriteAllBytes",
]


def test_prep_install_arguments_have_no_burn_formatting_type_expressions():
    args = _prep_install_arguments()
    for trap in _BURN_FORMATTING_TRAPS:
        assert trap not in args, f"PostgreSQLPasswordPrep InstallArguments reintroduced a Burn-formatted expression: {trap}"
    # The ONLY legitimate bracket token is the Hidden [PgSuperPassword] Burn variable.
    brackets = re.findall(r"\[[^\]]*\]", args)
    assert brackets == ["[PgSuperPassword]"], f"unexpected bracket tokens in InstallArguments: {brackets}"
    assert "-File Prepare-PostgreSQL.ps1" in args


def test_no_exepackage_install_arguments_use_inline_command_script():
    """Neither PowerShell helper may embed a program via -Command; both must invoke a -File payload."""
    bundle = _bundle_text()
    for tag in re.findall(r"<ExePackage\b[^>]*?(?:/>|>.*?</ExePackage>)", bundle, re.DOTALL):
        if "powershell.exe" not in tag:
            continue
        args = re.search(r'InstallArguments="([^"]*)"', tag)
        assert args, f"powershell ExePackage without InstallArguments:\n{tag}"
        assert "-Command" not in args.group(1), "powershell helper must use -File payload, not inline -Command"
        assert "-File " in args.group(1)
        assert re.search(r'<Payload\s+Name="[A-Za-z0-9\-]+\.ps1"\s+SourceFile="\$\(sys\.SOURCEFILEDIR\)scripts\\[A-Za-z0-9\-]+\.ps1"\s*/>', tag), \
            f"powershell ExePackage does not carry its .ps1 as a directory-anchored embedded Payload:\n{tag}"


def test_prep_and_cleanup_scripts_are_committed_and_ascii():
    for name in ("Prepare-PostgreSQL.ps1", "Cleanup-PostgreSQL.ps1"):
        path = INSTALLER / "scripts" / name
        assert path.exists(), f"missing installer script payload: {name}"
        raw = path.read_bytes()
        assert all(b < 128 for b in raw), f"{name} must be ASCII"
        assert b"password" not in raw.lower() or b"superpassword" in raw.lower()


def test_cleanup_script_preserves_identity_secret():
    cleanup = (INSTALLER / "scripts" / "Cleanup-PostgreSQL.ps1").read_text(encoding="utf-8")
    code = cleanup.split("#>")[-1]  # executable portion, excluding the explanatory comment block
    assert "pg_install.optionfile" in code and "Remove-Item" in code
    assert "pg_super.bin" not in code, "cleanup must NOT remove pg_super.bin (needed by RoofSpan first-run)"


def test_all_bundle_prerequisites_are_embedded():
    bundle = _bundle_text()
    assert 'Compressed="no"' not in bundle
    assert 'SourceFile="$(var.PostgresInstaller)"' in bundle
    assert 'SourceFile="$(var.WebView2StandaloneInstaller)"' in bundle
    assert 'SourceFile="$(var.MsiPath)"' in bundle
    assert bundle.count('Compressed="yes"') >= 4


def test_no_committed_or_hardcoded_password():
    bundle = _bundle_text()
    assert 'Value="RoofSpan' not in bundle
    assert "password=" not in bundle.lower() or "superpassword" in bundle.lower()
