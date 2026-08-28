"""Pure, deterministic roof takeoff calculations.

Physical measurements remain immutable facts. This module applies estimating assumptions
(waste, scoped metrics and packaging) without modifying measurement records.
"""
from __future__ import annotations

import math


def _num(value, default=0.0) -> float:
    if value in (None, ""):
        return float(default)
    return float(value)


def _prefer(totals: dict, scoped_key: str, legacy_key: str, default=0):
    value = totals.get(scoped_key)
    return totals.get(legacy_key, default) if value is None else value


def resolve_waste_percent(company_default: float = 10, *, template=None, assembly=None, estimate=None, structure=None) -> float:
    """Resolve waste from most-specific to least-specific assumption."""
    for value in (structure, estimate, assembly, template, company_default):
        if value not in (None, ""):
            return round(float(value), 4)
    return 10.0


def weighted_roof_waste_percent(area_by_structure: list[dict], *, base_waste: float, structure_overrides: dict | None = None) -> float:
    """Return effective waste percent while preserving raw measured area."""
    structure_overrides = structure_overrides or {}
    included_rows = [row for row in (area_by_structure or []) if row.get("included_in_scope", True) is not False]
    measured = sum(_num(r.get("area_sqft")) for r in included_rows)
    if measured <= 0:
        return round(float(base_waste or 0), 4)
    adjusted = 0.0
    for row in included_rows:
        area = _num(row.get("area_sqft"))
        sid = str(row.get("structure_id")) if row.get("structure_id") is not None else None
        waste = structure_overrides.get(sid, base_waste)
        adjusted += area * (1 + _num(waste) / 100.0)
    return round(((adjusted / measured) - 1) * 100.0, 4)


def _pitch_metric(metric_key: str, totals: dict) -> float | None:
    prefixes = {
        "roof_squares_pitch_gte:": "squares",
        "roof_area_sqft_pitch_gte:": "area_sqft",
    }
    for prefix, output in prefixes.items():
        if metric_key.startswith(prefix):
            try:
                threshold = float(metric_key.split(":", 1)[1])
            except (TypeError, ValueError):
                return 0.0
            rows = totals.get("takeoff_area_by_pitch")
            if rows is None:
                rows = totals.get("area_by_pitch") or []
            area = sum(
                _num(row.get("area_sqft"))
                for row in rows
                if row.get("pitch") is not None and _num(row.get("pitch")) >= threshold
            )
            return round(area / 100.0 if output == "squares" else area, 4)
    return None


def metric_value(metric_key: str, totals: dict, summary: dict | None, drip_edge_override=None) -> float:
    """Read a takeoff metric from a measurement snapshot, preferring takeoff-scoped totals."""
    summary = summary or {}
    pitch_value = _pitch_metric(metric_key, totals)
    if pitch_value is not None:
        return pitch_value

    edges = totals.get("takeoff_edge_totals")
    if edges is None:
        edges = totals.get("edge_totals") or {}
    pens = totals.get("takeoff_penetration_counts")
    if pens is None:
        pens = totals.get("penetration_counts") or {}

    roof_area = _prefer(totals, "takeoff_area_sqft", "total_area_sqft", 0)
    roof_squares = _prefer(totals, "takeoff_squares", "total_squares", 0)
    penetration_total = _prefer(totals, "takeoff_penetration_total", "penetration_total", 0)
    stories = totals.get("max_stories")
    if stories is None:
        stories = summary.get("stories", 0)

    direct = {
        "roof_area_sqft": roof_area,
        "roof_squares": roof_squares,
        "eave_lf": edges.get("eave_lf", 0),
        "rake_lf": edges.get("rake_lf", 0),
        "ridge_lf": edges.get("ridge_lf", 0),
        "hip_lf": edges.get("hip_lf", 0),
        "valley_lf": edges.get("valley_lf", 0),
        "sidewall_lf": edges.get("sidewall_lf", 0),
        "headwall_lf": edges.get("headwall_lf", 0),
        "transition_lf": edges.get("transition_lf", 0),
        "penetration_total": penetration_total,
        "ridge_vent_lf": summary.get("ridge_vent_lf", 0),
        "intake_soffit_vent_lf": summary.get("intake_soffit_vent_lf", 0),
        "damaged_deck_sf": summary.get("damaged_deck_sf", 0),
        "replacement_sheets": summary.get("replacement_sheets", 0),
        "stories": stories,
        "height_ft": totals.get("max_height_ft", 0),
        "steep_access": 1 if summary.get("steep_access") else 0,
        "high_access": 1 if summary.get("high_access") else 0,
        "long_carry": 1 if summary.get("long_carry") else 0,
        "restricted_access": 1 if summary.get("restricted_access") else 0,
        "landscaping_protection": 1 if summary.get("landscaping_protection") else 0,
    }
    if metric_key == "drip_edge_lf":
        if drip_edge_override not in (None, ""):
            return round(_num(drip_edge_override), 4)
        if summary.get("drip_edge_lf") not in (None, ""):
            return round(_num(summary.get("drip_edge_lf")), 4)
        return round(_num(edges.get("eave_lf")) + _num(edges.get("rake_lf")), 4)
    if metric_key == "tearoff_squares":
        return round(_num(roof_squares) * max(_num(summary.get("existing_layers")), 1), 4)
    if metric_key.startswith("penetration:"):
        return round(_num(pens.get(metric_key.split(":", 1)[1])), 4)
    return round(_num(direct.get(metric_key, 0)), 4)


def _unit(value) -> str:
    text = str(value or "").strip().upper().replace(".", "")
    aliases = {
        "SQUARE FOOT": "SF", "SQUARE FEET": "SF", "SQ FT": "SF", "SQFT": "SF", "FT2": "SF",
        "SQUARE": "SQ", "SQUARES": "SQ",
        "EACH": "EA", "UNIT": "EA", "UNITS": "EA",
        "LINEAR FOOT": "LF", "LINEAR FEET": "LF", "LIN FT": "LF",
    }
    return aliases.get(text, text)


def normalized_product_coverage(coverage_amount, coverage_unit, line_unit) -> float | None:
    """Normalize catalog coverage into one package's coverage in the estimate-line unit."""
    if coverage_amount in (None, "") or _num(coverage_amount) <= 0:
        return None
    source = _unit(coverage_unit)
    target = _unit(line_unit)
    amount = _num(coverage_amount)
    if not source or not target:
        return None
    if source == target:
        return round(amount, 6)
    if source == "SF" and target == "SQ":
        return round(amount / 100.0, 6)
    if source == "SQ" and target == "SF":
        return round(amount * 100.0, 6)
    return None


def package_quantity(calculated_quantity: float, *, coverage_per_package=None, conversion_factor=None) -> float | None:
    """Round purchase packages up using coverage first, then existing supplier conversion."""
    qty = _num(calculated_quantity)
    if coverage_per_package not in (None, "") and _num(coverage_per_package) > 0:
        return float(math.ceil(qty / _num(coverage_per_package)))
    if conversion_factor not in (None, "") and _num(conversion_factor) > 0:
        return float(math.ceil(qty * _num(conversion_factor)))
    return None
