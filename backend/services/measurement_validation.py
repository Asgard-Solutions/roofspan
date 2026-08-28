"""Soft validation warnings for Roof Measurement.

Warnings never block field completion, verification, takeoff, or estimating.
"""
from __future__ import annotations


def build_warnings(measurement: dict) -> list[dict]:
    totals = measurement.get("totals") or {}
    structures = measurement.get("structures") or []
    facets = measurement.get("facets") or []
    edges = measurement.get("edges") or []
    warnings = []

    reported = totals.get("reported_area_sqft")
    entered = totals.get("total_area_sqft") or 0
    delta = totals.get("reported_area_delta_sqft")
    if reported not in (None, 0) and delta not in (None, 0):
        pct = abs(float(delta)) / float(reported) * 100 if reported else 0
        if abs(float(delta)) >= 1:
            warnings.append({
                "code": "REPORTED_AREA_MISMATCH", "severity": "warning",
                "message": f"Entered facet area differs from the reported area by {abs(float(delta)):.2f} sq ft ({pct:.1f}%).",
                "details": {"entered_area_sqft": entered, "reported_area_sqft": reported, "delta_sqft": delta},
            })

    valley_segments = [e for e in edges if e.get("edge_type") == "valley"]
    if valley_segments and float((totals.get("edge_totals") or {}).get("valley_lf") or 0) <= 0:
        warnings.append({
            "code": "VALLEY_LENGTH_MISSING", "severity": "warning",
            "message": "Valley segments are present but no valley length has been entered.",
        })

    active_facets = [f for f in facets if float(f.get("area_sqft") or 0) > 0]
    missing_pitch = [f.get("facet_label") or f.get("id") for f in active_facets if f.get("pitch_rise") is None]
    if missing_pitch:
        warnings.append({
            "code": "FACET_PITCH_MISSING", "severity": "warning",
            "message": f"{len(missing_pitch)} roof facet(s) with area are missing pitch.",
            "details": {"facets": missing_pitch},
        })

    zero_area = [f.get("facet_label") or f.get("id") for f in facets if float(f.get("area_sqft") or 0) <= 0]
    if zero_area:
        warnings.append({
            "code": "ZERO_AREA_FACET", "severity": "warning",
            "message": f"{len(zero_area)} facet(s) have zero roof area.", "details": {"facets": zero_area},
        })

    pitches = [float(f["pitch_rise"]) for f in active_facets if f.get("pitch_rise") is not None]
    if len(pitches) >= 4 and len(set(pitches)) == 1:
        warnings.append({
            "code": "UNIFORM_PITCH_SANITY", "severity": "info",
            "message": f"All {len(pitches)} measured facets use {pitches[0]:g}/12 pitch. Verify this is intentional.",
        })

    # Scope warnings are intentionally soft. They help Office catch an accidental exclusion without
    # preventing a field rep from saving an incomplete roof while work is still in progress.
    takeoff_area = totals.get("takeoff_area_sqft")
    if takeoff_area is not None and float(entered or 0) > 0 and float(takeoff_area or 0) <= 0:
        warnings.append({
            "code": "NO_TAKEOFF_SCOPE", "severity": "warning",
            "message": "Roof area is measured, but every measured structure is excluded from estimate/takeoff scope.",
        })

    facet_area_by_structure: dict[str, float] = {}
    for facet in active_facets:
        sid = facet.get("structure_id")
        if sid:
            key = str(sid)
            facet_area_by_structure[key] = facet_area_by_structure.get(key, 0.0) + float(facet.get("area_sqft") or 0)
    empty_included = []
    for structure in structures:
        if structure.get("included_in_scope", True) is False:
            continue
        sid = structure.get("id")
        if sid and facet_area_by_structure.get(str(sid), 0.0) <= 0:
            empty_included.append(structure.get("name") or structure.get("structure_type") or str(sid))
    if empty_included:
        warnings.append({
            "code": "INCLUDED_STRUCTURE_EMPTY", "severity": "warning",
            "message": "Included structure(s) have no measured roof area: " + ", ".join(empty_included) + ".",
            "details": {"structures": empty_included},
        })

    return warnings
