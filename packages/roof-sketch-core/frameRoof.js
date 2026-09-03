"use strict";
// Deterministic ROOF-FRAMING SOLVER (replaces the old fan-out placement heuristic for complex roofs).
//
// Model the roof the way it is framed: from the RIDGE network outward. A roof is a set of rectangular
// "cores" (footprint rectangles). Each core has a ridge running along its long axis, two main slope
// planes between the ridge and the two long eaves, and two end treatments (a hip -> triangular plane, or
// a gable -> rake edges / no plane). Hips/valleys are the intersections between adjacent slope planes.
//
// This module is built in stages (see /app/memory/ROOF_FRAMING_SOLVER_PLAN.md). It returns null to DEFER
// (let the caller fall back) for any topology it does not yet solve, so simple archetypes and the legacy
// resolve-placement path are never regressed.
//
// Invariants: deterministic (no Date/Math.random; stable ids; same input => same output). Never fabricate
// dimensions silently — under-constrained placements emit an `approximations` diagnostic. Output must pass
// validateSketch (no overlapping facet interiors). width_ft is the SLOPED eave->ridge depth and is
// deprojected via planRunFromSlope(width_ft, pitch) to a plan run; length_ft / eaves are plan dimensions.

const { createSketchDocument } = require("./schema");
const { validateSketch } = require("./topology");
const { planRunFromSlope } = require("./geometry");

const num = (v) => { if (v === "" || v == null) return null; const n = Number(v); return Number.isFinite(n) ? n : null; };
const rnd = (n) => Math.round(Number(n) * 1000) / 1000;
const approxEq = (a, b, tol) => a != null && b != null && Math.abs(Number(a) - Number(b)) <= tol;
const LEN_TOL = 0.5;

// ---- geometry document builder (vertex/edge dedup + measurement-line mapping) ---------------------
function makeBuilder() {
  const verts = []; const vidByKey = {};
  const edges = []; let ei = 0;
  const vget = (x, y) => {
    const xr = rnd(x), yr = rnd(y); const key = xr + "|" + yr;
    if (vidByKey[key] != null) return vidByKey[key];
    const id = "fv_" + verts.length; verts.push({ id, x: xr, y: yr }); vidByKey[key] = id; return id;
  };
  // Add an edge between two plan points. `line` (a measurement roof line) maps the drawn edge to its
  // authoritative Roof Line; otherwise a derived boundary edge of the given `type` is created.
  const edge = (aPt, bPt, type, line) => {
    const v1 = vget(aPt.x, aPt.y), v2 = vget(bPt.x, bPt.y);
    const existing = edges.find((e) => (e.v1 === v1 && e.v2 === v2) || (e.v1 === v2 && e.v2 === v1));
    if (existing) return existing;
    const drawn = rnd(Math.hypot(bPt.x - aPt.x, bPt.y - aPt.y));
    const e = line
      ? { id: "mse_" + line.id, measurement_edge_id: String(line.id), relational_edge_id: String(line.id),
          v1, v2, type: line.edge_type, confirmed_length_ft: num(line.length_ft), locked: num(line.length_ft) != null, drawn_length_ft: drawn }
      : { id: "fe_" + (ei++), measurement_edge_id: null, v1, v2, type, confirmed_length_ft: null, locked: false, drawn_length_ft: drawn };
    edges.push(e); return e;
  };
  return { verts, edges, vget, edge };
}

// Exterior (non-shared) roof lines of a plane, of a given type, sorted stably.
function planeLinesOfType(edgesIn, mid, type, sharedMids) {
  return edgesIn
    .filter((e) => e && e.id != null && !sharedMids.has(String(e.id)))
    .filter((e) => e.edge_type === type)
    .filter((e) => String(e.facet_id) === String(mid) || String(e.facet_id_secondary) === String(mid))
    .sort((a, b) => (String(a.id) < String(b.id) ? -1 : 1));
}

function facetRecord(plane, mid, edgeIds) {
  return {
    id: "ff_" + mid, measurement_facet_id: mid, relational_facet_id: mid, label: (plane && plane.label) || "F",
    pitch_rise: num(plane && plane.pitch_rise), confirmed_area_sqft: num(plane && plane.area_sqft),
    orientation_azimuth: num(plane && plane.orientation_azimuth), roof_material: null, edgeIds, vertexIds: [],
  };
}

