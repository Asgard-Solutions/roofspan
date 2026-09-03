// Pure, Node-testable measurement payload builders for the Office worksheet.
//
// The Office manual worksheet only edits a subset of the Measurement Revision contract. Everything else
// (top-level report metadata, Roof Plane orientation/geometry, hidden summary fields) is system/technical
// data the worksheet must NEVER author from a stale form. `buildRebasePayload` implements the "Keep My
// Version" rule: rebase onto the newer authoritative server revision, let ONLY Office-editable values win,
// and preserve every non-editable value from the latest server copy — matched by stable id/ref.

export const num = (value) =>
  value === "" || value == null ? null : (Number.isFinite(Number(value)) ? Number(value) : null);

// Summary keys the Office manual form actually exposes as inputs (see the summary card JSX). Every other
// summary key (tearoff_notes, decking_notes, ventilation_notes, gutter_notes, stories, and any future
// non-editable key) is hidden/system and is preserved from the server copy during a conflict rebase.
export const EDITABLE_SUMMARY_KEYS = [
  "existing_covering_type", "existing_condition", "existing_underlayment", "existing_layers",
  "deck_type", "deck_thickness_in", "damaged_deck_sf", "replacement_sheets", "full_redeck",
  "drip_edge_lf", "ridge_vent_lf", "intake_soffit_vent_lf",
  "gutter_lf", "gutter_size", "gutter_type", "downspout_count", "downspout_lf", "gutter_guard_lf",
  "steep_access", "high_access", "long_carry", "restricted_access", "landscaping_protection",
  "conditions_notes",
];

// Facet fields the Office form does NOT edit — audited against the FacetIn/FacetOut contract. These are
// preserved from the matching server plane during a rebase.
export const HIDDEN_FACET_FIELDS = ["orientation_azimuth", "geometry"];

export const pick = (obj, keys) => {
  const out = {};
  keys.forEach((k) => { if (obj && obj[k] !== undefined) out[k] = obj[k]; });
  return out;
};

// Whole-document payload built from the local editable form. `base` supplies the hidden/system top-level
// metadata (source/provider/report_id/notes) the Office user does not edit. Correct for a normal save.
export function buildEditablePayload(ed, base, scope = {}) {
  return {
    lead_id: scope.leadId || null, property_id: scope.propertyId || null, inspection_id: scope.inspectionId || null,
    source: base?.source || "office", reported_area_sqft: num(ed.reported_area_sqft),
    provider: base?.provider ?? null, report_id: base?.report_id ?? null, notes: base?.notes ?? null,
    site_plan: ed.site_plan ?? null,
    structures: ed.structures.map((row, i) => ({
      ref: row.ref, name: row.name || "", structure_type: row.structure_type || "main_house",
      included_in_scope: row.included_in_scope !== false, stories: num(row.stories), approx_height_ft: num(row.approx_height_ft),
      attachment: row.attachment || null, notes: row.notes || null, sort: i,
    })),
    facets: ed.facets.map((row, i) => ({
      ref: row.ref, structure_ref: row.structure_ref || null, facet_label: row.facet_label || `F${i + 1}`,
      pitch_rise: num(row.pitch_rise), area_sqft: parseFloat(row.area_sqft) || 0,
      width_ft: num(row.width_ft), length_ft: num(row.length_ft), position_offset_ft: num(row.position_offset_ft),
      orientation_azimuth: num(row.orientation_azimuth),
      roof_material: row.roof_material || null, notes: row.notes || null, geometry: row.geometry || null, sort: i,
    })),
    edges: ed.edges.map((row, i) => ({
      ref: row.ref || row.id || row._k, edge_type: row.edge_type, length_ft: parseFloat(row.length_ft) || 0, facet_ref: row.facet_ref || null,
      facet_ref_secondary: row.facet_ref_secondary || null, label: row.label || null, notes: row.notes || null, sort: i,
    })),
    penetrations: ed.penetrations.map((row, i) => ({
      ref: row.ref || row.id || row._k, pen_type: row.pen_type, quantity: parseInt(row.quantity, 10) || 1, facet_ref: row.facet_ref || null,
      width_in: num(row.width_in), length_in: num(row.length_in), diameter_in: num(row.diameter_in), notes: row.notes || null, sort: i,
    })),
    summary: ed.summary || {},
  };
}

// "Keep My Version" conflict rebase: start from the NEWER authoritative server revision (`server`) and let
// ONLY Office-editable measurement values win. Everything the manual form does not own keeps its latest
// server value, so a stale local form can never revert hidden/system data.
//   • top-level report/system metadata (source/provider/report_id/reported_area_sqft/notes) ← server
//   • Roof Plane technical fields (HIDDEN_FACET_FIELDS) ← matching server plane, matched by stable id/ref
//   • hidden summary keys (everything outside EDITABLE_SUMMARY_KEYS) ← server summary
//   • locally-created planes (no matching server id) have no server technical data to preserve — kept as-is
export function buildRebasePayload(ed, server, scope = {}) {
  const p = buildEditablePayload(ed, server, scope);   // editable content from the form + server top-level metadata
  p.reported_area_sqft = server?.reported_area_sqft ?? null;   // report metadata: latest server wins
  p.summary = { ...(server?.summary || {}), ...pick(ed.summary || {}, EDITABLE_SUMMARY_KEYS) };
  const serverFacet = {};
  (server?.facets || []).forEach((f) => { serverFacet[String(f.id)] = f; });
  p.facets = p.facets.map((f) => {
    const s = serverFacet[String(f.ref)];                // stable identity match — never fuzzy by area/pitch/label
    if (!s) return f;                                    // locally-created plane: nothing on the server to preserve
    const preserved = {};
    HIDDEN_FACET_FIELDS.forEach((k) => { preserved[k] = s[k] ?? null; });
    return { ...f, ...preserved };                       // editable fields from the form; technical fields from server
  });
  return p;
}
