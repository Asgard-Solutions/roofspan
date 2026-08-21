from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]


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
    assert 'if result.get("status") == "error"' in source
    assert 'loc["auto_resolution_version"] = None' in source
    assert 'loc["resolution_state"] = "retry_pending"' in source


def test_location_status_endpoint_exists():
    source = (BACKEND / "routers" / "imports.py").read_text(encoding="utf-8")
    assert '@router.get("/territories/{territory_id}/location-resolution")' in source
