import uuid
from types import SimpleNamespace

from property_dedup import address_fingerprint, likely_duplicate


def _prop(address, lat, lng, *, territory=None, address2=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        territory_id=territory or uuid.UUID("11111111-1111-1111-1111-111111111111"),
        address_line1=address,
        address_line2=address2,
        city="Blanchard",
        state="OK",
        zip_code="73010",
        latitude=lat,
        longitude=lng,
    )


def test_normalization_treats_missing_directional_as_same_street_core():
    a = address_fingerprint("1778 S Ruby Dr", "Blanchard", "OK", "73010")
    b = address_fingerprint("1778 Ruby Drive", "Blanchard", "OK", "73010")
    assert a["house"] == b["house"] == "1778"
    assert a["street_core"] == b["street_core"] == "ruby dr"
    assert a["directionals"] == frozenset({"s"})
    assert b["directionals"] == frozenset()


def test_ruby_drive_duplicate_is_merged_when_pins_are_close():
    # Mirrors the real duplicate pattern: one record includes S, one omits it, and the pins are
    # only a few dozen feet apart.
    a = _prop("1778 S Ruby Dr", 35.120891, -97.673160)
    b = _prop("1778 Ruby Dr", 35.120784, -97.673193)
    assert likely_duplicate(a, b) is True


def test_opposite_directionals_are_never_auto_merged():
    a = _prop("1778 N Main St", 35.120891, -97.673160)
    b = _prop("1778 S Main St", 35.120900, -97.673170)
    assert likely_duplicate(a, b) is False


def test_far_apart_same_relaxed_address_is_not_auto_merged():
    a = _prop("1778 S Ruby Dr", 35.120891, -97.673160)
    b = _prop("1778 Ruby Dr", 35.130000, -97.673160)
    assert likely_duplicate(a, b) is False


def test_different_explicit_units_are_not_auto_merged():
    a = _prop("1778 S Ruby Dr", 35.120891, -97.673160, address2="Unit A")
    b = _prop("1778 Ruby Dr", 35.120784, -97.673193, address2="Unit B")
    assert likely_duplicate(a, b) is False


def test_pipeline_runs_cleanup_before_mapbox_and_windows_freezes_module():
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    repo = backend.parent
    server = (backend / "server.py").read_text(encoding="utf-8")
    imports = (backend / "routers" / "imports.py").read_text(encoding="utf-8")
    spec = (repo / "windows" / "winbuild" / "roofspan-backend.spec").read_text(encoding="utf-8")
    build = (repo / "windows" / "winbuild" / "build_exes.ps1").read_text(encoding="utf-8")

    assert "cleanup_duplicates_then_refresh_locations" in server
    assert server.index("cleanup_duplicate_properties()") < server.index("refresh_existing_property_locations()")
    assert "_cleanup_then_resolve" in imports
    helper = imports[imports.index("async def _cleanup_then_resolve"):imports.index("async def _run_import")]
    assert helper.index("cleanup_duplicate_properties") < helper.index("refresh_existing_property_locations")
    assert '"property_dedup", "location_upgrade", "mapbox_geocoding"' in spec
    assert "import server, property_dedup, location_upgrade, mapbox_geocoding" in build
