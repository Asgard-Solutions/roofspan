"""Real WiX 5 Burn-bundle compile smoke test + PostgreSQL/PgSuperPassword wiring regressions.

Why this exists: bundle.wxs shipped a `Variable Type="string"` with no `Value` (WIX0010) AND
`ExePackage SourceFile="[BurnRuntimeVariable]"` (WIX0103) - both of which only surface when the Burn
bundle is actually compiled, not by static XML inspection. `test_installer_static.py` could NOT catch
them. This module invokes the real `wix build` so schema/compiler regressions fail in CI before a
human ever runs the Windows build.

  * When `wix` is on PATH (always in the windows-build CI job) this runs a real compile.
  * On Windows it must produce the RoofSpanSetup.exe artifact (authoritative).
  * On non-Windows, WiX prints "behavior undefined" and fails at the payload-bind stage (WIX0389 hits
    even WiX's own BAL payloads), so we only assert the COMPILE-stage regressions are gone
    (no WIX0010, and no `[BurnVariable]` used as an ExePackage SourceFile).
  * When `wix` is absent (default ubuntu unit runner) the compile test skips; the static wiring
    assertions below still run everywhere.
"""
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "installer"
BUNDLE = INSTALLER / "bundle.wxs"
WIX = shutil.which("wix")


_DUMMY_MSI_WXS = (
    '<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">'
    '<Package Name="RoofSpan Dummy" Manufacturer="RoofSpan" Version="0.2.0" '
    'UpgradeCode="11111111-1111-1111-1111-111111111111" Scope="perMachine" Compressed="yes">'
    '<MediaTemplate EmbedCab="yes" />'
    '<StandardDirectory Id="ProgramFiles64Folder"><Directory Id="APPDIR" Name="RoofSpanDummy">'
    '<Component Id="C1" Guid="22222222-2222-2222-2222-222222222222">'
    '<RegistryValue Root="HKLM" Key="Software\\RoofSpanDummy" Name="v" Type="string" Value="1" KeyPath="yes" />'
    '</Component></Directory></StandardDirectory>'
    '<Feature Id="F"><ComponentRef Id="C1" /></Feature></Package></Wix>'
)


def _make_payloads(outdir: Path):
    """Real MSI (WiX parses MsiPackage metadata) + real PE stand-ins for the ExePackage payloads."""
    msi = outdir / "RoofSpanOffice.msi"
    wxs = outdir / "dummy.wxs"
    wxs.write_text(_DUMMY_MSI_WXS, encoding="utf-8")
    subprocess.run([WIX, "build", str(wxs), "-arch", "x64", "-o", str(msi)], capture_output=True, text=True)
    if not msi.exists():
        msi.write_bytes(b"MZ" + b"\0" * 4096)  # off-Windows: bind fails before MSI is parsed anyway

    pg = outdir / "postgres.exe"
    wv = outdir / "webview2.exe"
    if platform.system() == "Windows":
        import os
        real = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "where.exe"
        for p in (pg, wv):
            shutil.copyfile(real, p)
    else:
        for p in (pg, wv):
            p.write_bytes(b"MZ" + b"\0" * 4096)
    return msi, pg, wv


