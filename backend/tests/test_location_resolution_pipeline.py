from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"
WINDOWS = BACKEND.parent / "windows" / "winbuild"


def test_rentcast_import_is_separate_from_geocodio_resolution():
    source = (BACKEND / "routers" / "imports.py").read_text(encoding="utf-8")
    run_import = source[source.index("async def _run_import"):source.index("@router.post(\"/territories/{territory_id}/import\"")]

    # RentCast acquisition commits first. Geocoding is a second phase and cannot roll back the import.
    assert "_mark_location_pending(nd)" in run_import
    assert "geocode_batch" not in run_import
    assert 'job.status = "completed"' in run_import
    assert "refresh_existing_property_locations(territory_id=territory_id)" in run_import
    assert run_import.index('job.status = "completed"') < run_import.index("refresh_existing_property_locations")
    assert "Geocodio pin location runs separately" in source


def test_second_phase_batches_uncached_properties_and_persists_completed_cache():
    source = (BACKEND / "location_upgrade.py").read_text(encoding="utf-8")
    assert 'RESOLUTION_VERSION = "geocodio_property_location_v1"' in source
    assert "CHUNK_SIZE = GEOCODIO_BATCH_SIZE" in source
    assert "geocode_batch" in source
    assert 'loc["cached_permanently"] = True' in source
    assert 'loc["auto_resolution_version"] = RESOLUTION_VERSION' in source
    assert 'loc["auto_resolution_version"] = None' in source
    assert 'loc["resolution_state"] = "retry_pending"' in source
    assert "await db.commit()" in source


def test_rentcast_refresh_preserves_same_address_permanent_cache():
    source = (BACKEND / "routers" / "imports.py").read_text(encoding="utf-8")
    assert "_preserve_permanent_location_cache" in source
    assert 'old_loc.get("cached_permanently") is True' in source
    assert 'old_loc.get("location_provider") == "geocodio"' in source
    assert 'old_loc.get("query_address")' in source
    assert 'preserved_loc.get("geocodio_latitude")' in source
    assert 'preserved_loc.get("geocodio_longitude")' in source


def test_single_property_action_uses_geocodio_location():
    backend_source = (BACKEND / "routers" / "properties.py").read_text(encoding="utf-8")
    ui_source = (FRONTEND / "components" / "PropertySheet.jsx").read_text(encoding="utf-8")
    assert '@router.post("/{property_id}/locate")' in backend_source
    assert 'action="property.locate_geocodio"' in backend_source
    assert "locate_property_now" in backend_source
    assert "Locate property with Geocodio" in ui_source
    assert "Cached locally" in ui_source
    assert "Locate property with MapTiler" not in ui_source


def test_geocodio_byok_and_windows_freeze_are_wired():
    integrations = (BACKEND / "routers" / "integrations.py").read_text(encoding="utf-8")
    settings = (FRONTEND / "pages" / "admin" / "Settings.jsx").read_text(encoding="utf-8")
    spec = (WINDOWS / "roofspan-backend.spec").read_text(encoding="utf-8")
    build = (WINDOWS / "build_exes.ps1").read_text(encoding="utf-8")

    assert '"geocodio": {"label": "Geocodio"' in integrations
    assert "_start_geocodio_backfill_if_ready" in integrations
    assert 'provider="geocodio"' in settings
    assert "Geocodio Property Locations" in settings
    assert '"location_upgrade", "geocodio"' in spec
    assert "import server, location_upgrade, geocodio" in build


def test_location_status_endpoint_exists():
    source = (BACKEND / "routers" / "imports.py").read_text(encoding="utf-8")
    assert '@router.get("/territories/{territory_id}/location-resolution")' in source
    assert 'status = loc.get("geocoder_status")' in source
