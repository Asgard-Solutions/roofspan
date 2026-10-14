"""Schema compatibility guard: service start never migrates an existing database."""
import sys
import types
from pathlib import Path

import pytest

WINBUILD = Path(__file__).resolve().parents[1] / "winbuild"
if str(WINBUILD) not in sys.path:
    sys.path.insert(0, str(WINBUILD))

import schema_guard as sg


class _Log:
    def info(self, *a):
        pass


def _tree(current, heads=("h2",), known=True, fresh=False):
    return {"current": current, "heads": list(heads), "known": known, "fresh": fresh}


@pytest.fixture()
def fake(monkeypatch):
    calls = []
    mr = types.ModuleType("migrations_runner")
    mr.run_migrations = lambda: calls.append("business")
    cpm = types.ModuleType("control_plane.migrations_runner")
    cpm.run_cp_migrations = lambda: calls.append("cp")
    cp = types.ModuleType("control_plane")
    cp.migrations_runner = cpm
    monkeypatch.setitem(sys.modules, "migrations_runner", mr)
    monkeypatch.setitem(sys.modules, "control_plane", cp)
    monkeypatch.setitem(sys.modules, "control_plane.migrations_runner", cpm)

    def set_status(biz, cpt):
        monkeypatch.setattr(sg, "status", lambda: {"business": biz, "control_plane": cpt})
    return calls, set_status


def test_brand_new_database_migrates_on_first_start(fake):
    calls, set_status = fake
    set_status(_tree(None, known=False, fresh=True), _tree(None, known=False, fresh=True))
    assert sg.enforce(_Log()) == "fresh" and calls == ["business", "cp"]


def test_current_schema_starts_without_migrating(fake):
    calls, set_status = fake
    set_status(_tree("h2"), _tree("h2"))
    assert sg.enforce(_Log()) == "current" and calls == []


@pytest.mark.parametrize("biz,cpt,needle", [
    (_tree("h1"), _tree("h2"), "business schema revision h1 is not this build's head"),
    (_tree("h2"), _tree("h1"), "control_plane schema revision h1 is not this build's head"),
    (_tree("zz_newer", known=False), _tree("h2"), "newer than this build supports"),
    (_tree("h2"), _tree(None, known=False), "control_plane schema revision None"),
])
def test_out_of_date_or_newer_schema_refuses_to_start(fake, biz, cpt, needle):
    calls, set_status = fake
    set_status(biz, cpt)
    with pytest.raises(sg.SchemaGuardError, match="RoofSpanSetup.exe") as e:
        sg.enforce(_Log())
    assert needle in str(e.value) and calls == []
