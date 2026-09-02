"use strict";
// Measurements -> Proposed Roof Sketch: FIRST real geometry generation (Phase 2).
//
// Intentionally limited to the two roof configurations that can be solved SAFELY and DETERMINISTICALLY
// from the current measurements:
//   1. a single simple roof plane (rectangle) adequately constrained by Width x Length
//   2. a simple two-plane gable (two rectangles sharing one Ridge; adjacency from the Ridge roof line's
//      Primary/Secondary Roof Plane relationship)
//
// Semantics (confirmed by the audit): a Roof Plane's area_sqft == width_ft * length_ft (the plane's own
// SURFACE rectangle as measured — NOT pitch-adjusted). So the flat surface rectangles are laid out
// directly from Width/Length; pitch is carried as an attribute (it is not needed to place a flat plane).
//
// HARD RULES:
//   - Deterministic geometry, never AI/random. Identical input -> identical layout (up to an irrelevant
//     whole-roof rotation/reflection, which is explicitly acceptable).
//   - Returns a COMPLETED sketch ONLY when the measurements mathematically support it; otherwise returns
//     the (no-XY) foundation candidate + diagnostics with status "needs_review".
//   - Real-world scale (feetPerUnit = 1; vertices in feet) established from the measured dimensions.
//   - Generated facet -> Measurement Roof Plane and generated edge -> Measurement Roof Line links are
//     carried by RELATIONAL id (never fuzzy). Measured edge lengths remain the confirmed reference and
//     are NEVER written back onto the measurements.
//   - Compass orientation is NOT invented. If two materially different layouts satisfy the same numbers,
//     it returns Needs Review rather than picking one.
//   - Penetrations keep no fabricated position (carried from the foundation with position_known:false).
//   - Never saves / queues / mutates measurements / replaces a sketch / calls the network.
const { generateProposedSketch, AREA_DIM_TOL } = require("./generateSketch");
const { createSketchDocument } = require("./schema");
const { validateSketch } = require("./topology");

const LEN_TOL = 0.5; // ft tolerance for confirmed-edge vs drawn-side and ridge-match consistency

