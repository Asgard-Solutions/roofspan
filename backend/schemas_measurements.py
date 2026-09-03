"""Roof Measurement schemas.

A revision is treated as a whole document: create/replace send the full nested payload. Children
cross-reference each other by a client-supplied `ref` (temporary key) so offline clients can build
the whole structure before the server assigns UUIDs. Totals are DERIVED server-side, never sent in.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


# ---------------- children (input) ----------------
class StructureIn(BaseModel):
    ref: Optional[str] = None                 # client temp key for facet linkage / editable-save lineage
    name: str = ""
    structure_type: str = "main_house"
    included_in_scope: bool = True
    stories: Optional[float] = None
    approx_height_ft: Optional[float] = None
    attachment: Optional[str] = None
    notes: Optional[str] = None
    sort: int = 0


class FacetIn(BaseModel):
    ref: Optional[str] = None                 # client temp key for edge/penetration linkage / lineage
    structure_ref: Optional[str] = None       # link to a StructureIn.ref
    structure_id: Optional[str] = None        # or an existing structure id (rare)
    facet_label: str = ""
    pitch_rise: Optional[float] = None
    area_sqft: float = 0
    width_ft: Optional[float] = None
    length_ft: Optional[float] = None
    position_offset_ft: Optional[float] = None   # pin a dormer/wing along the host slope (ft from start)
    orientation_azimuth: Optional[float] = None
    roof_material: Optional[str] = None
    notes: Optional[str] = None
    geometry: Optional[Dict[str, Any]] = None
    sort: int = 0


class EdgeIn(BaseModel):
    ref: Optional[str] = None                 # existing MeasurementEdge.id (identity-preserving save) or temp client key
    edge_type: str = "eave"
    length_ft: float = 0
    facet_ref: Optional[str] = None
    facet_ref_secondary: Optional[str] = None
    facet_id: Optional[str] = None
    facet_id_secondary: Optional[str] = None
    label: Optional[str] = None
    notes: Optional[str] = None
    sort: int = 0


class PenetrationIn(BaseModel):
    ref: Optional[str] = None                 # stable client key; existing rows use their server UUID
    pen_type: str = "pipe_boot"
    quantity: int = 1
    facet_ref: Optional[str] = None
    facet_id: Optional[str] = None
    diameter_in: Optional[float] = None
    width_in: Optional[float] = None
    length_in: Optional[float] = None
    notes: Optional[str] = None
    sort: int = 0


class SummaryIn(BaseModel):
    existing_covering_type: Optional[str] = None
    existing_condition: Optional[str] = None
    existing_layers: Optional[int] = None
    existing_underlayment: Optional[str] = None
    tearoff_notes: Optional[str] = None
    deck_type: Optional[str] = None
    deck_thickness_in: Optional[float] = None
    damaged_deck_sf: Optional[float] = None
    replacement_sheets: Optional[int] = None
    full_redeck: bool = False
    decking_notes: Optional[str] = None
    drip_edge_lf: Optional[float] = None
    ridge_vent_lf: Optional[float] = None
    intake_soffit_vent_lf: Optional[float] = None
    ventilation_notes: Optional[str] = None
    gutter_lf: Optional[float] = None
    gutter_size: Optional[str] = None
    gutter_type: Optional[str] = None
    downspout_count: Optional[int] = None
    downspout_lf: Optional[float] = None
    gutter_guard_lf: Optional[float] = None
    gutter_notes: Optional[str] = None
    stories: Optional[float] = None            # legacy fallback; structures are authoritative when present
    steep_access: bool = False
    high_access: bool = False
    long_carry: bool = False
    restricted_access: bool = False
    landscaping_protection: bool = False
    conditions_notes: Optional[str] = None


# ---------------- revision (input) ----------------
class MeasurementRevisionIn(BaseModel):
    inspection_id: Optional[str] = None
    property_id: Optional[str] = None
    lead_id: Optional[str] = None
    source: str = "field"
    provider: Optional[str] = None
    report_id: Optional[str] = None
    reported_area_sqft: Optional[float] = None
    notes: Optional[str] = None
    mark_field_complete: bool = False
    site_plan: Optional[Dict[str, Any]] = None    # combined multi-structure site-plan layout offsets
    structures: List[StructureIn] = []
    facets: List[FacetIn] = []
    edges: List[EdgeIn] = []
    penetrations: List[PenetrationIn] = []
    summary: Optional[SummaryIn] = None


class StatusChangeIn(BaseModel):
    to: str                                    # draft | field_complete | office_verified | locked


# ---------------- output ----------------
class StructureOut(BaseModel):
    id: str
    name: str
    structure_type: str
    included_in_scope: bool = True
    stories: Optional[float] = None
    approx_height_ft: Optional[float] = None
    attachment: Optional[str] = None
    notes: Optional[str] = None
    sort: int = 0


class FacetOut(BaseModel):
    id: str
    structure_id: Optional[str] = None
    facet_label: str
    pitch_rise: Optional[float] = None
    area_sqft: float
    width_ft: Optional[float] = None
    length_ft: Optional[float] = None
    position_offset_ft: Optional[float] = None
    orientation_azimuth: Optional[float] = None
    roof_material: Optional[str] = None
    notes: Optional[str] = None
    geometry: Optional[Dict[str, Any]] = None
    sort: int = 0


class EdgeOut(BaseModel):
    id: str
    edge_type: str
    length_ft: float
    facet_id: Optional[str] = None
    facet_id_secondary: Optional[str] = None
    label: Optional[str] = None
    notes: Optional[str] = None
    sort: int = 0


class PenetrationOut(BaseModel):
    id: str
    pen_type: str
    quantity: int
    facet_id: Optional[str] = None
    diameter_in: Optional[float] = None
    width_in: Optional[float] = None
    length_in: Optional[float] = None
    notes: Optional[str] = None
    sort: int = 0


class MeasurementTotals(BaseModel):
    # Physical measured totals (backward-compatible semantics).
    total_area_sqft: float = 0
    total_squares: float = 0
    facet_count: int = 0
    structure_count: int = 0
    predominant_pitch: Optional[float] = None
    area_by_pitch: List[Dict[str, Any]] = []
    area_by_structure: List[Dict[str, Any]] = []
    edge_totals: Dict[str, float] = {}
    penetration_counts: Dict[str, int] = {}
    penetration_total: int = 0

    # Estimate/takeoff scope. Excluded structures remain in the physical totals above.
    takeoff_area_sqft: float = 0
    takeoff_squares: float = 0
    takeoff_facet_count: int = 0
    takeoff_structure_count: int = 0
    takeoff_predominant_pitch: Optional[float] = None
    takeoff_area_by_pitch: List[Dict[str, Any]] = []
    takeoff_edge_totals: Dict[str, float] = {}
    takeoff_penetration_counts: Dict[str, int] = {}
    takeoff_penetration_total: int = 0
    max_stories: Optional[float] = None
    max_height_ft: Optional[float] = None

    reported_area_sqft: Optional[float] = None
    reported_area_delta_sqft: Optional[float] = None


class MeasurementRevisionOut(BaseModel):
    id: str
    set_id: str
    revision_number: int
    status: str
    supersedes_revision_id: Optional[str] = None
    is_immutable: bool = False
    editable: bool = False
    source: str
    provider: Optional[str] = None
    report_id: Optional[str] = None
    imported_at: Optional[datetime] = None
    reported_area_sqft: Optional[float] = None
    notes: Optional[str] = None
    inspection_id: Optional[str] = None
    property_id: Optional[str] = None
    lead_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    field_complete_by: Optional[str] = None
    field_complete_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    locked_by: Optional[str] = None
    locked_at: Optional[datetime] = None
    site_plan: Optional[Dict[str, Any]] = None
    structures: List[StructureOut] = []
    facets: List[FacetOut] = []
    edges: List[EdgeOut] = []
    penetrations: List[PenetrationOut] = []
    summary: Optional[SummaryIn] = None
    totals: MeasurementTotals = MeasurementTotals()


class MeasurementRevisionListItem(BaseModel):
    id: str
    set_id: str
    revision_number: int
    status: str
    source: str
    is_immutable: bool = False
    total_area_sqft: float = 0
    total_squares: float = 0
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    supersedes_revision_id: Optional[str] = None
