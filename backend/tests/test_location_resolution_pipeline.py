from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"
WINDOWS = BACKEND.parent / "windows" / "winbuild"


def test_rentcast_import_is_separate_from_mapbox_resolution():
    source = (BACKEND / "routers" / "imports.py").read_text(encoding="utf-8")
    run_import = source[source.index("async def _run_import"):source.index("@router.post(\"/territories/{territory_id}/import\"")]
    assert "_mark_location_pending(nd)" in run_import
    assert "geocode_batch" not in run_import
    assert 'job.status = "completed"' in run_import
    assert "refresh_existing_property_locations(territory_id=territory_id)" in run_import
    assert run_import.index('job.status = "completed"') < run_import.index("refresh_existing_property_locations")
    assert "Mapbox Permanent Geocoding runs separately" in source


def test_second_phase_batches_uncached_properties_and_persists_completed_cache():
    source = (BACKEND / "location_upgrade.py").read_text(encoding="utf-8")
    assert 'RESOLUTION_VERSION = "mapbox_permanent_property_location_v2"' in source
    assert "CHUNK_SIZE = MAPBOX_BATCH_SIZE" in source
    assert "geocode_batch" in source
    assert 'loc["cached_permanently"] = True' in source
    assert 'loc["auto_resolution_version"] = RESOLUTION_VERSION' in source
    assert 'loc["auto_resolution_version"] = None' in source
    assert 'loc["resolution_state"] = "retry_pending"' in source
    assert '"street_alias_detected"' in source
    assert "await db.commit()" in source


def test_rentcast_refresh_preserves_same_address_permanent_cache():
    source = (BACKEND / "routers" / "imports.py").read_text(encoding="utf-8")
    assert "_preserve_permanent_location_cache" in source
    assert 'old_loc.get("cached_permanently") is True' in source
    assert 'old_loc.get("location_provider") == "mapbox"' in source
    assert 'old_loc.get("query_address")' in source
    assert 'preserved_loc.get("mapbox_latitude")' in source
    assert 'preserved_loc.get("mapbox_longitude")' in source


def test_single_property_action_uses_mapbox_location():
    backend_source = (BACKEND / "routers" / "properties.py").read_text(encoding="utf-8")
    ui_source = (FRONTEND / "components" / "PropertySheet.jsx").read_text(encoding="utf-8")
    assert '@router.post("/{property_id}/locate")' in backend_source
    assert 'action="property.locate_mapbox"' in backend_source
    assert "locate_property_now" in backend_source
    assert "Locate property with Mapbox" in ui_source
    assert "Cached locally" in ui_source
    assert "Geocodio" not in ui_source


def test_mapbox_byok_and_windows_freeze_are_wired():
    integrations = (BACKEND / "routers" / "integrations.py").read_text(encoding="utf-8")
    settings = (FRONTEND / "pages" / "admin" / "Settings.jsx").read_text(encoding="utf-8")
    spec = (WINDOWS / "roofspan-backend.spec").read_text(encoding="utf-8")
    build = (WINDOWS / "build_exes.ps1").read_text(encoding="utf-8")

    assert '"mapbox": {"label": "Mapbox Permanent Geocoding"' in integrations
    assert "_start_mapbox_backfill_if_ready" in integrations
    assert 'provider="mapbox"' in settings
    assert "Mapbox Permanent Geocoding" in settings
    assert '"location_upgrade", "mapbox_geocoding"' in spec
    assert "import server, location_upgrade, mapbox_geocoding" in build


def test_location_status_endpoint_exists():
    source = (BACKEND / "routers" / "imports.py").read_text(encoding="utf-8")
    assert '@router.get("/territories/{territory_id}/location-resolution")' in source
    assert 'status = loc.get("geocoder_status")' in source


def test_map_progress_is_sidebar_content_and_pin_diagnostics_are_collapsed_footer():
    progress = (FRONTEND / "components" / "LocationResolutionProgress.jsx").read_text(encoding="utf-8")
    sheet = (FRONTEND / "components" / "PropertySheet.jsx").read_text(encoding="utf-8")

    assert 'document.querySelector(\'[data-testid="territory-panel"]\')' in progress
    assert "createPortal(" in progress
    assert "fixed top-3" not in progress

    assert '<details className="group mt-6' in sheet
    assert 'data-testid="pin-location-diagnostics"' in sheet
    assert "<summary" in sheet
    assert " open=" not in sheet
    assert sheet.index('data-testid="convert-lead-button"') < sheet.index('data-testid="pin-location-diagnostics"')


def test_zip_search_frontend_has_matching_maptiler_backend_route():
    settings = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
    map_view = (FRONTEND / "pages" / "MapView.jsx").read_text(encoding="utf-8")

    assert '@router.get("/geocode/zip")' in settings
    assert '"types": "postal_code"' in settings
    assert '"country": "us"' in settings
    assert '"provider": "maptiler"' in settings
    assert '"bbox": [[float(bbox[0]), float(bbox[1])], [float(bbox[2]), float(bbox[3])]]' in settings
    assert '`/geocode/zip?zip=${encodeURIComponent(code)}`' in map_view
