from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"


def test_rentcast_import_is_separate_from_maptiler_resolution():
    source = (BACKEND / "routers" / "imports.py").read_text(encoding="utf-8")
    run_import = source[source.index("async def _run_import"):source.index("@router.post(\"/territories/{territory_id}/import\"")]

    # The import saves RentCast coordinates first and only queues the resolver after completion.
    assert "_mark_location_pending(nd)" in run_import
    assert "geocode_addresses_batch" not in run_import
    assert 'job.status = "completed"' in run_import
    assert "refresh_existing_property_locations(territory_id=territory_id)" in run_import
    assert run_import.index('job.status = "completed"') < run_import.index("refresh_existing_property_locations")


def test_second_phase_uses_single_address_requests_and_retries_transport_errors():
    source = (BACKEND / "location_upgrade.py").read_text(encoding="utf-8")
    assert "[address]" in source, "MapTiler second phase must isolate each address request"
    assert "CONCURRENCY = 8" in source
    assert 'result.get("status") == "error"' in source
    assert 'loc["auto_resolution_version"] = None' in source
    assert 'loc["resolution_state"] = "retry_pending"' in source


def test_rentcast_address_is_authoritative_and_road_result_is_only_a_search_anchor():
    source = (BACKEND / "location_upgrade.py").read_text(encoding="utf-8")
    assert 'RESOLUTION_VERSION = "maptiler_property_location_v4"' in source
    assert "_road_anchor_matches_known_property" in source
    assert "_locate_numbered_building_from_anchor" in source
    assert '"road_anchor_building_number"' in source
    assert 'result["status"] = "located"' in source
    assert 'loc["location_resolved"]' not in source or '"location_resolved": location_resolved' in source
    assert 'loc["coordinate_source"] = "rentcast"' in source


def test_single_property_action_is_location_not_address_validation():
    backend_source = (BACKEND / "routers" / "properties.py").read_text(encoding="utf-8")
    ui_source = (FRONTEND / "components" / "PropertySheet.jsx").read_text(encoding="utf-8")
    assert '@router.post("/{property_id}/locate")' in backend_source
    assert 'action="property.locate_maptiler"' in backend_source
    assert "Locate property with MapTiler" in ui_source
    assert "Pin location:" in ui_source
    assert "Verify address with MapTiler" not in ui_source


def test_location_status_endpoint_exists():
    source = (BACKEND / "routers" / "imports.py").read_text(encoding="utf-8")
    assert '@router.get("/territories/{territory_id}/location-resolution")' in source
