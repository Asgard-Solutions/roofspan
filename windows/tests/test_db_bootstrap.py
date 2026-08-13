"""P1-4a fix: local PostgreSQL provisioning + deployed-config bootstrap.

Pure decision/render logic is unit-tested in-container; native psql/role/db execution, the WiX/Burn secret
handoff, and the BAFunctions credential generation are HUMAN REQUIRED on Windows and asserted statically.
"""
import glob
import os

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINBUILD = os.path.join(HERE, "winbuild")
WXS = os.path.join(HERE, "installer", "RoofSpan.wxs")
BUNDLE = os.path.join(HERE, "installer", "bundle.wxs")
BAFUNC = os.path.join(HERE, "bafunctions", "RoofSpanBaFunctions.cpp")
BAFUNC_DLLMAIN = os.path.join(HERE, "bafunctions", "dllmain.cpp")
BAFUNC_VCXPROJ = os.path.join(HERE, "bafunctions", "RoofSpanBaFunctions.vcxproj")
BAFUNC_DEF = os.path.join(HERE, "bafunctions", "RoofSpanBaFunctions.def")
BAFUNC_BUILD = os.path.join(HERE, "bafunctions", "build_bafunctions.ps1")
BUILD_PS1 = os.path.join(HERE, "installer", "build.ps1")

from winbuild import bootstrap_db as bs  # noqa: E402
from winbuild.targets import TOOL_TARGETS  # noqa: E402

TMPL = ("DATABASE_URL=postgresql+asyncpg://roofspan:__GENERATED_AT_FIRST_RUN__@127.0.0.1:5442/roofspan\n")


def _read(p):
    with open(p) as f:
        return f.read()


# --- credential generation -----------------------------------------------------------------------
def test_password_random_unique_and_long():
    a, b = bs.generate_db_password(), bs.generate_db_password()
    assert a != b and len(a) >= 24
    for weak in ("postgres", "roofspan", "__GENERATED_AT_FIRST_RUN__"):
        assert a != weak


# --- superuser credential is REQUIRED (handed off by the installer), never self-invented -----------
def test_bootstrap_no_longer_generates_a_superuser_credential():
    # The old circular concept (bootstrap inventing a new postgres password after PG install) is gone.
    assert not hasattr(bs, "generate_bootstrap_password")
    assert not hasattr(bs, "resolve_bootstrap_password")


def test_require_bootstrap_password_uses_supplied_value():
    assert bs.require_bootstrap_password("HANDED-OFF-SUPER") == "HANDED-OFF-SUPER"
    assert bs.require_bootstrap_password("  spaced  ") == "spaced"


def test_require_bootstrap_password_missing_fails_closed():
    for empty in ("", "   ", None):
        with pytest.raises(bs.BootstrapError):
            bs.require_bootstrap_password(empty)


def test_no_alter_user_postgres_circular_dependency_in_source():
    src = _read(os.path.join(WINBUILD, "bootstrap_db.py"))
    assert "ALTER USER postgres" not in src           # no post-install superuser (re)establishment
    assert "set_superuser" not in src                 # the circular flag/param is removed


# --- deployed config rendering -------------------------------------------------------------------
def test_render_substitutes_placeholder():
    out = bs.render_deployed_env(TMPL, "SUPERSECRET")
    assert "__GENERATED_AT_FIRST_RUN__" not in out and "SUPERSECRET" in out


def test_write_deployed_fresh_then_preserve_on_upgrade(tmp_path):
    tmpl = tmp_path / "t.env"
    tmpl.write_text(TMPL)
    dep = tmp_path / "deployed" / "roofspan.env"
    pw = bs.generate_db_password()
    bs.write_deployed_config(str(tmpl), str(dep), pw)
    body = dep.read_text()
    assert "__GENERATED_AT_FIRST_RUN__" not in body and pw in body     # real DATABASE_URL written
    assert ":roofspan@" not in body                                     # not a universal/placeholder pw
    # upgrade/repair: second call must PRESERVE existing creds (no overwrite)
    bs.write_deployed_config(str(tmpl), str(dep), bs.generate_db_password())
    assert dep.read_text() == body