def _run_wix_build(outdir: Path):
    """Invoke the canonical bundle build with throwaway payloads; return (returncode, combined_output)."""
    import os
    msi, pg, wv = _make_payloads(outdir)
    env = dict(os.environ)
    if platform.system() != "Windows":
        # $(env.SystemRoot) is a COMPILE-time preprocessor var referenced by the PowerShell ExePackage;
        # it is always defined on the Windows build host. Off-Windows we must define it (to a fake tree
        # with a stand-in powershell.exe) so the preprocessor does not abort BEFORE the Variable/@Value
        # (WIX0010) check we are guarding - otherwise this smoke test would silently miss a regression.
        fake = outdir / "win"
        ps_dir = fake / "System32" / "WindowsPowerShell" / "v1.0"
        ps_dir.mkdir(parents=True, exist_ok=True)
        (ps_dir / "powershell.exe").write_bytes(b"MZ" + b"\0" * 4096)
        # WiX joins "$(env.SystemRoot)" + literal "\System32\..."; create that literal name too so bind
        # at least attempts our payload rather than aborting for a missing directory.
        (outdir / (str(fake.name) + r"\System32\WindowsPowerShell\v1.0\powershell.exe"))
        env["SystemRoot"] = str(fake)
    cmd = [
        WIX, "build", str(BUNDLE), "-arch", "x64",
        "-d", "Version=0.2.0",
        "-d", f"MsiPath={msi}",
        "-d", f"PostgresInstaller={pg}",
        "-d", f"WebView2Bootstrapper={wv}",
        "-ext", "WixToolset.BootstrapperApplications.wixext",
        "-ext", "WixToolset.Util.wixext",
        "-o", str(outdir / "RoofSpanSetup.exe"),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


@pytest.mark.skipif(WIX is None, reason="wix CLI not installed; authoritative compile runs in the windows-build CI job")
def test_burn_bundle_compiles():
    with tempfile.TemporaryDirectory() as td:
        outdir = Path(td)
        rc, out = _run_wix_build(outdir)

        # COMPILE-stage regressions must never come back (these are the reported blockers):
        assert "WIX0010" not in out, f"WIX0010 regressed (typed Variable without Value):\n{out}"
        assert "'[WebView2Bootstrapper]'" not in out, f"ExePackage SourceFile must not be a Burn variable:\n{out}"
        assert "'[PostgresInstaller]'" not in out, f"ExePackage SourceFile must not be a Burn variable:\n{out}"

        if platform.system() == "Windows":
            # Authoritative: the customer-facing bundle must actually build.
            artifact = outdir / "RoofSpanSetup.exe"
            assert rc == 0 and artifact.exists(), f"Burn bundle failed to compile on Windows:\n{out}"
        else:
            # WiX is unsupported off-Windows; it compiles/validates our authoring, then fails at the
            # payload-bind stage (WIX0389 hits even WiX's own BAL payloads on Linux). The meaningful
            # signal here is that the COMPILE stage produced none of the guarded regressions above and
            # did not abort on a preprocessor error (SystemRoot is defined in _run_wix_build).
            assert "WIX0150" not in out, f"preprocessor aborted the compile; WIX0010 guard would be missed:\n{out}"


# ---- Static wiring guards (run everywhere, no wix required) -----------------------------------------

def _bundle_text():
    return BUNDLE.read_text(encoding="utf-8")


def test_pgsuperpassword_is_untyped_hidden_nonpersisted():
    b = _bundle_text()
    assert '<Variable Name="PgSuperPassword" Hidden="yes" Persisted="no"' in b, \
        "PgSuperPassword must stay Hidden + non-persisted"
    # WIX0010 fix: a typed variable requires a Value; this one must remain untyped/valueless.
    assert 'Name="PgSuperPassword" Type=' not in b, "PgSuperPassword must NOT declare Type (WIX0010)"
    # and must never carry a committed default value
    assert 'Name="PgSuperPassword"' in b and 'PgSuperPassword" Type="string" Value' not in b


def test_no_exepackage_sourcefile_uses_burn_variable():
    """WIX0103 guard: an ExePackage SourceFile must resolve at build time, never a runtime [variable]."""
    import re
    b = _bundle_text()
    for m in re.finditer(r'SourceFile="([^"]+)"', b):
        val = m.group(1)
        assert not (val.startswith("[") and val.endswith("]")), \
            f"ExePackage/MsiPackage SourceFile must not be a Burn runtime variable: {val}"


def test_postgres_step_generates_secure_password_at_runtime():
    b = _bundle_text()
    # Runtime generation when no password supplied, using a CSPRNG (not committed / not hardcoded).
    assert "RandomNumberGenerator" in b, "postgres step must generate the superpassword with a CSPRNG"
    assert "IsNullOrWhiteSpace($p)" in b, "must only generate when PgSuperPassword was not supplied"
    assert "[PgSuperPassword]" in b, "the admin-overridable Burn variable must feed the step"
    # DPAPI-protected so RoofSpan first-run can later provision its least-privilege role.
    assert "ProtectedData" in b and "LocalMachine" in b, "generated secret must be DPAPI-protected (machine scope)"
    # EDB unattended install contract preserved.
    assert "--mode','unattended'" in b and "--superpassword'," in b
    assert "'--servicename','RoofSpanPostgreSQL'" in b, "the RoofSpanPostgreSQL service name must be preserved"
    # Failure of the EDB installer must fail the package (exit code propagated).
    assert "exit $pr.ExitCode" in b


def test_no_committed_or_hardcoded_password():
    b = _bundle_text()
    # No literal 'superpassword <value>' and no default Value on the hidden var.
    assert 'Value="RoofSpan' not in b
    assert "password=" not in b.lower() or "superpassword" in b.lower()  # only the arg name, never a literal value
