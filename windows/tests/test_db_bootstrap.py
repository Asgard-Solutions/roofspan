"""P1-4a fix: local PostgreSQL + deployed-config bootstrap (pure logic; native psql HUMAN REQUIRED)."""
import os

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINBUILD = os.path.join(HERE, "winbuild")
WXS = os.path.join(HERE, "installer", "RoofSpan.wxs")

from winbuild import bootstrap_db as bs  # noqa: E402
from winbuild.targets import TOOL_TARGETS  # noqa: E402


def _read(p):
    with open(p) as f:
        return f.read()


def test_password_random_unique_and_long():
    a, b = bs.generate_db_password(), bs.generate_db_password()
    assert a != b and len(a) >= 24
    for weak in ("postgres", "roofspan", "__GENERATED_AT_FIRST_RUN__"):
        assert a != weak


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


def test_template_ships_placeholder_not_real_password():
    t = _read(os.path.join(WINBUILD, "config", "roofspan.env.template"))
    assert "__GENERATED_AT_FIRST_RUN__" in t


def test_bootstrap_registered_and_packaged():
    assert TOOL_TARGETS["RoofSpanBootstrap"] == "bootstrap_db.py"
    assert os.path.isfile(os.path.join(WINBUILD, "roofspan-bootstrap.spec"))
    wxs = _read(WXS)
    assert r"tools\RoofSpanBootstrap.exe" in wxs
    assert 'Action="RoofSpanBootstrap" Before="StartServices"' in wxs   # runs before backend start


def test_secrets_dir_is_backend_only_writable():
    wxs = _read(WXS)
    assert '<Directory Id="SecretsDir" Name="secrets" />' in wxs
    import re
    m = re.search(r'Id="AclSecrets".*?</Component>', wxs, re.S)
    assert m, "AclSecrets component missing"
    block = m.group(0)
    assert 'User="RoofSpanBackend"' in block and 'GenericWrite="yes"' in block
    assert "RoofSpanRelay" not in block and "RoofSpanUpdate" not in block  # not exposed to other services