# --- psql discovery (parsing) --------------------------------------------------------------------
def test_psql_path_from_base_dir():
    p = bs.psql_path_from_base_dir(r"C:\Program Files\RoofSpanPostgreSQL\15")
    assert p.endswith(os.path.join("bin", "psql.exe"))
    assert "RoofSpanPostgreSQL" in p


# --- orchestration: fresh install (credential handed off by Burn) --------------------------------
def test_run_bootstrap_provisions_then_writes_config(tmp_path):
    tmpl = tmp_path / "t.env"
    tmpl.write_text(TMPL)
    dep = tmp_path / "config" / "roofspan.env"
    seen = {}

    def fake_provision(*, psql_path, host, port, super_password, db_password):
        seen["config_exists_at_provision"] = os.path.isfile(str(dep))  # must be False (provision first)
        seen.update(super_password=super_password, db_password=db_password, port=port, host=host)

    rc = bs.run_bootstrap(supplied_super_pw="HANDED-OFF-SUPER", deployed_path=str(dep),
                          template_path=str(tmpl), psql_path="psql.exe", port=5442,
                          provision_fn=fake_provision)
    assert rc == 0
    assert seen["config_exists_at_provision"] is False          # config written only AFTER provisioning
    assert seen["super_password"] == "HANDED-OFF-SUPER"         # supplied credential used to authenticate
    assert seen["super_password"] != seen["db_password"]        # separate random values
    assert seen["port"] == 5442 and seen["host"] == "127.0.0.1"
    body = dep.read_text()
    assert seen["db_password"] in body                          # only the app password is persisted
    assert seen["super_password"] not in body                   # superuser credential never persisted


def test_run_bootstrap_missing_credential_fails_closed_no_config(tmp_path):
    tmpl = tmp_path / "t.env"
    tmpl.write_text(TMPL)
    dep = tmp_path / "config" / "roofspan.env"

    def fake_provision(**_):
        raise AssertionError("provisioning must not run when the handed-off credential is missing")

    with pytest.raises(bs.BootstrapError):
        bs.run_bootstrap(supplied_super_pw="", deployed_path=str(dep), template_path=str(tmpl),
                         psql_path="psql.exe", provision_fn=fake_provision)
    assert not os.path.isfile(str(dep))                          # fail closed: no deployed config


def test_run_bootstrap_provision_failure_writes_no_config(tmp_path):
    tmpl = tmp_path / "t.env"
    tmpl.write_text(TMPL)
    dep = tmp_path / "config" / "roofspan.env"

    def fake_provision(**_):
        raise RuntimeError("psql failed")

    with pytest.raises(RuntimeError):
        bs.run_bootstrap(supplied_super_pw="HANDED-OFF-SUPER", deployed_path=str(dep),
                         template_path=str(tmpl), psql_path="psql.exe", provision_fn=fake_provision)
    assert not os.path.isfile(str(dep))                          # config never written on failure


def test_run_bootstrap_upgrade_preserves_and_regenerates_nothing(tmp_path):
    tmpl = tmp_path / "t.env"
    tmpl.write_text(TMPL)
    dep = tmp_path / "config" / "roofspan.env"
    dep.parent.mkdir(parents=True)
    dep.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:EXISTING@127.0.0.1:5442/roofspan\n")

    def fake_provision(**_):
        raise AssertionError("upgrade must not re-provision or regenerate credentials")

    rc = bs.run_bootstrap(supplied_super_pw="", deployed_path=str(dep), template_path=str(tmpl),
                          psql_path="psql.exe", provision_fn=fake_provision)
    assert rc == 0 and "EXISTING" in dep.read_text()             # preserved untouched


