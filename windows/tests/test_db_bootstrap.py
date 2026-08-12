"""P1-4a fix: hybrid local PostgreSQL + deployed-config bootstrap.

Pure decision/render logic is unit-tested in-container; native psql/role/db execution + the WiX/Burn
secret handoff are HUMAN REQUIRED on Windows.
"""
import os

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINBUILD = os.path.join(HERE, "winbuild")
WXS = os.path.join(HERE, "installer", "RoofSpan.wxs")
BUNDLE = os.path.join(HERE, "installer", "bundle.wxs")

from winbuild import bootstrap_db as bs  # noqa: E402
from winbuild.targets import TOOL_TARGETS  # noqa: E402


def _read(p):
    with open(p) as f:
        return f.read()


# --- credential generation -----------------------------------------------------------------------
def test_password_random_unique_and_long():
    a, b = bs.generate_db_password(), bs.generate_db_password()
    assert a != b and len(a) >= 24
    for weak in ("postgres", "roofspan", "__GENERATED_AT_FIRST_RUN__"):
        assert a != weak


def test_bootstrap_and_app_passwords_are_separate_random_values():
    assert bs.generate_bootstrap_password() != bs.generate_bootstrap_password()
    assert bs.generate_bootstrap_password() != bs.generate_db_password()
    assert len(bs.generate_bootstrap_password()) >= 24


# --- hybrid credential resolution ----------------------------------------------------------------
def test_resolve_supplied_credential_is_used_and_not_generated():
    pw, generated = bs.resolve_bootstrap_password("ENTERPRISE-SUPER", roofspan_managed=False)
    assert pw == "ENTERPRISE-SUPER" and generated is False
    # supplied wins even on a RoofSpan-managed instance
    pw2, gen2 = bs.resolve_bootstrap_password("ENTERPRISE-SUPER", roofspan_managed=True)
    assert pw2 == "ENTERPRISE-SUPER" and gen2 is False


def test_resolve_managed_fresh_install_generates_temporary_credential():
    pw, generated = bs.resolve_bootstrap_password("", roofspan_managed=True)
    assert generated is True and len(pw) >= 24
    assert pw not in ("", "postgres", "roofspan")


def test_resolve_external_pg_without_credential_fails_closed():
    with pytest.raises(bs.BootstrapError):
        bs.resolve_bootstrap_password("", roofspan_managed=False)
    with pytest.raises(bs.BootstrapError):
        bs.resolve_bootstrap_password("   ", roofspan_managed=False)  # whitespace-only is empty


# --- deployed config rendering -------------------------------------------------------------------
def test_render_substitutes_placeholder():
    tmpl = "DATABASE_URL=postgresql+asyncpg://roofspan:__GENERATED_AT_FIRST_RUN__@127.0.0.1:5432/roofspan\n"
    out = bs.render_deployed_env(tmpl, "SUPERSECRET")
    assert "__GENERATED_AT_FIRST_RUN__" not in out and "SUPERSECRET" in out


def test_write_deployed_fresh_then_preserve_on_upgrade(tmp_path):
    tmpl = tmp_path / "t.env"
    tmpl.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:__GENERATED_AT_FIRST_RUN__@127.0.0.1:5432/roofspan\n")
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


# --- orchestration: fresh RoofSpan-managed install -----------------------------------------------
def test_run_bootstrap_fresh_managed_provisions_then_writes_config(tmp_path):
    tmpl = tmp_path / "t.env"
    tmpl.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:__GENERATED_AT_FIRST_RUN__@127.0.0.1:5432/roofspan\n")
    dep = tmp_path / "config" / "roofspan.env"
    seen = {}

    def fake_provision(*, psql_path, super_password, db_password, set_superuser):
        # config must NOT exist yet — provisioning happens strictly before the config write
        seen["config_exists_at_provision"] = os.path.isfile(str(dep))
        seen.update(super_password=super_password, db_password=db_password, set_superuser=set_superuser)

    rc = bs.run_bootstrap(supplied_super_pw="", deployed_path=str(dep), template_path=str(tmpl),
                          roofspan_managed=True, psql_path="psql.exe", provision_fn=fake_provision)
    assert rc == 0
    assert seen["config_exists_at_provision"] is False          # config written only AFTER provisioning
    assert seen["set_superuser"] is True                        # generated temp superuser applied
    assert seen["super_password"] != seen["db_password"]        # separate random values
    body = dep.read_text()
    assert seen["db_password"] in body                          # only the app password is persisted
    assert seen["super_password"] not in body                   # bootstrap credential never persisted


# --- orchestration: enterprise/external PostgreSQL -----------------------------------------------
def test_run_bootstrap_enterprise_uses_supplied_credential(tmp_path):
    tmpl = tmp_path / "t.env"
    tmpl.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:__GENERATED_AT_FIRST_RUN__@127.0.0.1:5432/roofspan\n")
    dep = tmp_path / "config" / "roofspan.env"
    seen = {}

    def fake_provision(*, psql_path, super_password, db_password, set_superuser):
        seen.update(super_password=super_password, set_superuser=set_superuser, db_password=db_password)

    rc = bs.run_bootstrap(supplied_super_pw="ENTERPRISE-SUPER", deployed_path=str(dep),
                          template_path=str(tmpl), roofspan_managed=False, psql_path="psql.exe",
                          provision_fn=fake_provision)
    assert rc == 0
    assert seen["super_password"] == "ENTERPRISE-SUPER"         # supplied credential used as-is
    assert seen["set_superuser"] is False                       # no generated bootstrap credential
    assert seen["super_password"] not in dep.read_text()        # supplied superuser pw never persisted


