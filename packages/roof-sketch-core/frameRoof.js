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

  // Every plane must carry a pitch (needed to deproject the sloped Width). Unequal pitches ARE supported:
  // the ridge sits proportionally between the two eaves by each main slope's plan depth (not mid-depth).
  const allMids = [mainA, mainB, ...endMids];
  const pitchList = allMids.map((m) => num(planeByMid[m].pitch_rise));
  if (pitchList.some((p) => p == null)) return null;

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
  // Ridge Y: proportional to each main slope's plan depth (unequal pitch -> off-centre ridge). Equal
  // pitch collapses to mid-depth (W/2). Falls back to mid-depth when a slope depth is unknown.
  let ridgeY;
  if (runFront != null && runFront > 0 && runBack != null && runBack > 0) {
    ridgeY = rnd(W * (runFront / (runFront + runBack)));
  } else {
    ridgeY = rnd(W / 2);
    if (pitchList[0] != null && !pitchList.every((p) => Math.abs(p - pitchList[0]) < 0.01)) {
      approximations.push({ severity: "warning", code: "approx_ridge_position", target_type: "structure", target_id: base.structure_id, message: "Unequal pitch but ridge centred (missing sloped Width to place it exactly)." });
    }
  }

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

// ---- two-core L-roof (equal pitch, equal width): real convex HIP + real concave VALLEY -------------
// Topology: 4 planes, 2 ridges + 1 hip + 1 valley. Each ridge joins a distinct pair (an "arm"); the hip
// joins one plane from each arm (the outer/convex corner), the valley joins the other plane from each arm
// (the reentrant/concave corner). Built as two perpendicular arms of common width W meeting where their
// ridges cross at (W/2, W/2). Deterministic up to whole-roof rotation/reflection. Returns null to defer.
function tryLRoof(base, edgesIn) {
  const planes = base.constraints.planes;
  if (planes.length !== 4) return null;
  const adj = base.constraints.adjacency;
  const ridges = adj.filter((a) => a.edge_type === "ridge");
  const hips = adj.filter((a) => a.edge_type === "hip");
  const valleys = adj.filter((a) => a.edge_type === "valley" || a.edge_type === "dead_valley");
  const other = adj.filter((a) => !["ridge", "hip", "valley", "dead_valley"].includes(a.edge_type));
  if (ridges.length !== 2 || hips.length !== 1 || valleys.length !== 1 || other.length) return null;

  const planeByMid = {}; planes.forEach((p) => { planeByMid[String(p.measurement_facet_id)] = p; });
  const pairA = ridges[0].facets.map(String);
  const pairB = ridges[1].facets.map(String);
  if (new Set([...pairA, ...pairB]).size !== 4) return null; // arms must be disjoint pairs
  const hipSet = new Set(hips[0].facets.map(String));
  const valSet = new Set(valleys[0].facets.map(String));
  // Each arm contributes exactly one plane to the hip and one to the valley.
  const split = (pair) => {
    const h = pair.find((p) => hipSet.has(p)); const v = pair.find((p) => valSet.has(p));
    return h && v && h !== v ? { hip: h, val: v } : null;
  };
  const sA = split(pairA), sB = split(pairB);
  if (!sA || !sB) return null;
  if (!(hipSet.has(sA.hip) && hipSet.has(sB.hip))) return null;
  if (!(valSet.has(sA.val) && valSet.has(sB.val))) return null;

  const sharedMids = new Set(adj.map((a) => String(a.measurement_edge_id)));
  const lineById = {}; edgesIn.forEach((e) => { lineById[String(e.id)] = e; });
  const singleEave = (mid) => { const es = planeLinesOfType(edgesIn, mid, "eave", sharedMids); return es.length === 1 ? es[0] : null; };
  const eaveLen = (mid) => { const e = singleEave(mid); return e ? num(e.length_ft) : null; };

  // Assign the longer-armed pair as horizontal (H); reflection/rotation is acceptable.
  const armLen = (s) => eaveLen(s.hip) != null ? eaveLen(s.hip) : (planeByMid[s.hip] && num(planeByMid[s.hip].length_ft));
  let H = sA, V = sB;
  if ((armLen(sB) || 0) > (armLen(sA) || 0)) { H = sB; V = sA; }
  else if ((armLen(sB) || 0) === (armLen(sA) || 0) && sB.hip < sA.hip) { H = sB; V = sA; }

  // Equal pitch (symmetric) is required; an unequal-pitch L is not uniquely determined here.
  const pitches = [H.hip, H.val, V.hip, V.val].map((m) => num(planeByMid[m].pitch_rise));
  if (pitches.some((p) => p == null) || pitches.some((p) => Math.abs(p - pitches[0]) > 0.01)) return null;

  const approximations = [];
  // Common width W: front-slope plan depth is W/2, so W = 2 * planRunFromSlope(width, pitch).
  const runOf = (mid) => { const p = planeByMid[mid]; return planRunFromSlope(num(p.width_ft), p.pitch_rise); };
  let W = null;
  const rH = runOf(H.hip);
  if (rH != null && rH > 0) W = rnd(rH * 2);
  // Cross-check / fallback from measured eaves: inner eave = outer eave - W.
  const LxE = eaveLen(H.hip), LyE = eaveLen(V.hip), HbackE = eaveLen(H.val), VrightE = eaveLen(V.val);
  if (W == null && LxE != null && HbackE != null) W = rnd(LxE - HbackE);
  if (W == null || !(W > 0)) return null;

  const Lx = LxE != null && LxE > 0 ? LxE : (num(planeByMid[H.hip].length_ft));
  const Ly = LyE != null && LyE > 0 ? LyE : (num(planeByMid[V.hip].length_ft));
  if (Lx == null || !(Lx > W) || Ly == null || !(Ly > W)) return null; // arms must exceed the shared width
  if (rH == null) approximations.push({ severity: "warning", code: "approx_plane_depth", target_type: "structure", target_id: base.structure_id, message: "L-roof width approximated from eaves (no sloped Width + pitch)." });

  const half = rnd(W / 2);
  const b = makeBuilder();
  const P = (x, y) => ({ x: rnd(x), y: rnd(y) });
  const O = P(0, 0), J = P(half, half), Re = P(W, W);
  const Hg0 = P(Lx, 0), Hgm = P(Lx, half), HgW = P(Lx, W);         // H gable end at x=Lx
  const Vg0 = P(0, Ly), Vgm = P(half, Ly), VgW = P(W, Ly);         // V gable end at y=Ly

  const ridgeH = b.edge(J, Hgm, "ridge", lineById[String(ridges[H === sA ? 0 : 1].measurement_edge_id)]);
  const ridgeV = b.edge(J, Vgm, "ridge", lineById[String(ridges[V === sA ? 0 : 1].measurement_edge_id)]);
  const hip = b.edge(O, J, "hip", lineById[String(hips[0].measurement_edge_id)]);
  const valley = b.edge(Re, J, valleys[0].edge_type, lineById[String(valleys[0].measurement_edge_id)]);

  // Hfront (hip side): eave y=0, rake at gable, ridgeH, hip.
  const eHf = b.edge(O, Hg0, "eave", singleEave(H.hip));
  const rHf = b.edge(Hg0, Hgm, "rake", null);
  const fHfront = facetRecord(planeByMid[H.hip], H.hip, [eHf.id, rHf.id, ridgeH.id, hip.id]);
  // Hback (valley side): ridgeH, rake at gable, inner eave, valley.
  const rHb = b.edge(Hgm, HgW, "rake", null);
  const eHb = b.edge(HgW, Re, "eave", singleEave(H.val));
  const fHback = facetRecord(planeByMid[H.val], H.val, [ridgeH.id, rHb.id, eHb.id, valley.id]);
  // Vleft (hip side): hip, ridgeV, rake at gable, eave x=0.
  const rVl = b.edge(Vgm, Vg0, "rake", null);
  const eVl = b.edge(Vg0, O, "eave", singleEave(V.hip));
  const fVleft = facetRecord(planeByMid[V.hip], V.hip, [hip.id, ridgeV.id, rVl.id, eVl.id]);
  // Vright (valley side): valley, inner eave, rake at gable, ridgeV.
  const eVr = b.edge(Re, VgW, "eave", singleEave(V.val));
  const rVr = b.edge(VgW, Vgm, "rake", null);
  const fVright = facetRecord(planeByMid[V.val], V.val, [valley.id, eVr.id, rVr.id, ridgeV.id]);

  const facets = [fHfront, fHback, fVleft, fVright];
  const resolvedOrder = [H.hip, H.val, V.hip, V.val];
  return finalize(base, b, facets, resolvedOrder, approximations, "l_roof");
}

// Public entry. Returns null to DEFER (caller falls back) when the topology is not yet solved.
function frameRoof(base, edgesIn, resolutions) {
  if (!base || !base.constraints || !Array.isArray(base.constraints.planes)) return null;
  const edges = (edgesIn || []).filter((e) => e && e.id != null);
  const single = trySingleCore(base, edges);
  if (single) return single;
  const l = tryLRoof(base, edges);
  if (l) return l;
  return null;
}

module.exports = { frameRoof, trySingleCore, LEN_TOL };