# --- argv parsing ---------------------------------------------------------------------------------
def test_parse_args_defaults_and_port():
    a = bs.parse_args([])
    assert a.pg_superpassword == "" and a.pg_port == bs.DEFAULT_PG_PORT
    b = bs.parse_args(["--pg-superpassword", "S3CRET", "--pg-port", "5442"])
    assert b.pg_superpassword == "S3CRET" and b.pg_port == 5442


def test_dedicated_port_is_not_5432():
    assert bs.DEFAULT_PG_PORT == 5442  # RoofSpan-owned; not the common default 5432


# --- packaging + WiX authoring cross-checks -------------------------------------------------------
def test_template_ships_placeholder_and_dedicated_port():
    t = _read(os.path.join(WINBUILD, "config", "roofspan.env.template"))
    assert "__GENERATED_AT_FIRST_RUN__" in t
    assert "127.0.0.1:5442/roofspan" in t and "127.0.0.1:5432/roofspan" not in t


def test_bootstrap_registered_and_packaged():
    assert TOOL_TARGETS["RoofSpanBootstrap"] == "bootstrap_db.py"
    assert os.path.isfile(os.path.join(WINBUILD, "roofspan-bootstrap.spec"))
    wxs = _read(WXS)
    assert r"tools\RoofSpanBootstrap.exe" in wxs
    assert 'Action="RoofSpanBootstrap" Before="StartServices"' in wxs   # runs before backend start


def test_wxs_secret_handoff_is_hidden_and_not_logged():
    wxs = _read(WXS)
    assert 'Id="PG_SUPERPASSWORD"' in wxs
    assert 'Secure="yes"' in wxs and 'Hidden="yes"' in wxs
    assert '--pg-superpassword' in wxs and '[PG_SUPERPASSWORD]' in wxs
    assert '--pg-port' in wxs and '[PG_PORT]' in wxs
    assert 'DllEntry="WixSilentExec"' in wxs
    assert 'HideTarget="yes"' in wxs
    assert 'DllEntry="WixQuietExec"' not in wxs
    assert 'BinaryRef="Wix4UtilCA_$(sys.BUILDARCHSHORT)"' in wxs


def test_bundle_generates_credential_before_postgres_and_hands_off_same_value():
    b = _read(BUNDLE)
    # BAFunctions hook generates PgSuperPassword before the chain (keeps standard UI). WiX v5 attribute
    # is bal:BAFunctions (not the v4-proposal bal:IsBAFunctions).
    assert 'bal:BAFunctions="yes"' in b and "bal:IsBAFunctions" not in b
    assert 'SourceFile="$(var.BaFunctionsDll)"' in b
    # SAME hidden variable handed to BOTH the EDB installer and the MSI.
    assert '--superpassword [PgSuperPassword]' in b
    assert '<MsiProperty Name="PG_SUPERPASSWORD" Value="[PgSuperPassword]" />' in b
    # Hidden so Burn redacts it in logs everywhere it is formatted onto a command line.
    assert 'Name="PgSuperPassword"' in b and 'Hidden="yes"' in b


def test_bundle_detects_roofspan_managed_pg_not_generic():
    b = _read(BUNDLE)
    # Detection keyed to the DEDICATED RoofSpan service, not any PostgreSQL install.
    assert r"CurrentControlSet\Services\RoofSpanPostgreSQL" in b
    assert 'Variable="RoofSpanPgPresent"' in b
    assert 'InstallCondition="NOT RoofSpanPgPresent"' in b
    assert 'DetectCondition="RoofSpanPgPresent"' in b
    # The old generic "any PostgreSQL" detection must be gone.
    assert 'Variable="PgPresent"' not in b
    assert r"SOFTWARE\PostgreSQL\Installations" not in b


def test_bundle_uses_dedicated_port_for_collision_safety():
    b = _read(BUNDLE)
    assert 'Name="PgPort"' in b and 'Value="5442"' in b
    assert "--serverport [PgPort]" in b
    assert "--servicename RoofSpanPostgreSQL" in b
    assert '<MsiProperty Name="PG_PORT" Value="[PgPort]" />' in b


