"""Pure roof-measurement derivation helpers.

This module deliberately has no database dependencies. Physical measured totals and takeoff-scoped
totals are derived side-by-side so excluding a structure from pricing never erases what was measured.
"""
from __future__ import annotations

EDGE_KEYS = ["eave", "rake", "ridge", "hip", "valley", "sidewall", "headwall", "transition"]


def _get(row, name, default=None):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _sid(value):
    return str(value) if value is not None else None


def _num(value, default=0.0):
    if value in (None, ""):
        return float(default)
    return float(value)


def _pitch_rows(facets):
    pitch_areas = {}
    for facet in facets:
        pitch = _get(facet, "pitch_rise")
        pitch_areas[pitch] = pitch_areas.get(pitch, 0.0) + _num(_get(facet, "area_sqft"))
    return [
        {"pitch": pitch, "area_sqft": round(area, 2), "squares": round(area / 100.0, 2)}
        for pitch, area in sorted(pitch_areas.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))
    ]


def _edge_totals(edges):
    totals = {f"{key}_lf": 0.0 for key in EDGE_KEYS}
    for edge in edges:
        key = f"{_get(edge, 'edge_type', 'eave')}_lf"
        if key in totals:
            totals[key] += _num(_get(edge, "length_ft"))
    return {key: round(value, 2) for key, value in totals.items()}


def _penetration_totals(penetrations):
    counts = {}
    total = 0
    for pen in penetrations:
        kind = _get(pen, "pen_type", "pipe_boot")
        qty = int(_get(pen, "quantity", 0) or 0)
        counts[kind] = counts.get(kind, 0) + qty
        total += qty
    return counts, total


def derive_measurement_totals(structures, facets, edges, penetrations):
    structures = list(structures or [])
    facets = list(facets or [])
    edges = list(edges or [])
    penetrations = list(penetrations or [])

    structure_by_id = {_sid(_get(row, "id")): row for row in structures}
    included_structure_ids = {
        sid for sid, row in structure_by_id.items()
        if _get(row, "included_in_scope", True) is not False
    }
    facet_by_id = {_sid(_get(row, "id")): row for row in facets}

    def facet_in_scope(facet):
        structure_id = _sid(_get(facet, "structure_id"))
        return structure_id is None or structure_id in included_structure_ids

    scoped_facets = [facet for facet in facets if facet_in_scope(facet)]
    scoped_facet_ids = {_sid(_get(facet, "id")) for facet in scoped_facets if _get(facet, "id") is not None}

    def edge_in_scope(edge):
        linked = [
            _sid(_get(edge, "facet_id")),
            _sid(_get(edge, "facet_id_secondary")),
        ]
        linked = [fid for fid in linked if fid is not None]
        if not linked:
            return True
        return any(fid in scoped_facet_ids for fid in linked)

    def penetration_in_scope(pen):
        fid = _sid(_get(pen, "facet_id"))
        return fid is None or fid in scoped_facet_ids

    scoped_edges = [edge for edge in edges if edge_in_scope(edge)]
    scoped_pens = [pen for pen in penetrations if penetration_in_scope(pen)]

    total_area = round(sum(_num(_get(facet, "area_sqft")) for facet in facets), 2)
    takeoff_area = round(sum(_num(_get(facet, "area_sqft")) for facet in scoped_facets), 2)

    area_by_structure = []
    buckets = {}
    for facet in facets:
        structure_id = _sid(_get(facet, "structure_id"))
        buckets[structure_id] = buckets.get(structure_id, 0.0) + _num(_get(facet, "area_sqft"))
    for structure_id, area in buckets.items():
        structure = structure_by_id.get(structure_id)
        included = structure_id is None or structure_id in included_structure_ids
        area_by_structure.append({
            "structure_id": structure_id,
            "name": (_get(structure, "name") or _get(structure, "structure_type")) if structure else "Unassigned",
            "area_sqft": round(area, 2),
            "squares": round(area / 100.0, 2),
            "included_in_scope": included,
        })

    area_by_pitch = _pitch_rows(facets)
    takeoff_area_by_pitch = _pitch_rows(scoped_facets)
    predominant_pitch = None
    if area_by_pitch:
        predominant_pitch = max(area_by_pitch, key=lambda row: row["area_sqft"])["pitch"]
    takeoff_predominant_pitch = None
    if takeoff_area_by_pitch:
        takeoff_predominant_pitch = max(takeoff_area_by_pitch, key=lambda row: row["area_sqft"])["pitch"]

    pen_counts, pen_total = _penetration_totals(penetrations)
    scoped_pen_counts, scoped_pen_total = _penetration_totals(scoped_pens)

    included_structures = [
        row for row in structures
        if _sid(_get(row, "id")) in included_structure_ids
    ]
    story_values = [_num(_get(row, "stories")) for row in included_structures if _get(row, "stories") not in (None, "")]
    height_values = [_num(_get(row, "approx_height_ft")) for row in included_structures if _get(row, "approx_height_ft") not in (None, "")]

    return {
        "total_area_sqft": total_area,
        "total_squares": round(total_area / 100.0, 2),
        "takeoff_area_sqft": takeoff_area,
        "takeoff_squares": round(takeoff_area / 100.0, 2),
        "facet_count": len(facets),
        "structure_count": len(structures),
        "takeoff_facet_count": len(scoped_facets),
        "takeoff_structure_count": sum(1 for row in structures if _sid(_get(row, "id")) in included_structure_ids),
        "predominant_pitch": predominant_pitch,
        "takeoff_predominant_pitch": takeoff_predominant_pitch,
        "area_by_pitch": area_by_pitch,
        "takeoff_area_by_pitch": takeoff_area_by_pitch,
        "area_by_structure": area_by_structure,
        "edge_totals": _edge_totals(edges),
        "takeoff_edge_totals": _edge_totals(scoped_edges),
        "penetration_counts": pen_counts,
        "penetration_total": pen_total,
        "takeoff_penetration_counts": scoped_pen_counts,
        "takeoff_penetration_total": scoped_pen_total,
        "max_stories": round(max(story_values), 2) if story_values else None,
        "max_height_ft": round(max(height_values), 2) if height_values else None,
    }
