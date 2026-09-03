"use strict";
// Measurements -> Proposed Roof Sketch: FIRST real geometry generation (Phase 2).
//
// Intentionally limited to the two roof configurations that can be solved SAFELY and DETERMINISTICALLY
// from the current measurements:
//   1. a single simple roof plane (rectangle) adequately constrained by Width x Length
//   2. a simple two-plane gable (two rectangles sharing one Ridge; adjacency from the Ridge roof line's
//      Primary/Secondary Roof Plane relationship)
//
// LOCKED dimensional semantics (see PRD "DIMENSIONAL SEMANTICS CORRECTION"):
//   - length_ft = the ridge/eave-PARALLEL plan dimension. Used directly for plan-view X. For a gable it
//     MUST match the shared Ridge length (no Width/Length axis swapping is permitted).
//   - width_ft  = the SLOPED eave->ridge distance. It is deprojected to the horizontal plan run via
//     planRunFromSlope(width_ft, pitch_rise) before being used as plan-view Y (never used raw as depth).
//   - area_sqft = the sloped SURFACE area (~= width_ft * length_ft). It is preserved as a confirmed
//     attribute and NEVER rewritten; an Area override (area_sqft != width*length) does not block layout.
//   Pitch is required to deproject the sloped Width; a missing pitch is Needs Review, never assumed.
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
const { planRunFromSlope } = require("./geometry");
const { planPlacement, layoutFromResolutions } = require("./resolvePlacement");

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

const _INSUFFICIENT_CODES = new Set(["missing_structure", "no_roof_planes", "missing_pitch", "missing_area", "insufficient_dimensions"]);
function _classifyReadiness(diagnostics) {
  const errs = diagnostics.filter((d) => d.severity === "error");
  if (errs.length > 0 && errs.every((d) => _INSUFFICIENT_CODES.has(d.code))) return "insufficient_information";
  return "needs_review";
}
function _allPlaneIds(base) { return base.constraints.planes.map((p) => String(p.measurement_facet_id)); }

// Material-ambiguity records that name the ACTUAL measurement Roof Plane(s) + Roof Line involved.
function _ambiguityRecords(base, planeIds) {
  const labelBy = {}; base.constraints.planes.forEach((p) => { labelBy[String(p.measurement_facet_id)] = p.label || String(p.measurement_facet_id); });
  const set = planeIds ? new Set(planeIds.map(String)) : null;
  const out = [];
  base.constraints.adjacency.forEach((a) => {
    const [p0, p1] = a.facets.map(String);
    if (set && !(set.has(p0) && set.has(p1))) return;
    const t = a.edge_type;
    if (t === "valley" || t === "dead_valley" || t === "hip") {
      const title = t === "dead_valley" ? "Dead Valley" : t.charAt(0).toUpperCase() + t.slice(1);
      out.push({ code: "plane_side_ambiguous", plane: p1, related_plane: p0, via_edge: String(a.measurement_edge_id), via_type: t,
        message: `${labelBy[p1] || p1} placement needs review — measurements establish a ${title} with ${labelBy[p0] || p0} but do not uniquely establish which side of ${labelBy[p0] || p0}.` });
    }
  });
  return out;
}

// A needs-review result keeps the foundation's no-XY candidate + adds the blocking diagnostics.
function _needsReview(base, diags, graph, opts) {
  opts = opts || {};
  const diagnostics = base.diagnostics
    .filter((d) => d.code !== "geometry_deferred" && d.code !== "geometry_deferred_complex")
    .concat(diags);
  return {
    ...base,
    ok: false,
    status: "needs_review",
    confidence: "none",
    geometry_status: "needs_review",
    readiness: opts.readiness || _classifyReadiness(diagnostics),
    partial: false,
    document: base.document,
    diagnostics,
    unresolved: diagnostics.filter((d) => d.severity === "error"),
    resolved_planes: [],
    unresolved_planes: opts.unresolvedPlanes || _allPlaneIds(base),
    unresolved_lines: opts.unresolvedLines || [],
    ambiguities: opts.ambiguities || [],
    ...(graph ? { graph } : {}),
  };
}