def test_bafunctions_source_generates_hidden_credential():
    c = _read(BAFUNC)
    assert "BCryptGenRandom" in c                       # CSPRNG source
    assert "PgSuperPassword" in c and "BalSetStringVariable" in c
    assert "OnPlanBegin" in c                           # after Detect, before the chain executes
    assert "RoofSpanPgPresent" in c                     # skip when managed PG already present
    assert "CBalBaseBAFunctions" in c                   # supplements WixStdBA (keeps standard UI)
    assert "CreateBAFunctions" in c
    # fail-closed on RNG/set failure (never proceed with an empty superpassword).
    assert "*pfCancel = TRUE" in c


def test_bafunctions_exports_and_entrypoints_present():
    dm = _read(BAFUNC_DLLMAIN)
    assert "BAFunctionsCreate" in dm and "BAFunctionsDestroy" in dm and "DllMain" in dm
    d = _read(BAFUNC_DEF)
    assert "BAFunctionsCreate" in d and "BAFunctionsDestroy" in d


def test_bafunctions_source_has_no_placeholder_pseudocode():
    # This gate requires REAL, build-valid source — no provisional / reconcile-later markers.
    blob = _read(BAFUNC) + _read(BAFUNC_DLLMAIN) + _read(os.path.join(HERE, "bafunctions", "pch.h"))
    lowered = blob.lower()
    for bad in ("reconcile", "in practice", "pseudocode", "your code goes here",
                "reconcile against the pinned", "expected later", "placeholder"):
        assert bad not in lowered, f"placeholder/pseudocode marker present: {bad!r}"


def test_bafunctions_pch_defines_dutil_types_before_bal_headers():
    pch = _read(os.path.join(HERE, "bafunctions", "pch.h"))
    # WiX v5 BAL/BAFunctions headers require these DUtil types; dictutil.h defines STRINGDICT_HANDLE used
    # by balinfo.h (pulled via BootstrapperApplicationBase.h).
    required_dutil = ["dutil.h", "dictutil.h", "fileutil.h", "pathutil.h", "strutil.h", "regutil.h"]
    for h in required_dutil:
        assert f'#include "{h}"' in pch, f"pch.h missing required DUtil header {h}"

    def pos(marker):
        i = pch.find(marker)
        assert i != -1, f"pch.h missing {marker}"
        return i

    bal_start = pos('#include "BootstrapperApplicationBase.h"')
    # Every DUtil header must be included BEFORE the BAL/BAFunctions headers.
    for h in required_dutil:
        assert pos(f'#include "{h}"') < bal_start, f"{h} must precede BootstrapperApplicationBase.h"
    for bal in ('#include "BAFunctions.h"', '#include "IBAFunctions.h"'):
        assert pos('#include "dictutil.h"') < pos(bal)
    # thmutil (via the BAL base) needs GDI+/common-controls system headers present first.
    assert "#include <gdiplus.h>" in pch and "#include <CommCtrl.h>" in pch
    # CSPRNG dependency preserved.
    assert "#include <bcrypt.h>" in pch


def test_bafunctions_build_project_pins_wix_v5_sdk():
    vcx = _read(BAFUNC_VCXPROJ)
    assert 'Include="WixToolset.BootstrapperApplicationApi" Version="5.0.2"' in vcx
    assert 'Include="WixToolset.WixStandardBootstrapperApplicationFunctionApi" Version="5.0.2"' in vcx
    assert "DynamicLibrary" in vcx                       # produces a DLL
    assert "RoofSpanBaFunctions.def" in vcx              # exports via the module-definition file
    assert "bcrypt.lib" in vcx                           # CSPRNG link dep
    # thmutil (transitive via the BAL base) link deps, mirroring the official WiX v5 BAFunctions build.
    for lib in ("gdiplus.lib", "comctl32.lib", "msimg32.lib"):
        assert lib in vcx, f"vcxproj missing link dependency {lib}"
    assert os.path.isfile(BAFUNC_BUILD)                  # reproducible build script exists