// ---- single-core layout (gable / standard hip / half-hip), built from the ridge outward -----------
// Detects a roof that is ONE rectangular core: exactly one Ridge (the two main slopes) plus 0..2 hip-end
// triangles connected by Hips to BOTH main slopes; no valleys. Returns a laid-out result, or null to defer.
function trySingleCore(base, edgesIn) {
  const planes = base.constraints.planes;
  const adj = base.constraints.adjacency;
  const ridges = adj.filter((a) => a.edge_type === "ridge");
  const hips = adj.filter((a) => a.edge_type === "hip");
  const others = adj.filter((a) => a.edge_type !== "ridge" && a.edge_type !== "hip");
  if (others.length > 0) return null;              // valleys/dead-valleys -> not a single core (later stage)
  if (ridges.length !== 1) return null;            // 0 or >1 ridges -> not a single core

  const planeByMid = {}; planes.forEach((p) => { planeByMid[String(p.measurement_facet_id)] = p; });
  const [mainA, mainB] = ridges[0].facets.map(String);
  if (mainA === mainB || !planeByMid[mainA] || !planeByMid[mainB]) return null;
  const mainSet = new Set([mainA, mainB]);

  // End planes: connected by a hip to BOTH main slopes (a proper hip-end triangle sits between them).
  const hipNeighbours = {}; // endMid -> Set(mainMid)
  for (const h of hips) {
    const [x, y] = h.facets.map(String);
    const end = mainSet.has(x) ? y : (mainSet.has(y) ? x : null);
    const main = mainSet.has(x) ? x : (mainSet.has(y) ? y : null);
    if (end == null || main == null || mainSet.has(end)) return null; // hip not main<->end
    (hipNeighbours[end] = hipNeighbours[end] || new Set()).add(main);
  }
  const endMids = Object.keys(hipNeighbours).sort();
  for (const e of endMids) { if (hipNeighbours[e].size !== 2) return null; } // each end must touch both mains
  if (endMids.length > 2) return null;
  // Every non-main plane must be an accounted-for end (no stray planes).
  const accounted = new Set([mainA, mainB, ...endMids]);
  if (planes.some((p) => !accounted.has(String(p.measurement_facet_id)))) return null;

  const sharedMids = new Set(adj.map((a) => String(a.measurement_edge_id)));
  const lineById = {}; edgesIn.forEach((e) => { lineById[String(e.id)] = e; });
  const ridgeLine = lineById[String(ridges[0].measurement_edge_id)];

  // Deterministic role assignment: front = smaller-id main (drawn at low y / north); ends by sorted id.
  const [frontMid, backMid] = [mainA, mainB].sort();
  const loMid = endMids[0] || null;   // hip end at x=0 (or null => gable end)
  const hiMid = endMids[1] || null;   // hip end at x=L

  const singleEave = (mid) => { const es = planeLinesOfType(edgesIn, mid, "eave", sharedMids); return es.length === 1 ? es[0] : null; };
  const frontEave = singleEave(frontMid), backEave = singleEave(backMid);

  // Footprint length L = the long (main-slope) eave. Depth W = short eave (hip) or sum of slope plan runs.
  const approximations = [];
  let L = frontEave ? num(frontEave.length_ft) : (backEave ? num(backEave.length_ft) : null);
  if (L == null || !(L > 0)) L = num(planeByMid[frontMid].length_ft);
  if (L == null || !(L > 0)) return null;

  const slopeRun = (mid) => { const p = planeByMid[mid]; return planRunFromSlope(num(p.width_ft), p.pitch_rise); };
  const runFront = slopeRun(frontMid), runBack = slopeRun(backMid);

  let W = null;
  const anyEndEave = loMid ? singleEave(loMid) : (hiMid ? singleEave(hiMid) : null);
  if (anyEndEave && num(anyEndEave.length_ft) > 0) W = num(anyEndEave.length_ft);
  else if (runFront != null && runBack != null) W = rnd(runFront + runBack);
  if (W == null || !(W > 0)) return null;

  // Symmetric core assumption (equal pitch): ridge lies at mid-depth; hip insets split from the ridge.
  const ridgeLen = ridgeLine ? num(ridgeLine.length_ft) : null;
  const hippedEnds = endMids.length;
  let insetLo = 0, insetHi = 0;
  if (hippedEnds > 0) {
    let totalInset;
    if (ridgeLen != null && ridgeLen > 0 && ridgeLen < L) totalInset = rnd(L - ridgeLen);
    else { totalInset = rnd((hippedEnds === 2 ? W : W / 2)); approximations.push({ severity: "warning", code: "approx_hip_inset", target_type: "structure", target_id: base.structure_id, message: "Hip inset approximated from eave depth (no ridge length)." }); }
    if (hippedEnds === 2) { insetLo = rnd(totalInset / 2); insetHi = rnd(totalInset / 2); }
    else if (loMid) { insetLo = totalInset; } else { insetHi = totalInset; }
  }
  if (insetLo + insetHi >= L) return null; // ridge would vanish/invert -> not a clean core
  const ridgeY = rnd(W / 2);

  const b = makeBuilder();
  const P = (x, y) => ({ x: rnd(x), y: rnd(y) });
  // Footprint corners.
  const flo = P(0, 0), fhi = P(L, 0), bhi = P(L, W), blo = P(0, W);
  // Ridge endpoints.
  const rLo = P(insetLo, ridgeY), rHi = P(L - insetHi, ridgeY);

  const ridge = b.edge(rLo, rHi, "ridge", ridgeLine);
  const eaveFront = b.edge(flo, fhi, "eave", frontEave);
  const eaveBack = b.edge(blo, bhi, "eave", backEave);

  // Map a hip line connecting `end` and `main`.
  const hipLine = (end, main) => {
    const a = hips.find((h) => { const s = new Set(h.facets.map(String)); return s.has(end) && s.has(main); });
    return a ? lineById[String(a.measurement_edge_id)] : null;
  };

  const facets = [];
  // ---- lo end ----
  let frontLoEdge, backLoEdge;
  if (loMid) {
    const shortEave = singleEave(loMid);
    frontLoEdge = b.edge(flo, rLo, "hip", hipLine(loMid, frontMid));
    backLoEdge = b.edge(blo, rLo, "hip", hipLine(loMid, backMid));
    const sEave = b.edge(flo, blo, "eave", shortEave);
    facets.push(facetRecord(planeByMid[loMid], loMid, [sEave.id, backLoEdge.id, frontLoEdge.id]));
  } else {
    frontLoEdge = b.edge(flo, rLo, "rake", null);
    backLoEdge = b.edge(blo, rLo, "rake", null);
  }
  // ---- hi end ----
  let frontHiEdge, backHiEdge;
  if (hiMid) {
    const shortEave = singleEave(hiMid);
    frontHiEdge = b.edge(fhi, rHi, "hip", hipLine(hiMid, frontMid));
    backHiEdge = b.edge(bhi, rHi, "hip", hipLine(hiMid, backMid));
    const sEave = b.edge(fhi, bhi, "eave", shortEave);
    facets.push(facetRecord(planeByMid[hiMid], hiMid, [sEave.id, backHiEdge.id, frontHiEdge.id]));
  } else {
    frontHiEdge = b.edge(fhi, rHi, "rake", null);
    backHiEdge = b.edge(bhi, rHi, "rake", null);
  }

  // ---- main slopes (loop order threads a single closed cycle) ----
  facets.push(facetRecord(planeByMid[frontMid], frontMid, [eaveFront.id, frontHiEdge.id, ridge.id, frontLoEdge.id]));
  facets.push(facetRecord(planeByMid[backMid], backMid, [eaveBack.id, backHiEdge.id, ridge.id, backLoEdge.id]));

  if (runFront == null || runBack == null) approximations.push({ severity: "warning", code: "approx_plane_depth", target_type: "structure", target_id: base.structure_id, message: "Slope depth approximated (missing sloped Width + pitch)." });

  const resolvedOrder = [frontMid, backMid, ...endMids];
  return finalize(base, b, facets, resolvedOrder, approximations, "single_core");
}

// ---- finalize: assemble the canonical document + validate --------------------------------------------
function finalize(base, b, facets, resolvedOrder, approximations, method) {
  const doc = createSketchDocument({ structureId: base.structure_id });
  doc.scale = { resolved: true, feetPerUnit: 1, feet_per_unit: 1, method: "roof_framing_solver" };
  doc.vertices = b.verts;
  doc.edges = b.edges;
  doc.facets = facets;
  doc.penetrations = base.document.penetrations;
  doc.generated = base.document.generated;
  const v = validateSketch(doc);
  return { doc, resolved: resolvedOrder, unresolved: [], approximations: approximations || [], valid: v.valid, validation: v, method };
}

// Public entry. Returns null to DEFER (caller falls back) when the topology is not yet solved.
function frameRoof(base, edgesIn, resolutions) {
  if (!base || !base.constraints || !Array.isArray(base.constraints.planes)) return null;
  const edges = (edgesIn || []).filter((e) => e && e.id != null);
  const single = trySingleCore(base, edges);
  if (single) return single;
  return null;
}

module.exports = { frameRoof, trySingleCore, LEN_TOL };