function _success(base, doc, mappings, extraDiags, graph) {
  const diagnostics = base.diagnostics
    .filter((d) => d.code !== "geometry_deferred" && d.code !== "geometry_deferred_complex")
    .concat(extraDiags || []);
  return {
    ...base,
    ok: true,
    status: "generated",
    confidence: "high",
    geometry_status: "generated",
    readiness: "high_confidence",
    partial: false,
    document: doc,
    mappings,
    diagnostics,
    unresolved: [],
    resolved_planes: doc.facets.map((f) => f.measurement_facet_id),
    unresolved_planes: [],
    unresolved_lines: [],
    ambiguities: [],
    ...(graph ? { graph } : {}),
  };
}

// A PARTIAL proposal: a safe connected section is drawn; the rest is explicitly unresolved.
function _partial(base, doc, opts) {
  opts = opts || {};
  const v = validateSketch(doc);
  if (!v.valid) {
    return _needsReview(base, [{ severity: "error", code: "generated_geometry_invalid", target_type: "structure", target_id: base.structure_id,
      message: "Generated partial geometry failed canonical validation." }], opts.graph);
  }
  const diagnostics = base.diagnostics
    .filter((d) => d.code !== "geometry_deferred" && d.code !== "geometry_deferred_complex")
    .concat(opts.extraDiags || []);
  const mappings = {
    facets: doc.facets.map((f) => ({ sketch_facet_id: f.id, measurement_facet_id: f.measurement_facet_id })),
    edges: doc.edges.filter((e) => e.measurement_edge_id != null).map((e) => ({ sketch_edge_id: e.id, measurement_edge_id: e.measurement_edge_id })),
    penetrations: (doc.penetrations || []).map((p) => ({ sketch_penetration_id: p.id, measurement_penetration_id: p.measurement_penetration_id, position_known: false })),
  };
  return {
    ...base,
    ok: false,
    status: "needs_review",
    confidence: "partial",
    geometry_status: "partial",
    readiness: "needs_review",
    partial: true,
    document: doc,
    mappings,
    diagnostics,
    unresolved: diagnostics.filter((d) => d.severity === "error"),
    resolved_planes: opts.resolvedPlanes || doc.facets.map((f) => f.measurement_facet_id),
    unresolved_planes: opts.unresolvedPlanes || [],
    unresolved_lines: opts.unresolvedLines || [],
    ambiguities: opts.ambiguities || [],
    ...(opts.graph ? { graph: opts.graph } : {}),
  };
}

// Connected components of the plane adjacency graph (shared roof lines only). Deterministic order.
function _components(base) {
  const nodes = _allPlaneIds(base);
  const idset = new Set(nodes);
  const parent = {}; nodes.forEach((nd) => { parent[nd] = nd; });
  const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  const union = (a, b) => { parent[find(a)] = find(b); };
  base.constraints.adjacency.forEach((a) => { const [x, y] = a.facets.map(String); if (idset.has(x) && idset.has(y)) union(x, y); });
  const groups = {};
  nodes.forEach((nd) => { const r = find(nd); (groups[r] = groups[r] || []).push(nd); });
  const comps = Object.values(groups).map((g) => g.slice().sort());
  comps.sort((a, b) => (b.length - a.length) || (a[0] < b[0] ? -1 : 1));
  return comps;
}