def test_installer_build_autobuilds_bafunctions():
    ps = _read(BUILD_PS1)
    assert "build_bafunctions.ps1" in ps                 # build.ps1 produces its own BAFunctions DLL
    assert '$BaFunctionsDll = ""' in ps or "$BaFunctionsDll = " in ps  # optional override, not mandatory
    assert "BaFunctionsDll=$BaFunctionsDll" in ps        # handed to the bundle build
    assert "wix --version 5" in ps or "wix --version 5.*" in ps  # standardized on WiX v5


def test_secrets_dir_is_backend_only_writable():
    wxs = _read(WXS)
    assert '<Directory Id="SecretsDir" Name="secrets" />' in wxs
    import re
    m = re.search(r'Id="AclSecrets".*?</Component>', wxs, re.S)
    assert m, "AclSecrets component missing"
    block = m.group(0)
    assert 'User="RoofSpanBackend"' in block and 'GenericWrite="yes"' in block
    assert "RoofSpanRelay" not in block and "RoofSpanUpdate" not in block  # not exposed to other services


# --- retry-safe DPAPI bootstrap credential recovery ----------------------------------------------
def test_require_bootstrap_password_error_has_exit_code_2():
    try:
        bs.require_bootstrap_password("")
        assert False, "expected BootstrapError"
    except bs.BootstrapError as e:
        assert e.code == 2 and "rerun" in str(e).lower()  # actionable, non-secret message


def test_purge_bootstrap_secret_removes_file_and_is_safe_when_absent(tmp_path):
    secret = tmp_path / "pgsuper.bin"
    secret.write_bytes(b"protected-blob")
    bs.purge_bootstrap_secret(str(secret))
    assert not secret.exists()
    bs.purge_bootstrap_secret(str(secret))          # absent -> no error
    bs.purge_bootstrap_secret("")                    # empty path -> no error


def _tmpl(tmp_path):
    t = tmp_path / "t.env"
    t.write_text(TMPL)
    return t


def test_run_bootstrap_purges_secret_only_after_success(tmp_path):
    tmpl = _tmpl(tmp_path)
    dep = tmp_path / "config" / "roofspan.env"
    secret = tmp_path / "pgsuper.bin"
    secret.write_bytes(b"protected-blob")

    def ok_provision(**_):
        pass

    rc = bs.run_bootstrap(supplied_super_pw="RECOVERED-SUPER", deployed_path=str(dep),
                          template_path=str(tmpl), psql_path="psql.exe", port=5442,
                          bootstrap_secret_path=str(secret), provision_fn=ok_provision)
    assert rc == 0 and dep.is_file()
    assert not secret.exists()  # secret securely removed only after role/db + config succeeded


def test_run_bootstrap_keeps_secret_when_provision_fails(tmp_path):
    tmpl = _tmpl(tmp_path)
    dep = tmp_path / "config" / "roofspan.env"
    secret = tmp_path / "pgsuper.bin"
    secret.write_bytes(b"protected-blob")

    def bad_provision(**_):
        raise RuntimeError("psql failed")

    with pytest.raises(RuntimeError):
        bs.run_bootstrap(supplied_super_pw="RECOVERED-SUPER", deployed_path=str(dep),
                         template_path=str(tmpl), psql_path="psql.exe",
                         bootstrap_secret_path=str(secret), provision_fn=bad_provision)
    assert secret.exists()       # NOT purged -> next RoofSpanSetup.exe run can still recover it
    assert not dep.exists()


