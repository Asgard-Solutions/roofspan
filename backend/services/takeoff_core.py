"""Pure, deterministic roof takeoff calculations for Increment B.

Physical measurements remain immutable facts. This module applies estimating assumptions
(waste, derived metrics and packaging) without modifying measurement records.
"""
from __future__ import annotations

import math


def _num(value, default=0.0) -> float:
    if value in (None, ""):
        return float(default)
    return float(value)


def resolve_waste_percent(company_default: float = 10, *, template=None, assembly=None, estimate=None, structure=None) -> float:
    """Resolve waste from most-specific to least-specific assumption."""
    for value in (structure, estimate, assembly, template, company_default):
        if value not in (None, ""):
            return round(float(value), 4)
    return 10.0


def weighted_roof_waste_percent(area_by_structure: list[dict], *, base_waste: float, structure_overrides: dict | None = None) -> float:
    """Return the effective waste percent for a roof while preserving raw measured area."""
    structure_overrides = structure_overrides or {}
    measured = sum(_num(r.get("area_sqft")) for r in area_by_structure)
    if measured <= 0:
        return round(float(base_waste or 0), 4)
    adjusted = 0.0
    for row in area_by_structure:
        area = _num(row.get("area_sqft"))
        sid = str(row.get("structure_id")) if row.get("structure_id") is not None else None
        waste = structure_overrides.get(sid, base_waste)
        adjusted += area * (1 + _num(waste) / 100.0)
    return round(((adjusted / measured) - 1) * 100.0, 4)


def metric_value(metric_key: str, totals: dict, summary: dict | None, drip_edge_override=None) -> float:
    """Read a takeoff metric from an Increment A measurement snapshot."""
    summary = summary or {}
    edges = totals.get("edge_totals") or {}
    pens = totals.get("penetration_counts") or {}
    direct = {
        "roof_area_sqft": totals.get("total_area_sqft", 0),
        "roof_squares": totals.get("total_squares", 0),
        "eave_lf": edges.get("eave_lf", 0),
        "rake_lf": edges.get("rake_lf", 0),
        "ridge_lf": edges.get("ridge_lf", 0),
        "hip_lf": edges.get("hip_lf", 0),
        "valley_lf": edges.get("valley_lf", 0),
        "sidewall_lf": edges.get("sidewall_lf", 0),
        "headwall_lf": edges.get("headwall_lf", 0),
        "transition_lf": edges.get("transition_lf", 0),
        "penetration_total": totals.get("penetration_total", 0),
        "ridge_vent_lf": summary.get("ridge_vent_lf", 0),
        "intake_soffit_vent_lf": summary.get("intake_soffit_vent_lf", 0),
        "damaged_deck_sf": summary.get("damaged_deck_sf", 0),
        "replacement_sheets": summary.get("replacement_sheets", 0),
        "stories": summary.get("stories", 0),
        "steep_access": 1 if summary.get("steep_access") else 0,
        "high_access": 1 if summary.get("high_access") else 0,
        "long_carry": 1 if summary.get("long_carry") else 0,
        "restricted_access": 1 if summary.get("restricted_access") else 0,
        "landscaping_protection": 1 if summary.get("landscaping_protection") else 0,
    }
    if metric_key == "drip_edge_lf":
        if drip_edge_override not in (None, ""):
            return round(_num(drip_edge_override), 4)
        return round(_num(edges.get("eave_lf")) + _num(edges.get("rake_lf")), 4)
    if metric_key == "tearoff_squares":
        return round(_num(totals.get("total_squares")) * max(_num(summary.get("existing_layers")), 1), 4)
    if metric_key.startswith("penetration:"):
        return round(_num(pens.get(metric_key.split(":", 1)[1])), 4)
    return round(_num(direct.get(metric_key, 0)), 4)


def package_quantity(calculated_quantity: float, *, coverage_per_package=None, conversion_factor=None) -> float | None:
    """Round purchase packages up using explicit product coverage first, then existing conversion."""
    qty = _num(calculated_quantity)
    if coverage_per_package not in (None, "") and _num(coverage_per_package) > 0:
        return float(math.ceil(qty / _num(coverage_per_package)))
    if conversion_factor not in (None, "") and _num(conversion_factor) > 0:
        return float(math.ceil(qty * _num(conversion_factor)))
    return None