def test_run_bootstrap_external_without_credential_fails_closed_no_config(tmp_path):
    tmpl = tmp_path / "t.env"
    tmpl.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:__GENERATED_AT_FIRST_RUN__@127.0.0.1:5432/roofspan\n")
    dep = tmp_path / "config" / "roofspan.env"

    def fake_provision(**_):
        raise AssertionError("provisioning must not run when the required credential is missing")

    with pytest.raises(bs.BootstrapError):
        bs.run_bootstrap(supplied_super_pw="", deployed_path=str(dep), template_path=str(tmpl),
                         roofspan_managed=False, psql_path="psql.exe", provision_fn=fake_provision)
    assert not os.path.isfile(str(dep))                          # fail closed: no deployed config


def test_run_bootstrap_provision_failure_writes_no_config(tmp_path):
    tmpl = tmp_path / "t.env"
    tmpl.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:__GENERATED_AT_FIRST_RUN__@127.0.0.1:5432/roofspan\n")
    dep = tmp_path / "config" / "roofspan.env"

    def fake_provision(**_):
        raise RuntimeError("psql failed")

    with pytest.raises(RuntimeError):
        bs.run_bootstrap(supplied_super_pw="", deployed_path=str(dep), template_path=str(tmpl),
                         roofspan_managed=True, psql_path="psql.exe", provision_fn=fake_provision)
    assert not os.path.isfile(str(dep))                          # config never written on failure


def test_run_bootstrap_upgrade_preserves_and_regenerates_nothing(tmp_path):
    tmpl = tmp_path / "t.env"
    tmpl.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:__GENERATED_AT_FIRST_RUN__@127.0.0.1:5432/roofspan\n")
    dep = tmp_path / "config" / "roofspan.env"
    dep.parent.mkdir(parents=True)
    dep.write_text("DATABASE_URL=postgresql+asyncpg://roofspan:EXISTING@127.0.0.1:5432/roofspan\n")

    def fake_provision(**_):
        raise AssertionError("upgrade must not re-provision")

    rc = bs.run_bootstrap(supplied_super_pw="", deployed_path=str(dep), template_path=str(tmpl),
                          roofspan_managed=True, psql_path="psql.exe", provision_fn=fake_provision)
    assert rc == 0 and "EXISTING" in dep.read_text()             # preserved untouched


# --- argv parsing ---------------------------------------------------------------------------------
def test_parse_args_superpassword_defaults_empty():
    a = bs.parse_args([])
    assert a.pg_superpassword == ""
    b = bs.parse_args(["--pg-superpassword", "S3CRET"])
    assert b.pg_superpassword == "S3CRET"


# --- packaging + WiX authoring cross-checks -------------------------------------------------------
def test_template_ships_placeholder_not_real_password():
    t = _read(os.path.join(WINBUILD, "config", "roofspan.env.template"))
    assert "__GENERATED_AT_FIRST_RUN__" in t


def test_bootstrap_registered_and_packaged():
    assert TOOL_TARGETS["RoofSpanBootstrap"] == "bootstrap_db.py"
    assert os.path.isfile(os.path.join(WINBUILD, "roofspan-bootstrap.spec"))
    wxs = _read(WXS)
    assert r"tools\RoofSpanBootstrap.exe" in wxs
    assert 'Action="RoofSpanBootstrap" Before="StartServices"' in wxs   # runs before backend start


def test_wxs_secret_handoff_is_hidden_and_not_logged():
    wxs = _read(WXS)
    # Hidden + Secure source property receives the credential from Burn.
    assert 'Id="PG_SUPERPASSWORD"' in wxs
    assert 'Secure="yes"' in wxs and 'Hidden="yes"' in wxs
    # SetProperty (Id == deferred CA Id) builds the CustomActionData command line with the argv.
    assert '--pg-superpassword' in wxs and '[PG_SUPERPASSWORD]' in wxs
    # WixSilentExec (not WixQuietExec) + HideTarget so the command line / CustomActionData are not logged.
    assert 'DllEntry="WixSilentExec"' in wxs
    assert 'HideTarget="yes"' in wxs
    assert 'DllEntry="WixQuietExec"' not in wxs
    assert 'BinaryRef="Wix4UtilCA_$(sys.BUILDARCHSHORT)"' in wxs


def test_bundle_hands_off_superpassword_to_msi():
    b = _read(BUNDLE)
    assert '<MsiProperty Name="PG_SUPERPASSWORD" Value="[PgSuperPassword]" />' in b
    assert 'Name="PgSuperPassword"' in b and 'Hidden="yes"' in b


def test_secrets_dir_is_backend_only_writable():
    wxs = _read(WXS)
    assert '<Directory Id="SecretsDir" Name="secrets" />' in wxs
    import re
    m = re.search(r'Id="AclSecrets".*?</Component>', wxs, re.S)
    assert m, "AclSecrets component missing"
    block = m.group(0)
    assert 'User="RoofSpanBackend"' in block and 'GenericWrite="yes"' in block
    assert "RoofSpanRelay" not in block and "RoofSpanUpdate" not in block  # not exposed to other services