const num = (v) => {
  if (v === "" || v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
const approx = (a, b, tol) => a != null && b != null && Math.abs(Number(a) - Number(b)) <= tol;
const bySortThenId = (a, b) => {
  const sa = Number(a && a.sort), sb = Number(b && b.sort);
  const na = Number.isFinite(sa) ? sa : 0, nb = Number.isFinite(sb) ? sb : 0;
  if (na !== nb) return na - nb;
  return String((a && a.id) ?? "").localeCompare(String((b && b.id) ?? ""));
};
const SIMPLE_EDGE_TYPES = new Set(["eave", "rake", "ridge"]);

// A needs-review result keeps the foundation's no-XY candidate + adds the blocking diagnostics.
function _needsReview(base, diags) {
  const diagnostics = base.diagnostics
    .filter((d) => d.code !== "geometry_deferred" && d.code !== "geometry_deferred_complex")
    .concat(diags);
  return {
    ...base,
    ok: false,
    status: "needs_review",
    confidence: "none",
    geometry_status: "needs_review",
    diagnostics,
    unresolved: diagnostics.filter((d) => d.severity === "error"),
  };
}

function _success(base, doc, mappings, extraDiags) {
  const diagnostics = base.diagnostics
    .filter((d) => d.code !== "geometry_deferred" && d.code !== "geometry_deferred_complex")
    .concat(extraDiags || []);
  return {
    ...base,
    ok: true,
    status: "generated",
    confidence: "high",
    geometry_status: "generated",
    document: doc,
    mappings,
    diagnostics,
    unresolved: [],
  };
}

// Measurement roof lines that belong to a plane (excluding a given shared edge id), sorted stably.
function _planeLines(edgesIn, planeMid, excludeMid) {
  return edgesIn
    .filter((e) => e && e.id != null && String(e.id) !== String(excludeMid))
    .filter((e) => String(e.facet_id) === String(planeMid) || String(e.facet_id_secondary) === String(planeMid))
    .slice()
    .sort(bySortThenId);
}

// Assign a plane's measurement lines to the drawn sides by CLASSIFICATION + a fixed order (deterministic;
// this is role/order assignment, NOT fuzzy value matching). Returns { assigned:{slot->line}, error }.
// longSlots receive eave/ridge lines; crossSlots receive rake lines. Unknown types or overflow -> error.
function _assignLines(lines, longSlots, crossSlots) {
  const longLines = lines.filter((l) => l.edge_type === "eave" || l.edge_type === "ridge");
  const crossLines = lines.filter((l) => l.edge_type === "rake");
  const unknown = lines.filter((l) => !SIMPLE_EDGE_TYPES.has(l.edge_type));
  if (unknown.length) {
    return { error: { severity: "error", code: "unsupported_edge_type_for_simple_roof", target_type: "edge",
      target_id: String(unknown[0].id), message: `Roof line type '${unknown[0].edge_type}' is not part of a simple single-plane or gable roof.` } };
  }
  if (longLines.length > longSlots.length) {
    return { error: { severity: "error", code: "ambiguous_roof_lines", target_type: "facet", target_id: null,
      message: "More eave/ridge roof lines than the rectangle can place; layout is ambiguous." } };
  }
  if (crossLines.length > crossSlots.length) {
    return { error: { severity: "error", code: "ambiguous_roof_lines", target_type: "facet", target_id: null,
      message: "More rake roof lines than the rectangle can place; layout is ambiguous." } };
  }
  const assigned = {};
  longLines.forEach((l, i) => { assigned[longSlots[i]] = l; });
  crossLines.forEach((l, i) => { assigned[crossSlots[i]] = l; });
  return { assigned, error: null };
}

// Build one drawn edge (mapped to a measurement roof line, or a derived boundary edge with no line).
function _edge(id, v1, v2, drawnType, drawnLenFt, line) {
  if (line) {
    return {
      id: `mse_${line.id}`, measurement_edge_id: String(line.id), relational_edge_id: String(line.id),
      v1, v2, type: line.edge_type, confirmed_length_ft: num(line.length_ft),
      locked: num(line.length_ft) != null, drawn_length_ft: drawnLenFt,
    };
  }
  return { id, v1, v2, type: drawnType, confirmed_length_ft: null, locked: false, drawn_length_ft: drawnLenFt };
}

// ---- single simple plane (rectangle from Width x Length) ------------------------------------------
function _layoutSinglePlane(base, facetsIn, edgesIn) {
  const f = facetsIn[0];
  const mid = String(f.id);
  const W = num(f.width_ft), L = num(f.length_ft), A = num(f.area_sqft);
  if (W == null || !(W > 0) || L == null || !(L > 0)) {
    return _needsReview(base, [{ severity: "error", code: "insufficient_dimensions", target_type: "facet", target_id: mid,
      message: "Roof plane needs both Width and Length to lay out its boundary." }]);
  }
  if (A != null && Math.abs(W * L - A) > AREA_DIM_TOL) {
    return _needsReview(base, [{ severity: "error", code: "contradictory_dimensions", target_type: "facet", target_id: mid,
      message: "Roof plane area does not equal Width x Length; dimensions are contradictory." }]);
  }
  const lines = _planeLines(edgesIn, mid, null);
  // slots: bottom/top are the L-length sides; left/right are the W-length sides.
  const { assigned, error } = _assignLines(lines, ["bottom", "top"], ["left", "right"]);
  if (error) return _needsReview(base, [error]);

  // consistency: a mapped eave/ridge (long side) must equal L; a mapped rake (cross side) must equal W.
  for (const slot of ["bottom", "top"]) {
    const l = assigned[slot];
    if (l && num(l.length_ft) != null && !approx(num(l.length_ft), L, LEN_TOL)) {
      return _needsReview(base, [{ severity: "error", code: "contradictory_dimensions", target_type: "edge", target_id: String(l.id),
        message: "Measured eave/ridge length does not match the plane Length." }]);
    }
  }
  for (const slot of ["left", "right"]) {
    const l = assigned[slot];
    if (l && num(l.length_ft) != null && !approx(num(l.length_ft), W, LEN_TOL)) {
      return _needsReview(base, [{ severity: "error", code: "contradictory_dimensions", target_type: "edge", target_id: String(l.id),
        message: "Measured rake length does not match the plane Width." }]);
    }
  }

  const doc = createSketchDocument({ structureId: base.structure_id });
  doc.scale = { resolved: true, feetPerUnit: 1, feet_per_unit: 1, method: "measurement_dimensions" };
  const v0 = { id: "gv_0", x: 0, y: 0 }, v1 = { id: "gv_1", x: L, y: 0 };
  const v2 = { id: "gv_2", x: L, y: W }, v3 = { id: "gv_3", x: 0, y: W };
  doc.vertices = [v0, v1, v2, v3];
  const eBottom = _edge("gen_e_bottom", v0.id, v1.id, "eave", L, assigned.bottom);
  const eRight = _edge("gen_e_right", v1.id, v2.id, "rake", W, assigned.right);
  const eTop = _edge("gen_e_top", v2.id, v3.id, "eave", L, assigned.top);
  const eLeft = _edge("gen_e_left", v3.id, v0.id, "rake", W, assigned.left);
  doc.edges = [eBottom, eRight, eTop, eLeft];
  doc.facets = [{
    id: `msf_${mid}`, measurement_facet_id: mid, relational_facet_id: mid,
    label: f.facet_label || "F1", pitch_rise: num(f.pitch_rise), confirmed_area_sqft: A,
    orientation_azimuth: num(f.orientation_azimuth), roof_material: f.roof_material || null,
    edgeIds: [eBottom.id, eRight.id, eTop.id, eLeft.id], vertexIds: [],
  }];
  doc.penetrations = base.document.penetrations; // no fabricated position
  doc.generated = base.document.generated;
  return _finalize(base, doc);
}

// ---- simple gable (two rectangles sharing one Ridge) ----------------------------------------------
function _layoutGable(base, facetsIn, edgesIn) {
  const adj = base.constraints.adjacency.filter((a) => a.edge_type === "ridge");
  if (adj.length !== 1) {
    return _needsReview(base, [{ severity: "error", code: "missing_ridge_relationship", target_type: "structure", target_id: base.structure_id,
      message: "A simple gable needs exactly one shared Ridge roof line linking the two roof planes (Primary/Secondary)." }]);
  }
  const ridgeMid = adj[0].measurement_edge_id;
  const ridgeLine = edgesIn.find((e) => String(e.id) === String(ridgeMid));
  const R = ridgeLine ? num(ridgeLine.length_ft) : null;
  if (R == null || !(R > 0)) {
    return _needsReview(base, [{ severity: "error", code: "insufficient_dimensions", target_type: "edge", target_id: String(ridgeMid),
      message: "The shared Ridge roof line needs a positive length to lay out the gable." }]);
  }
  const [pAmid, pBmid] = adj[0].facets.map(String);
  const facetByMid = {};
  facetsIn.forEach((f) => { facetByMid[String(f.id)] = f; });

  // For each plane: one dimension must match the ridge (ridge-parallel); the other is the plane depth.
  function planeDepth(mid) {
    const f = facetByMid[mid];
    const W = num(f.width_ft), L = num(f.length_ft), A = num(f.area_sqft);
    if (W == null || !(W > 0) || L == null || !(L > 0)) {
      return { error: { severity: "error", code: "insufficient_dimensions", target_type: "facet", target_id: mid,
        message: "Each gable plane needs both Width and Length." } };
    }
    if (A != null && Math.abs(W * L - A) > AREA_DIM_TOL) {
      return { error: { severity: "error", code: "contradictory_dimensions", target_type: "facet", target_id: mid,
        message: "Gable plane area does not equal Width x Length; dimensions are contradictory." } };
    }
    const wMatch = approx(W, R, LEN_TOL), lMatch = approx(L, R, LEN_TOL);
    if (!wMatch && !lMatch) {
      return { error: { severity: "error", code: "contradictory_dimensions", target_type: "facet", target_id: mid,
        message: "Neither plane dimension matches the shared Ridge length; the gable cannot be laid out." } };
    }
    // both match => square-ish; depth = W deterministically (shape is identical either way).
    const depth = wMatch && !lMatch ? L : (lMatch && !wMatch ? W : W);
    return { depth };
  }
  const dA = planeDepth(pAmid); if (dA.error) return _needsReview(base, [dA.error]);
  const dB = planeDepth(pBmid); if (dB.error) return _needsReview(base, [dB.error]);

  // measurement lines per plane, excluding the shared ridge
  const linesA = _planeLines(edgesIn, pAmid, ridgeMid);
  const linesB = _planeLines(edgesIn, pBmid, ridgeMid);
  const asgA = _assignLines(linesA, ["eaveA"], ["rakeAL", "rakeAR"]); if (asgA.error) return _needsReview(base, [asgA.error]);
  const asgB = _assignLines(linesB, ["eaveB"], ["rakeBL", "rakeBR"]); if (asgB.error) return _needsReview(base, [asgB.error]);

  // consistency: a mapped eave equals R (ridge-parallel); a mapped rake equals that plane's depth.
  const consErr = _gableConsistency(asgA.assigned, R, dA.depth) || _gableConsistency(asgB.assigned, R, dB.depth);
  if (consErr) return _needsReview(base, [consErr]);

  const doc = createSketchDocument({ structureId: base.structure_id });
  doc.scale = { resolved: true, feetPerUnit: 1, feet_per_unit: 1, method: "measurement_dimensions" };
  const rA = { id: "gv_rA", x: 0, y: 0 }, rB = { id: "gv_rB", x: R, y: 0 };
  const aL = { id: "gv_aL", x: 0, y: dA.depth }, aR = { id: "gv_aR", x: R, y: dA.depth };
  const bL = { id: "gv_bL", x: 0, y: -dB.depth }, bR = { id: "gv_bR", x: R, y: -dB.depth };
  doc.vertices = [rA, rB, aL, aR, bL, bR];

  const ridge = _edge("gen_e_ridge", rA.id, rB.id, "ridge", R, ridgeLine);
  const rakeAR = _edge("gen_e_rakeAR", rB.id, aR.id, "rake", dA.depth, asgA.assigned.rakeAR);
  const eaveA = _edge("gen_e_eaveA", aR.id, aL.id, "eave", R, asgA.assigned.eaveA);
  const rakeAL = _edge("gen_e_rakeAL", aL.id, rA.id, "rake", dA.depth, asgA.assigned.rakeAL);
  const rakeBR = _edge("gen_e_rakeBR", rB.id, bR.id, "rake", dB.depth, asgB.assigned.rakeBR);
  const eaveB = _edge("gen_e_eaveB", bR.id, bL.id, "eave", R, asgB.assigned.eaveB);
  const rakeBL = _edge("gen_e_rakeBL", bL.id, rA.id, "rake", dB.depth, asgB.assigned.rakeBL);
  doc.edges = [ridge, rakeAR, eaveA, rakeAL, rakeBR, eaveB, rakeBL];

  doc.facets = [
    _gableFacet(facetByMid[pAmid], pAmid, [ridge.id, rakeAR.id, eaveA.id, rakeAL.id]),
    _gableFacet(facetByMid[pBmid], pBmid, [ridge.id, rakeBR.id, eaveB.id, rakeBL.id]),
  ];
  doc.penetrations = base.document.penetrations;
  doc.generated = base.document.generated;
  return _finalize(base, doc);
}

function _gableConsistency(assigned, R, depth) {
  if (assigned.eaveA && num(assigned.eaveA.length_ft) != null && !approx(num(assigned.eaveA.length_ft), R, LEN_TOL)) {
    return { severity: "error", code: "contradictory_dimensions", target_type: "edge", target_id: String(assigned.eaveA.id), message: "Measured eave length does not match the ridge length." };
  }
  if (assigned.eaveB && num(assigned.eaveB.length_ft) != null && !approx(num(assigned.eaveB.length_ft), R, LEN_TOL)) {
    return { severity: "error", code: "contradictory_dimensions", target_type: "edge", target_id: String(assigned.eaveB.id), message: "Measured eave length does not match the ridge length." };
  }
  for (const k of ["rakeAL", "rakeAR", "rakeBL", "rakeBR"]) {
    const l = assigned[k];
    if (l && num(l.length_ft) != null && !approx(num(l.length_ft), depth, LEN_TOL)) {
      return { severity: "error", code: "contradictory_dimensions", target_type: "edge", target_id: String(l.id), message: "Measured rake length does not match the plane depth." };
    }
  }
  return null;
}

function _gableFacet(f, mid, edgeIds) {
  return {
    id: `msf_${mid}`, measurement_facet_id: mid, relational_facet_id: mid,
    label: f.facet_label || `F`, pitch_rise: num(f.pitch_rise), confirmed_area_sqft: num(f.area_sqft),
    orientation_azimuth: num(f.orientation_azimuth), roof_material: f.roof_material || null,
    edgeIds, vertexIds: [],
  };
}

// Validate the completed geometry with the canonical validator (never emit an invalid sketch) and
// rebuild the id mappings from the drawn document.
function _finalize(base, doc) {
  const v = validateSketch(doc);
  if (!v.valid) {
    return _needsReview(base, [{ severity: "error", code: "generated_geometry_invalid", target_type: "structure", target_id: base.structure_id,
      message: "Generated geometry failed canonical validation: " + (v.errors[0] && v.errors[0].code) }]);
  }
  const mappings = {
    facets: doc.facets.map((f) => ({ sketch_facet_id: f.id, measurement_facet_id: f.measurement_facet_id })),
    edges: doc.edges.filter((e) => e.measurement_edge_id != null)
      .map((e) => ({ sketch_edge_id: e.id, measurement_edge_id: e.measurement_edge_id })),
    penetrations: (doc.penetrations || []).map((p) => ({ sketch_penetration_id: p.id, measurement_penetration_id: p.measurement_penetration_id, position_known: false })),
  };
  return _success(base, doc, mappings, []);
}

// Public entry: constraint foundation + deterministic geometry for the two supported roof types.
function generateSketchGeometry(input) {
  const base = generateProposedSketch(input);
  if (base.status !== "generated") {
    return { ...base, geometry_status: "not_attempted" };
  }
  const facetsIn = (Array.isArray(input && input.facets) ? input.facets : [])
    .filter((f) => f && f.id != null && (base.structure_id == null || String(f.structure_id) === String(base.structure_id)))
    .slice().sort(bySortThenId);
  const edgesIn = (Array.isArray(input && input.edges) ? input.edges : []).filter((e) => e && e.id != null);

  if (base.archetype === "single_plane") return _layoutSinglePlane(base, facetsIn, edgesIn);
  if (base.archetype === "symmetric_gable") return _layoutGable(base, facetsIn, edgesIn);
  // >2 planes / no clean shared ridge / unknown -> not a safely solvable simple roof this phase.
  return _needsReview(base, [{ severity: "error", code: "unsupported_roof_topology", target_type: "structure", target_id: base.structure_id,
    message: "Only a single simple plane or a simple two-plane gable can be generated at high confidence in this phase." }]);
}

module.exports = { generateSketchGeometry, LEN_TOL };
