"""Pure contracts for RoofSpan roof takeoff math.

These tests deliberately avoid database/network dependencies so quantity rules stay deterministic
and safe to run in CI.
"""
import math

from services.takeoff_core import (
    resolve_waste_percent,
    weighted_roof_waste_percent,
    metric_value,
    package_quantity,
    normalized_product_coverage,
)


def test_waste_precedence_structure_estimate_assembly_template_company():
    assert resolve_waste_percent(10, template=11, assembly=12, estimate=15, structure=18) == 18
    assert resolve_waste_percent(10, template=11, assembly=12, estimate=15) == 15
    assert resolve_waste_percent(10, template=11, assembly=12) == 12
    assert resolve_waste_percent(10, template=11) == 11
    assert resolve_waste_percent(10) == 10


def test_weighted_roof_waste_uses_structure_overrides_without_changing_measured_area():
    areas = [
        {"structure_id": "house", "area_sqft": 2000},
        {"structure_id": "garage", "area_sqft": 1000},
    ]
    waste = weighted_roof_waste_percent(areas, base_waste=10, structure_overrides={"garage": 15})
    assert math.isclose(waste, 11.6667, abs_tol=0.0001)


def test_metric_value_prefers_takeoff_scope_but_keeps_legacy_fallback():
    totals = {
        "total_area_sqft": 3600,
        "total_squares": 36,
        "takeoff_area_sqft": 2600,
        "takeoff_squares": 26,
        "edge_totals": {},
        "takeoff_edge_totals": {},
    }
    assert metric_value("roof_area_sqft", totals, {}) == 2600
    assert metric_value("roof_squares", totals, {}) == 26
    assert metric_value("roof_squares", {"total_squares": 36, "edge_totals": {}}, {}) == 36


def test_metric_value_drip_edge_override_then_measured_then_eave_plus_rake():
    totals = {"edge_totals": {"eave_lf": 120, "rake_lf": 80}, "takeoff_edge_totals": {"eave_lf": 120, "rake_lf": 80}}
    assert metric_value("drip_edge_lf", totals, {"drip_edge_lf": 210}, None) == 210
    assert metric_value("drip_edge_lf", totals, {"drip_edge_lf": 210}, 225) == 225
    assert metric_value("drip_edge_lf", totals, {}, None) == 200


def test_metric_value_roof_and_tearoff_metrics_use_takeoff_scope():
    totals = {"total_area_sqft": 3600, "total_squares": 36, "takeoff_area_sqft": 2846, "takeoff_squares": 28.46, "edge_totals": {}}
    summary = {"existing_layers": 2}
    assert metric_value("roof_area_sqft", totals, summary, None) == 2846
    assert metric_value("roof_squares", totals, summary, None) == 28.46
    assert metric_value("tearoff_squares", totals, summary, None) == 56.92


def test_metric_value_pitch_thresholds_use_scoped_pitch_distribution():
    totals = {
        "takeoff_area_by_pitch": [
            {"pitch": 4, "area_sqft": 400, "squares": 4},
            {"pitch": 7, "area_sqft": 600, "squares": 6},
            {"pitch": 10, "area_sqft": 500, "squares": 5},
            {"pitch": 12, "area_sqft": 200, "squares": 2},
        ],
        "edge_totals": {},
    }
    assert metric_value("roof_squares_pitch_gte:7", totals, {}) == 13
    assert metric_value("roof_squares_pitch_gte:9", totals, {}) == 7
    assert metric_value("roof_squares_pitch_gte:12", totals, {}) == 2
    assert metric_value("roof_area_sqft_pitch_gte:9", totals, {}) == 700


def test_metric_value_penetrations_stories_and_height_use_scoped_totals():
    totals = {
        "penetration_counts": {"pipe_boot": 3, "skylight": 1},
        "penetration_total": 4,
        "takeoff_penetration_counts": {"pipe_boot": 2},
        "takeoff_penetration_total": 2,
        "max_stories": 2,
        "max_height_ft": 24,
        "edge_totals": {},
    }
    summary = {"steep_access": True, "stories": 1}
    assert metric_value("penetration:pipe_boot", totals, summary, None) == 2
    assert metric_value("penetration_total", totals, summary, None) == 2
    assert metric_value("steep_access", totals, summary, None) == 1
    assert metric_value("stories", totals, summary, None) == 2
    assert metric_value("height_ft", totals, summary, None) == 24


def test_product_coverage_normalizes_to_estimate_line_unit():
    # Product catalog may describe a shingle bundle as 33.33 square feet while the estimate line is SQ.
    assert math.isclose(normalized_product_coverage(33.33, "SF", "SQ"), 0.3333, abs_tol=0.0001)
    assert normalized_product_coverage(0.5, "SQ", "SQ") == 0.5
    assert normalized_product_coverage(100, "SF", "SF") == 100
    assert normalized_product_coverage(1, "EA", "EA") == 1
    assert normalized_product_coverage(33.33, "SF", "EA") is None
    assert normalized_product_coverage(None, "SF", "SQ") is None


def test_product_coverage_rounds_packages_up_without_hard_coded_bundle_count():
    assert package_quantity(31.88, coverage_per_package=(1 / 3), conversion_factor=None) == 96
    assert package_quantity(31.88, coverage_per_package=None, conversion_factor=3) == 96
    assert package_quantity(31.88, coverage_per_package=None, conversion_factor=None) is None