def test_run_bootstrap_recovered_credential_completes_the_retry_sequence(tmp_path):
    # Rerun after PostgreSQL installed + MSI rolled back: Burn/BAFunctions recovered the DPAPI secret and
    # passes it here; deployed config is absent, so bootstrap provisions and then purges the secret.
    tmpl = _tmpl(tmp_path)
    dep = tmp_path / "config" / "roofspan.env"
    secret = tmp_path / "pgsuper.bin"
    secret.write_bytes(b"protected-blob")
    seen = {}

    def provision(*, psql_path, host, port, super_password, db_password):
        seen.update(super_password=super_password, db_password=db_password)

    rc = bs.run_bootstrap(supplied_super_pw="RECOVERED-SUPER", deployed_path=str(dep),
                          template_path=str(tmpl), psql_path="psql.exe",
                          bootstrap_secret_path=str(secret), provision_fn=provision)
    assert rc == 0
    assert seen["super_password"] == "RECOVERED-SUPER"     # recovered credential used to authenticate
    assert seen["super_password"] != seen["db_password"]   # separate random app password
    assert not secret.exists()
    assert seen["db_password"] in dep.read_text() and seen["super_password"] not in dep.read_text()


def test_run_bootstrap_missing_template_reports_code_5(tmp_path):
    dep = tmp_path / "config" / "roofspan.env"
    try:
        bs.run_bootstrap(supplied_super_pw="X", deployed_path=str(dep),
                         template_path=str(tmp_path / "missing.env"), psql_path="psql.exe",
                         provision_fn=lambda **_: None)
        assert False, "expected BootstrapError"
    except bs.BootstrapError as e:
        assert e.code == 5 and "template" in str(e).lower()


def test_default_template_matches_wix_installed_config_template():
    # The bootstrap DEFAULT_TEMPLATE must equal the file the MSI actually installs (ERROR_PATH_NOT_FOUND
    # / 0x80070003 otherwise). One canonical filename across staging, WiX, and bootstrap.
    staged = glob.glob(os.path.join(WINBUILD, "config", "roofspan.env*"))
    names = {os.path.basename(p) for p in staged}
    assert "roofspan.env.template" in names                      # the staged/source template filename
    assert bs.DEFAULT_TEMPLATE.split("\\")[-1] == "roofspan.env.template"
    assert bs.DEFAULT_TEMPLATE == r"C:\Program Files\RoofSpan Office\config-templates\roofspan.env.template"
    # deployed runtime file stays roofspan.env (NOT the template)
    assert bs.DEFAULT_DEPLOYED.split("\\")[-1] == "roofspan.env"
    wxs = _read(WXS)
    assert '<Directory Id="INSTALLFOLDER" Name="RoofSpan Office">' in wxs
    assert '<Directory Id="ConfigTemplatesDir" Name="config-templates" />' in wxs


def test_build_exes_rebuilds_fresh_per_spec_no_stale_artifacts():
    ps = _read(os.path.join(WINBUILD, "build_exes.ps1"))
    # dist is cleaned before each spec so only THIS spec's freshly-built exe is staged (no leftovers).
    assert "Remove-Item $distRoot -Recurse -Force" in ps
    assert "if (Test-Path $distRoot)" in ps
    assert "Expected exactly one exe for" in ps                  # guards against cross/stale exe staging


def test_build_script_has_stale_artifact_guard():
    ps = _read(os.path.join(HERE, "installer", "build.ps1"))
    assert "Stale staged executable" in ps                       # fails if staged exes older than sources
    assert "LastWriteTimeUtc" in ps
    assert r"tools\RoofSpanBootstrap.exe" in ps                   # bootstrap tool existence enforced
    c = _read(BAFUNC)
    # machine-protected DPAPI persistence + recovery, in the correct override -> recover -> generate order.
    assert "CryptProtectData" in c and "CryptUnprotectData" in c
    assert "CRYPTPROTECT_LOCAL_MACHINE" in c
    assert "PersistSecret" in c and "RecoverSecret" in c
    assert c.index("RecoverSecret(wzPassword") < c.index("GenerateHexPassword(ROOFSPAN_PG_PW_BYTES, wzPassword")
    # fresh install persists BEFORE handing the value to the chain (so a rollback is recoverable)
    assert c.index("PersistSecret(wzPassword)") < c.rindex("BalSetStringVariable(ROOFSPAN_PG_SUPERPASSWORD, wzPassword")
    vcx = _read(BAFUNC_VCXPROJ)
    assert "crypt32.lib" in vcx  # DPAPI link dependency
