"""Pure contracts for completed roof-measurement derived totals."""
from services.measurement_core import derive_measurement_totals


def _sample():
    structures = [
        {"id": "house", "name": "Main House", "included_in_scope": True, "stories": 2, "approx_height_ft": 24},
        {"id": "garage", "name": "Detached Garage", "included_in_scope": False, "stories": 1, "approx_height_ft": 12},
    ]
    facets = [
        {"id": "f1", "structure_id": "house", "pitch_rise": 6, "area_sqft": 2000},
        {"id": "f2", "structure_id": "house", "pitch_rise": 10, "area_sqft": 500},
        {"id": "f3", "structure_id": "garage", "pitch_rise": 4, "area_sqft": 1000},
        {"id": "f4", "structure_id": None, "pitch_rise": 3, "area_sqft": 100},
    ]
    edges = [
        {"edge_type": "eave", "length_ft": 120, "facet_id": "f1"},
        {"edge_type": "eave", "length_ft": 50, "facet_id": "f3"},
        {"edge_type": "rake", "length_ft": 20, "facet_id": None},
    ]
    penetrations = [
        {"pen_type": "pipe_boot", "quantity": 2, "facet_id": "f1"},
        {"pen_type": "skylight", "quantity": 1, "facet_id": "f3"},
        {"pen_type": "static_vent", "quantity": 1, "facet_id": None},
    ]
    return structures, facets, edges, penetrations


def test_physical_totals_are_preserved_when_structure_is_excluded_from_takeoff():
    totals = derive_measurement_totals(*_sample())
    assert totals["total_area_sqft"] == 3600
    assert totals["total_squares"] == 36
    assert totals["takeoff_area_sqft"] == 2600
    assert totals["takeoff_squares"] == 26


def test_area_by_structure_exposes_inclusion_without_dropping_measured_structure():
    totals = derive_measurement_totals(*_sample())
    rows = {r["structure_id"]: r for r in totals["area_by_structure"]}
    assert rows["house"]["area_sqft"] == 2500
    assert rows["house"]["included_in_scope"] is True
    assert rows["garage"]["area_sqft"] == 1000
    assert rows["garage"]["included_in_scope"] is False
    assert rows[None]["area_sqft"] == 100
    assert rows[None]["included_in_scope"] is True


def test_takeoff_pitch_edges_and_penetrations_exclude_only_excluded_structure_geometry():
    totals = derive_measurement_totals(*_sample())
    pitches = {r["pitch"]: r["area_sqft"] for r in totals["takeoff_area_by_pitch"]}
    assert pitches == {3: 100, 6: 2000, 10: 500}
    assert totals["edge_totals"]["eave_lf"] == 170
    assert totals["takeoff_edge_totals"]["eave_lf"] == 120
    assert totals["takeoff_edge_totals"]["rake_lf"] == 20
    assert totals["penetration_counts"] == {"pipe_boot": 2, "skylight": 1, "static_vent": 1}
    assert totals["takeoff_penetration_counts"] == {"pipe_boot": 2, "static_vent": 1}
    assert totals["takeoff_penetration_total"] == 3


def test_max_stories_and_height_are_derived_from_included_structures_only():
    structures, facets, edges, penetrations = _sample()
    structures[1]["stories"] = 3
    structures[1]["approx_height_ft"] = 36
    totals = derive_measurement_totals(structures, facets, edges, penetrations)
    assert totals["max_stories"] == 2
    assert totals["max_height_ft"] == 24


def test_all_structures_included_by_default_for_backward_compatibility():
    structures, facets, edges, penetrations = _sample()
    for row in structures:
        row.pop("included_in_scope", None)
    totals = derive_measurement_totals(structures, facets, edges, penetrations)
    assert totals["takeoff_area_sqft"] == totals["total_area_sqft"] == 3600