// Sub-input for one component (relational scoping only).
function _subInput(input, compSet) {
  const inSet = (id) => id != null && compSet.has(String(id));
  return {
    structure: input.structure,
    facets: (input.facets || []).filter((f) => inSet(f && f.id)),
    edges: (input.edges || []).filter((e) => e && (inSet(e.facet_id) || inSet(e.facet_id_secondary))),
    penetrations: (input.penetrations || []).filter((p) => p && inSet(p.facet_id)),
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
  // An Area override (area_sqft != width_ft*length_ft) is allowed and preserved — the foundation already
  // emits a non-blocking info diagnostic. Geometry is built from Width/Length; do NOT block on it.
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
  // width_ft is the SLOPED eave->ridge distance; deproject to the horizontal plan run for plan-view Y.
  const planRun = planRunFromSlope(W, num(f.pitch_rise));
  if (planRun == null || !(planRun > 0)) {
    return _needsReview(base, [{ severity: "error", code: "missing_pitch", target_type: "facet", target_id: mid,
      message: "Roof plane needs a pitch to deproject the sloped Width into plan geometry." }]);
  }
  const v0 = { id: "gv_0", x: 0, y: 0 }, v1 = { id: "gv_1", x: L, y: 0 };
  const v2 = { id: "gv_2", x: L, y: planRun }, v3 = { id: "gv_3", x: 0, y: planRun };
  doc.vertices = [v0, v1, v2, v3];
  const eBottom = _edge("gen_e_bottom", v0.id, v1.id, "eave", L, assigned.bottom);
  const eRight = _edge("gen_e_right", v1.id, v2.id, "rake", planRun, assigned.right);
  const eTop = _edge("gen_e_top", v2.id, v3.id, "eave", L, assigned.top);
  const eLeft = _edge("gen_e_left", v3.id, v0.id, "rake", planRun, assigned.left);
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

  // For each plane: Length is the ridge-parallel dimension and MUST match the shared Ridge length;
  // Width is strictly the sloped eave->ridge depth (deprojected downstream). No axis swapping.
  function planeDepth(mid) {
    const f = facetByMid[mid];
    const W = num(f.width_ft), L = num(f.length_ft);
    if (W == null || !(W > 0) || L == null || !(L > 0)) {
      return { error: { severity: "error", code: "insufficient_dimensions", target_type: "facet", target_id: mid,
        message: "Each gable plane needs both Width and Length." } };
    }
    // Length is the ridge/eave-parallel dimension: it must equal the shared Ridge length.
    if (!approx(L, R, LEN_TOL)) {
      return { error: { severity: "error", code: "contradictory_dimensions", target_type: "facet", target_id: mid,
        message: "Plane Length must match the shared Ridge length (Length is the ridge/eave-parallel dimension; Width is the sloped depth)." } };
    }
    // Area override allowed/preserved (see single-plane note) — do not block gable generation on it.
    // Width is the sloped eave->ridge depth; it is deprojected with the plane's pitch downstream.
    return { depth: W };
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
  // Each plane's ridge->eave depth is its SLOPED Width; deproject with THAT plane's pitch for plan-view Y.
  const pitchA = num(facetByMid[pAmid].pitch_rise), pitchB = num(facetByMid[pBmid].pitch_rise);
  const planDepthA = planRunFromSlope(dA.depth, pitchA), planDepthB = planRunFromSlope(dB.depth, pitchB);
  if (planDepthA == null || !(planDepthA > 0) || planDepthB == null || !(planDepthB > 0)) {
    return _needsReview(base, [{ severity: "error", code: "missing_pitch", target_type: "structure", target_id: base.structure_id,
      message: "Each gable plane needs a pitch to deproject its sloped Width into plan geometry." }]);
  }
  const rA = { id: "gv_rA", x: 0, y: 0 }, rB = { id: "gv_rB", x: R, y: 0 };
  const aL = { id: "gv_aL", x: 0, y: planDepthA }, aR = { id: "gv_aR", x: R, y: planDepthA };
  const bL = { id: "gv_bL", x: 0, y: -planDepthB }, bR = { id: "gv_bR", x: R, y: -planDepthB };
  doc.vertices = [rA, rB, aL, aR, bL, bR];

  const ridge = _edge("gen_e_ridge", rA.id, rB.id, "ridge", R, ridgeLine);
  const rakeAR = _edge("gen_e_rakeAR", rB.id, aR.id, "rake", planDepthA, asgA.assigned.rakeAR);
  const eaveA = _edge("gen_e_eaveA", aR.id, aL.id, "eave", R, asgA.assigned.eaveA);
  const rakeAL = _edge("gen_e_rakeAL", aL.id, rA.id, "rake", planDepthA, asgA.assigned.rakeAL);
  const rakeBR = _edge("gen_e_rakeBR", rB.id, bR.id, "rake", planDepthB, asgB.assigned.rakeBR);
  const eaveB = _edge("gen_e_eaveB", bR.id, bL.id, "eave", R, asgB.assigned.eaveB);
  const rakeBL = _edge("gen_e_rakeBL", bL.id, rA.id, "rake", planDepthB, asgB.assigned.rakeBL);
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
function _finalize(base, doc, graph) {
  const v = validateSketch(doc);
  if (!v.valid) {
    return _needsReview(base, [{ severity: "error", code: "generated_geometry_invalid", target_type: "structure", target_id: base.structure_id,
      message: "Generated geometry failed canonical validation: " + (v.errors[0] && v.errors[0].code) }], graph);
  }
  const mappings = {
    facets: doc.facets.map((f) => ({ sketch_facet_id: f.id, measurement_facet_id: f.measurement_facet_id })),
    edges: doc.edges.filter((e) => e.measurement_edge_id != null)
      .map((e) => ({ sketch_edge_id: e.id, measurement_edge_id: e.measurement_edge_id })),
    penetrations: (doc.penetrations || []).map((p) => ({ sketch_penetration_id: p.id, measurement_penetration_id: p.measurement_penetration_id, position_known: false })),
  };
  return _success(base, doc, mappings, [], graph);
}

// ---- connected multi-plane: adjacency graph + standard hip ----------------------------------------
const SHARED_TYPES = new Set(["ridge", "hip", "valley", "dead_valley"]);

// Build the facet adjacency graph from the AUTHORITATIVE Primary/Secondary relationships on shared
// roof lines (never from matching lengths/labels). Reports shared edges once each + component count.
function _adjacencyGraph(base) {
  const nodes = base.constraints.planes.map((p) => String(p.measurement_facet_id));
  const idset = new Set(nodes);
  const sharedEdges = base.constraints.adjacency.map((a) => ({
    measurement_edge_id: String(a.measurement_edge_id), edge_type: a.edge_type, facets: a.facets.map(String),
  }));
  const parent = {}; nodes.forEach((nd) => { parent[nd] = nd; });
  const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  const union = (a, b) => { parent[find(a)] = find(b); };
  sharedEdges.forEach((s) => { if (s.facets.length === 2 && idset.has(s.facets[0]) && idset.has(s.facets[1])) union(s.facets[0], s.facets[1]); });
  const comps = new Set(nodes.map((nd) => find(nd)));
  return { nodes, shared_edges: sharedEdges, components: comps.size, node_count: nodes.length };
}

// A shared-type roof line (Ridge/Hip/Valley/Dead Valley) MUST connect exactly two distinct in-scope
// planes. Anything else (self-reference, one foreign/missing endpoint) is contradictory adjacency.
function _contradictoryAdjacency(base, edgesIn) {
  const idset = new Set(base.constraints.planes.map((p) => String(p.measurement_facet_id)));
  for (const e of edgesIn) {
    if (!SHARED_TYPES.has(e.edge_type)) continue;
    const p = e.facet_id != null ? String(e.facet_id) : null;
    const s = e.facet_id_secondary != null ? String(e.facet_id_secondary) : null;
    const pin = p != null && idset.has(p);
    const sin = s != null && idset.has(s);
    if (!pin && !sin) continue; // fully foreign — foundation already excluded; not our structure
    if (!pin || !sin || p === s) {
      return { severity: "error", code: "contradictory_adjacency", target_type: "edge", target_id: String(e.id),
        message: `A ${e.edge_type} roof line must connect two distinct roof planes of this structure (Primary/Secondary).` };
    }
  }
  return null;
}

// Exterior (non-shared) roof lines belonging to a plane, sorted stably.
function _planeExterior(edgesIn, mid, sharedMids) {
  return edgesIn.filter((e) => !sharedMids.has(String(e.id)) &&
    (String(e.facet_id) === String(mid) || String(e.facet_id_secondary) === String(mid))).slice().sort(bySortThenId);
}

// Recognize a STANDARD hip strictly from the adjacency graph + Roof Line Types (no length/label guessing).
// Returns { result } (success or a specific needs_review) once the topology is a hip, or { result: null }
// to DEFER (fall through to unresolved_complex) when it is not a clean standard hip.
function _tryStandardHip(base, edgesIn) {
  const planes = base.constraints.planes;
  if (planes.length !== 4) return { result: null };
  const adj = base.constraints.adjacency;
  const ridges = adj.filter((a) => a.edge_type === "ridge");
  const hips = adj.filter((a) => a.edge_type === "hip");
  const others = adj.filter((a) => a.edge_type !== "ridge" && a.edge_type !== "hip");
  if (others.length > 0) return { result: null };            // valley/dead_valley/etc -> next phase
  if (ridges.length !== 1 || hips.length !== 4) return { result: null };
  const t1 = String(ridges[0].facets[0]), t2 = String(ridges[0].facets[1]);
  if (t1 === t2) return { result: null };
  const triMids = planes.map((p) => String(p.measurement_facet_id)).filter((m) => m !== t1 && m !== t2).sort();
  if (triMids.length !== 2) return { result: null };
  const [tri3, tri4] = triMids;
  const slotByCombo = {};
  for (const h of hips) {
    const [a, b] = h.facets.map(String);
    const trap = (a === t1 || a === t2) ? a : ((b === t1 || b === t2) ? b : null);
    const tri = (a === tri3 || a === tri4) ? a : ((b === tri3 || b === tri4) ? b : null);
    if (trap == null || tri == null) return { result: null };  // hip not trapezoid<->triangle
    const combo = (trap === t1 ? "F" : "B") + "-" + (tri === tri3 ? "L" : "R");
    if (slotByCombo[combo]) return { result: null };           // duplicate combo -> not a clean hip
    slotByCombo[combo] = String(h.measurement_edge_id);
  }
  if (!["F-L", "F-R", "B-L", "B-R"].every((c) => slotByCombo[c])) return { result: null };

  const sharedMids = new Set(adj.map((a) => String(a.measurement_edge_id)));
  const planeByMid = {}; planes.forEach((p) => { planeByMid[String(p.measurement_facet_id)] = p; });
  // exterior lines must be eaves only; a rake/sidewall/headwall/transition means an addition -> defer
  for (const m of [t1, t2, tri3, tri4]) {
    const ext = _planeExterior(edgesIn, m, sharedMids);
    if (ext.some((l) => l.edge_type !== "eave")) return { result: null };
  }
  // equal pitch (symmetric hip) — an asymmetric hip is not uniquely determined -> defer to next phase
  const pitches = [t1, t2, tri3, tri4].map((m) => num(planeByMid[m].pitch_rise));
  if (pitches.some((p) => p == null) || pitches.some((p) => Math.abs(p - pitches[0]) > 0.01)) return { result: null };

  return { result: _layoutStandardHip(base, edgesIn, { t1, t2, tri3, tri4, ridgeMid: String(ridges[0].measurement_edge_id), slotByCombo, sharedMids }) };
}

function _layoutStandardHip(base, edgesIn, ctx) {
  const { t1, t2, tri3, tri4, ridgeMid, slotByCombo, sharedMids } = ctx;
  const graph = _adjacencyGraph(base);
  const lineById = {}; edgesIn.forEach((e) => { lineById[String(e.id)] = e; });
  const planeByMid = {}; base.constraints.planes.forEach((p) => { planeByMid[String(p.measurement_facet_id)] = p; });

  const singleEave = (mid) => {
    const eaves = _planeExterior(edgesIn, mid, sharedMids).filter((l) => l.edge_type === "eave");
    return eaves.length === 1 ? eaves[0] : null;
  };
  const eT1 = singleEave(t1), eT2 = singleEave(t2), eL = singleEave(tri3), eR = singleEave(tri4);
  if (!eT1 || !eT2 || !eL || !eR) {
    return _needsReview(base, [{ severity: "error", code: "insufficient_dimensions", target_type: "structure", target_id: base.structure_id,
      message: "A standard hip needs exactly one eave per roof plane to establish the footprint." }], graph);
  }
  const L1 = num(eT1.length_ft), L2 = num(eT2.length_ft), W3 = num(eL.length_ft), W4 = num(eR.length_ft);
  const ridgeLine = lineById[ridgeMid];
  const ridgeLen = ridgeLine ? num(ridgeLine.length_ft) : null;
  if ([L1, L2, W3, W4, ridgeLen].some((x) => x == null || !(x > 0))) {
    return _needsReview(base, [{ severity: "error", code: "insufficient_dimensions", target_type: "structure", target_id: base.structure_id,
      message: "A standard hip needs positive eave lengths on all planes and a positive ridge length." }], graph);
  }
  if (!approx(L1, L2, LEN_TOL) || !approx(W3, W4, LEN_TOL)) {
    return _needsReview(base, [{ severity: "error", code: "contradictory_dimensions", target_type: "structure", target_id: base.structure_id,
      message: "Opposite hip eaves must be equal; the measured eaves are contradictory." }], graph);
  }
  const L = L1, W = W3;
  if (!(L > W + LEN_TOL)) {
    return _needsReview(base, [{ severity: "error", code: "contradictory_dimensions", target_type: "structure", target_id: base.structure_id,
      message: "The long (ridge) eaves must exceed the short (hip-end) eaves for a hip with a ridge." }], graph);
  }
  if (!approx(ridgeLen, L - W, LEN_TOL)) {
    return _needsReview(base, [{ severity: "error", code: "contradictory_dimensions", target_type: "edge", target_id: ridgeMid,
      message: "Measured ridge length does not match a symmetric hip (expected long eave − short eave)." }], graph);
  }

  const doc = createSketchDocument({ structureId: base.structure_id });
  doc.scale = { resolved: true, feetPerUnit: 1, feet_per_unit: 1, method: "measurement_dimensions" };
  const c00 = { id: "gv_c00", x: 0, y: 0 }, cL0 = { id: "gv_cL0", x: L, y: 0 };
  const cLW = { id: "gv_cLW", x: L, y: W }, c0W = { id: "gv_c0W", x: 0, y: W };
  const r1 = { id: "gv_r1", x: W / 2, y: W / 2 }, r2 = { id: "gv_r2", x: L - W / 2, y: W / 2 };
  doc.vertices = [c00, cL0, cLW, c0W, r1, r2];
  const hipPlan = Math.round(Math.hypot(W / 2, W / 2) * 100) / 100;

  const ridge = _edge("gen_e_ridge", r1.id, r2.id, "ridge", L - W, ridgeLine);
  const hipFL = _edge("gen_e_hipFL", c00.id, r1.id, "hip", hipPlan, lineById[slotByCombo["F-L"]]);
  const hipFR = _edge("gen_e_hipFR", cL0.id, r2.id, "hip", hipPlan, lineById[slotByCombo["F-R"]]);
  const hipBL = _edge("gen_e_hipBL", c0W.id, r1.id, "hip", hipPlan, lineById[slotByCombo["B-L"]]);
  const hipBR = _edge("gen_e_hipBR", cLW.id, r2.id, "hip", hipPlan, lineById[slotByCombo["B-R"]]);
  const eaveFront = _edge("gen_e_eaveFront", c00.id, cL0.id, "eave", L, eT1);
  const eaveBack = _edge("gen_e_eaveBack", c0W.id, cLW.id, "eave", L, eT2);
  const eaveLeft = _edge("gen_e_eaveLeft", c00.id, c0W.id, "eave", W, eL);
  const eaveRight = _edge("gen_e_eaveRight", cL0.id, cLW.id, "eave", W, eR);
  doc.edges = [ridge, hipFL, hipFR, hipBL, hipBR, eaveFront, eaveBack, eaveLeft, eaveRight];

  const facet = (mid, edgeIds) => {
    const p = planeByMid[mid];
    return { id: `msf_${mid}`, measurement_facet_id: mid, relational_facet_id: mid, label: p.label || "F",
      pitch_rise: num(p.pitch_rise), confirmed_area_sqft: num(p.area_sqft), orientation_azimuth: num(p.orientation_azimuth),
      roof_material: null, edgeIds, vertexIds: [] };
  };
  doc.facets = [
    facet(t1, [eaveFront.id, hipFR.id, ridge.id, hipFL.id]),
    facet(t2, [eaveBack.id, hipBR.id, ridge.id, hipBL.id]),
    facet(tri3, [eaveLeft.id, hipBL.id, hipFL.id]),
    facet(tri4, [eaveRight.id, hipBR.id, hipFR.id]),
  ];
  doc.penetrations = base.document.penetrations;
  doc.generated = base.document.generated;
  return _finalize(base, doc, graph);
}

function _layoutConnected(base, facetsIn, edgesIn, input) {
  const graph = _adjacencyGraph(base);
  const contradiction = _contradictoryAdjacency(base, edgesIn);
  if (contradiction) return _needsReview(base, [contradiction], graph);

  const comps = _components(base);
  if (comps.length === 1) {
    const hip = _tryStandardHip(base, edgesIn);
    if (hip.result) return hip.result;
    // Complex connected roof: the arrangement is not unique. Emit a placement scaffold so the user can
    // resolve each plane's side; if resolutions are supplied, lay it out deterministically from them.
    const scaffold = planPlacement(base);
    const hasRes = input && (Array.isArray(input.resolutions) ? input.resolutions.length : (input.resolutions && Object.keys(input.resolutions).length));
    if (hasRes) {
      const laid = layoutFromResolutions(base, edgesIn, input.resolutions);
      if (laid && laid.doc && laid.resolved && laid.resolved.length) {
        const v = validateSketch(laid.doc);
        if (v.valid) {
          const warnDiags = (laid.approximations || []).concat([{ severity: "info", code: "resolved_placement", target_type: "structure", target_id: base.structure_id,
            message: "Roof laid out from your side choices — positions follow those choices; some junction geometry is approximate." }]);
          const attach = (res) => ({ ...res, placement_requests: scaffold.requests, approximations: laid.approximations });
          if (laid.unresolved.length === 0 && (laid.approximations || []).every((d) => d.severity !== "error")) {
            return attach(_success(base, laid.doc, undefined, warnDiags, graph));
          }
          return attach(_partial(base, laid.doc, { graph, resolvedPlanes: laid.resolved, unresolvedPlanes: laid.unresolved,
            ambiguities: _ambiguityRecords(base, laid.unresolved), extraDiags: warnDiags }));
        }
      }
    }
    return { ..._needsReview(base, [{ severity: "error", code: "unresolved_complex_topology", target_type: "structure", target_id: base.structure_id,
      message: "This connected roof permits more than one valid arrangement — resolve each plane's side to generate it." }], graph,
      { ambiguities: _ambiguityRecords(base, comps[0]), unresolvedPlanes: comps[0], unresolvedLines: graph.shared_edges.map((e) => e.measurement_edge_id) }),
      placement_requests: scaffold.requests };
  }

  // Multiple sections: attempt each independently (partial-proposal support).
  const results = comps.map((comp) => ({ comp, sub: generateSketchGeometry(_subInput(input, new Set(comp))) }));
  const solved = results.filter((r) => r.sub.ok);
  const unsolved = results.filter((r) => !r.sub.ok);

  if (solved.length > 0 && unsolved.length > 0) {
    const drawn = solved[0]; // comps sorted (-size, min-id); solved preserves that order
    const doc = drawn.sub.document;
    doc.generated = base.document.generated; // whole-structure provenance/fingerprint
    const unresolvedPlanes = results.filter((r) => r !== drawn).flatMap((r) => r.comp);
    const ambiguities = [];
    unsolved.forEach((r) => {
      const recs = _ambiguityRecords(base, r.comp);
      if (recs.length) ambiguities.push(...recs);
      else ambiguities.push({ code: "section_unresolved", planes: r.comp, message: `Roof section (${r.comp.join(", ")}) could not be uniquely reconstructed and remains unresolved.` });
    });
    solved.slice(1).forEach((r) => ambiguities.push({ code: "relative_placement_unknown", planes: r.comp, message: `A separate solvable roof section (${r.comp.join(", ")}) is not linked to the drawn section by a shared roof line; its relative placement is not established.` }));
    const drawnSet = new Set(drawn.comp.map(String));
    const unresolvedLines = edgesIn.filter((e) => !(drawnSet.has(String(e.facet_id)) || drawnSet.has(String(e.facet_id_secondary)))).map((e) => String(e.id));
    return _partial(base, doc, { graph, resolvedPlanes: drawn.comp.slice(), unresolvedPlanes, unresolvedLines, ambiguities,
      extraDiags: [{ severity: "info", code: "partial_proposal", target_type: "structure", target_id: base.structure_id,
        message: "Only part of this roof could be uniquely reconstructed; the rest is left explicitly unresolved." }] });
  }

  if (solved.length > 1) {
    // Every section is solvable but they are not linked — never force an assembly.
    const ambiguities = solved.map((r) => ({ code: "relative_placement_unknown", planes: r.comp, message: `Roof section (${r.comp.join(", ")}) is solvable but not linked to the others by a shared roof line; relative placement is not established.` }));
    return _needsReview(base, [{ severity: "error", code: "disconnected_planes", target_type: "structure", target_id: base.structure_id,
      message: "Roof planes form multiple sections not linked by shared roof lines; their relative placement is not established." }], graph, { ambiguities });
  }

  const ambiguities = comps.flatMap((c) => _ambiguityRecords(base, c));
  return _needsReview(base, [{ severity: "error", code: "unresolved_complex_topology", target_type: "structure", target_id: base.structure_id,
    message: "This roof could not be uniquely reconstructed from the measurements." }], graph, { ambiguities });
}

// Public entry: constraint foundation + deterministic geometry for the two supported roof types.
function generateSketchGeometry(input) {
  const base = generateProposedSketch(input);
  if (base.status !== "generated") {
    return { ...base, geometry_status: "not_attempted", readiness: _classifyReadiness(base.diagnostics), partial: false,
      resolved_planes: [], unresolved_planes: _allPlaneIds(base), unresolved_lines: [], ambiguities: [] };
  }
  const facetsIn = (Array.isArray(input && input.facets) ? input.facets : [])
    .filter((f) => f && f.id != null && (base.structure_id == null || String(f.structure_id) === String(base.structure_id)))
    .slice().sort(bySortThenId);
  const edgesIn = (Array.isArray(input && input.edges) ? input.edges : []).filter((e) => e && e.id != null);

  if (base.archetype === "single_plane") return _layoutSinglePlane(base, facetsIn, edgesIn);
  if (base.archetype === "symmetric_gable") return _layoutGable(base, facetsIn, edgesIn);
  // >2 planes / connected multi-plane: build the adjacency graph and solve only when uniquely determined.
  return _layoutConnected(base, facetsIn, edgesIn, input);
}

module.exports = { generateSketchGeometry, LEN_TOL };
