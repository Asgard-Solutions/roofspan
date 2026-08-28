"""Pure contract tests for Roof Measurement Increment B takeoff math.

These tests deliberately avoid database/network dependencies so the quantity rules can be
verified deterministically in CI. Production API tests build on these contracts.
"""
import math

from services.takeoff_core import (
    resolve_waste_percent,
    weighted_roof_waste_percent,
    metric_value,
    package_quantity,
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
    # 2000*1.10 + 1000*1.15 = 3350 => effective waste 11.6666...%
    assert math.isclose(waste, 11.6667, abs_tol=0.0001)


def test_metric_value_drip_edge_is_eave_plus_rake_unless_overridden():
    totals = {"total_area_sqft": 2846, "edge_totals": {"eave_lf": 120, "rake_lf": 80}}
    assert metric_value("drip_edge_lf", totals, {}, None) == 200
    assert metric_value("drip_edge_lf", totals, {}, 225) == 225


def test_metric_value_roof_and_tearoff_metrics():
    totals = {"total_area_sqft": 2846, "total_squares": 28.46, "edge_totals": {}}
    summary = {"existing_layers": 2}
    assert metric_value("roof_area_sqft", totals, summary, None) == 2846
    assert metric_value("roof_squares", totals, summary, None) == 28.46
    assert metric_value("tearoff_squares", totals, summary, None) == 56.92


def test_metric_value_penetration_type_and_conditions():
    totals = {"penetration_counts": {"pipe_boot": 3, "skylight": 1}, "penetration_total": 4, "edge_totals": {}}
    summary = {"steep_access": True, "stories": 2}
    assert metric_value("penetration:pipe_boot", totals, summary, None) == 3
    assert metric_value("penetration_total", totals, summary, None) == 4
    assert metric_value("steep_access", totals, summary, None) == 1
    assert metric_value("stories", totals, summary, None) == 2


def test_product_coverage_rounds_packages_up_without_hard_coded_bundle_count():
    # A product covering 1/3 SQ per package needs 96 packages for 31.88 SQ.
    assert package_quantity(31.88, coverage_per_package=(1 / 3), conversion_factor=None) == 96
    # Fallback remains the existing purchase conversion rule when explicit coverage is absent.
    assert package_quantity(31.88, coverage_per_package=None, conversion_factor=3) == 96
    assert package_quantity(31.88, coverage_per_package=None, conversion_factor=None) is None
