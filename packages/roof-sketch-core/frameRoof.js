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
const { validateSketch, edgeLoopVertices, edgeMap, resolveFacetBoundary } = require("./topology");
const { planRunFromSlope } = require("./geometry");

const num = (v) => { if (v === "" || v == null) return null; const n = Number(v); return Number.isFinite(n) ? n : null; };
const rnd = (n) => Math.round(Number(n) * 1000) / 1000;
const approxEq = (a, b, tol) => a != null && b != null && Math.abs(Number(a) - Number(b)) <= tol;
const LEN_TOL = 0.5;

// ---- geometry document builder (vertex/edge dedup + measurement-line mapping) ---------------------
function makeBuilder() {
  const verts = []; const vidByKey = {};
  const edges = []; let ei = 0; const usedIds = {};
  const vget = (x, y) => {
    const xr = rnd(x), yr = rnd(y); const key = xr + "|" + yr;
    if (vidByKey[key] != null) return vidByKey[key];
    const id = "fv_" + verts.length; verts.push({ id, x: xr, y: yr }); vidByKey[key] = id; return id;
  };
  const uniq = (base) => { if (usedIds[base] == null) { usedIds[base] = 0; return base; } return `${base}_${++usedIds[base]}`; };
  // Add an edge between two plan points. `line` (a measurement roof line) maps the drawn edge to its
  // authoritative Roof Line; otherwise a derived boundary edge of the given `type` is created.
  const edge = (aPt, bPt, type, line) => {
    const v1 = vget(aPt.x, aPt.y), v2 = vget(bPt.x, bPt.y);
    const existing = edges.find((e) => (e.v1 === v1 && e.v2 === v2) || (e.v1 === v2 && e.v2 === v1));
    if (existing) return existing;
    const drawn = rnd(Math.hypot(bPt.x - aPt.x, bPt.y - aPt.y));
    const e = line
      ? { id: uniq("mse_" + line.id), measurement_edge_id: String(line.id), relational_edge_id: String(line.id),
          v1, v2, type: line.edge_type, confirmed_length_ft: num(line.length_ft), locked: num(line.length_ft) != null, drawn_length_ft: drawn }
      : { id: uniq("fe_" + (ei++)), measurement_edge_id: null, v1, v2, type, confirmed_length_ft: null, locked: false, drawn_length_ft: drawn };
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

// Auto-place each measurement penetration at its assigned facet's centroid as a SUGGESTED starting spot
// (reps only nudge it). position_known stays false + auto_placed:true so it is never treated as an
// authoritative measured position; unassigned/off-plane penetrations keep x/y null (manual).
function autoPlacePenetrations(doc) {
  const centroidByMid = {}; const countByMid = {};
  (doc.facets || []).forEach((f) => {
    const r = resolveFacetBoundary(doc, f);
    const pts = r && r.points;
    if (pts && pts.length >= 3) {
      const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
      const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
      centroidByMid[String(f.measurement_facet_id)] = { x: cx, y: cy };
    }
  });
  doc.penetrations = (doc.penetrations || []).map((p) => {
    const c = centroidByMid[String(p.measurement_facet_id)];
    if (!c) return p;
    const n = (countByMid[p.measurement_facet_id] = (countByMid[p.measurement_facet_id] || 0) + 1) - 1;
    // Spread multiple penetrations on one facet in a small deterministic row so they do not stack.
    const off = n === 0 ? 0 : ((n % 2 ? 1 : -1) * Math.ceil(n / 2) * 1.5);
    return { ...p, x: rnd(c.x + off), y: rnd(c.y), position_known: false, auto_placed: true };
  });
  return doc;
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
  const frame = { L, W, ridgeY, frontMid, backMid, loMid, hiMid };
  return finalize(base, b, facets, resolvedOrder, approximations, "single_core", frame);
}

// ---- finalize: assemble the canonical document + validate --------------------------------------------
function finalize(base, b, facets, resolvedOrder, approximations, method, frame) {
  const doc = createSketchDocument({ structureId: base.structure_id });
  doc.scale = { resolved: true, feetPerUnit: 1, feet_per_unit: 1, method: "roof_framing_solver" };
  doc.vertices = b.verts;
  doc.edges = b.edges;
  doc.facets = facets;
  doc.penetrations = base.document.penetrations;
  doc.generated = base.document.generated;
  autoPlacePenetrations(doc);
  const v = validateSketch(doc);
  return { doc, resolved: resolvedOrder, unresolved: [], approximations: approximations || [], valid: v.valid, validation: v, method, frame };
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
  // This construction is for EQUAL-width arms (ridges meet at one point). An unequal-width L needs true
  // 3D ridge-height reconciliation (the narrow ridge dies into the wide slope) -> defer to the resolver.
  const rV = runOf(V.hip);
  if (rV != null && rV > 0 && Math.abs(rnd(rV * 2) - W) > 1) return null;
  if (VrightE != null && LyE != null && Math.abs((LyE - VrightE) - W) > 1) return null;
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

// ---- Unequal-width projecting cross-gable wing: a real notched host slope + two true valleys ---------
// A main GABLE (2 planes) with one perpendicular gable WING that PROJECTS past the host slope's eave. The
// host slope is NOTCHED and shares two real concave VALLEYS with the wing (a clean, connected, non-
// overlapping planar subdivision — unlike a small dormer, which overlays the slope). Equal pitch; the wing
// must be a genuine wing (>= half the main width) that fits (<= the main width). Position along the wall is
// not measured, so the wing is centred (flagged approximate). Returns null to defer everything else.
function tryCrossGable(base, edgesIn) {
  const planes = base.constraints.planes;
  if (planes.length !== 4) return null;
  const adj = base.constraints.adjacency;
  const ridges = adj.filter((a) => a.edge_type === "ridge");
  const valleys = adj.filter((a) => a.edge_type === "valley" || a.edge_type === "dead_valley");
  const hips = adj.filter((a) => a.edge_type === "hip");
  const other = adj.filter((a) => !["ridge", "valley", "dead_valley"].includes(a.edge_type));
  if (ridges.length !== 2 || valleys.length !== 2 || hips.length || other.length) return null;

  const planeByMid = {}; planes.forEach((p) => { planeByMid[String(p.measurement_facet_id)] = p; });
  const vcount = {}; valleys.forEach((v) => v.facets.map(String).forEach((f) => { vcount[f] = (vcount[f] || 0) + 1; }));
  const hostCands = Object.keys(vcount).filter((f) => vcount[f] === 2);
  if (hostCands.length !== 1) return null;
  const host = hostCands[0];
  const wings = [...new Set(valleys.flatMap((v) => v.facets.map(String)))].filter((f) => f !== host).sort();
  if (wings.length !== 2) return null;
  const mainRidge = ridges.find((r) => r.facets.map(String).includes(host));
  if (!mainRidge) return null;
  const mback = mainRidge.facets.map(String).find((f) => f !== host);
  if (!mback || wings.includes(mback)) return null;
  const wingRidge = ridges.find((r) => { const s = new Set(r.facets.map(String)); return s.has(wings[0]) && s.has(wings[1]); });
  if (!wingRidge) return null;
  if (!wings.every((w) => valleys.some((v) => { const s = new Set(v.facets.map(String)); return s.has(w) && s.has(host); }))) return null;

  const mids = [host, mback, ...wings];
  const pit = mids.map((m) => num(planeByMid[m].pitch_rise));
  if (pit.some((p) => p == null) || pit.some((p) => Math.abs(p - pit[0]) > 0.01)) return null;

  const sharedMids = new Set(adj.map((a) => String(a.measurement_edge_id)));
  const lineById = {}; edgesIn.forEach((e) => { lineById[String(e.id)] = e; });
  const singleEave = (mid) => { const es = planeLinesOfType(edgesIn, mid, "eave", sharedMids); return es.length === 1 ? es[0] : null; };
  const runOf = (mid) => planRunFromSlope(num(planeByMid[mid].width_ft), planeByMid[mid].pitch_rise);

  const rHost = runOf(host); if (rHost == null || !(rHost > 0)) return null;
  const Wm = rnd(rHost * 2);
  const rWing = runOf(wings[0]); if (rWing == null || !(rWing > 0)) return null;
  const Wg = rnd(rWing * 2);
  if (Wg < 0.5 * Wm || Wg > Wm + 0.5) return null; // real wing that fits the host slope, else defer
  const hostEave = singleEave(host);
  const L = hostEave && num(hostEave.length_ft) > 0 ? num(hostEave.length_ft) : num(planeByMid[host].length_ft);
  if (L == null || !(L > Wg)) return null;
  let Lg = num(planeByMid[wings[0]].length_ft); if (Lg == null || !(Lg > 0)) Lg = rnd(Wg);

  const approximations = [{ severity: "warning", code: "approx_wing_position", target_type: "facet", target_id: wings[0],
    message: `Cross-gable wing centred on ${(planeByMid[host] && planeByMid[host].label) || host}; exact position along the wall is approximate.` }];
  const yM = rnd(Wm / 2), hg = rnd(Wg / 2), cx = rnd(L / 2);
  const b = makeBuilder();
  const P = (x, y) => ({ x: rnd(x), y: rnd(y) });
  const flo = P(0, 0), fnl = P(cx - hg, 0), Tp = P(cx, hg), fnr = P(cx + hg, 0), fhi = P(L, 0);
  const rTL = P(0, yM), rTR = P(L, yM), bBL = P(0, Wm), bBR = P(L, Wm);
  const wOutL = P(cx - hg, -Lg), wOutR = P(cx + hg, -Lg), wApex = P(cx, -Lg);

  const vLeftAdj = valleys.find((v) => { const s = new Set(v.facets.map(String)); return s.has(host) && s.has(wings[0]); });
  const vRightAdj = valleys.find((v) => { const s = new Set(v.facets.map(String)); return s.has(host) && s.has(wings[1]); });

  const mRidge = b.edge(rTL, rTR, "ridge", lineById[String(mainRidge.measurement_edge_id)]);
  const eF1 = b.edge(flo, fnl, "eave", hostEave);
  const vL = b.edge(fnl, Tp, "valley", lineById[String(vLeftAdj.measurement_edge_id)]);
  const vR = b.edge(Tp, fnr, "valley", lineById[String(vRightAdj.measurement_edge_id)]);
  const eF2 = b.edge(fnr, fhi, "eave", hostEave);
  const rakeFR = b.edge(fhi, rTR, "rake", null);
  const rakeFL = b.edge(flo, rTL, "rake", null);
  const fFront = facetRecord(planeByMid[host], host, [eF1.id, vL.id, vR.id, eF2.id, rakeFR.id, mRidge.id, rakeFL.id]);

  const rakeBR = b.edge(rTR, bBR, "rake", null);
  const eBack = b.edge(bBR, bBL, "eave", singleEave(mback));
  const rakeBL = b.edge(bBL, rTL, "rake", null);
  const fBack = facetRecord(planeByMid[mback], mback, [mRidge.id, rakeBR.id, eBack.id, rakeBL.id]);

  const wRidge = b.edge(Tp, wApex, "ridge", lineById[String(wingRidge.measurement_edge_id)]);
  const wEaveL = b.edge(wOutL, fnl, "eave", singleEave(wings[0]));
  const gRakeL = b.edge(wApex, wOutL, "rake", null);
  const fWL = facetRecord(planeByMid[wings[0]], wings[0], [wEaveL.id, vL.id, wRidge.id, gRakeL.id]);
  const wEaveR = b.edge(fnr, wOutR, "eave", singleEave(wings[1]));
  const gRakeR = b.edge(wOutR, wApex, "rake", null);
  const fWR = facetRecord(planeByMid[wings[1]], wings[1], [vR.id, wEaveR.id, gRakeR.id, wRidge.id]);

  return finalize(base, b, [fFront, fBack, fWL, fWR], mids, approximations, "cross_gable");
}

// ---- Stage 5: gable dormers seated on a host slope (real valleys; overlaps host in plan) ------------
// A gable dormer = a pair of planes sharing a ridge, each joined to a COMMON host core plane by a valley
// (and no hip). In plan it is drawn as two triangles meeting at the dormer ridge, with the two valleys
// converging where the dormer dies into the host slope. Physically the dormer sits ON the host, so its
// plan polygons OVERLAP the host (a validator WARNING, not an error) — the document is emitted in
// manual_polygon mode so overlapping/independent polygons are allowed.
function classifyDormers(base) {
  const adj = base.constraints.adjacency;
  const ridges = adj.filter((a) => a.edge_type === "ridge");
  const valleys = adj.filter((a) => a.edge_type === "valley" || a.edge_type === "dead_valley");
  const hips = adj.filter((a) => a.edge_type === "hip");
  const dormers = []; const used = new Set();
  const other = (a, x) => a.facets.map(String).find((f) => f !== x);
  for (const r of ridges) {
    const [a, b] = r.facets.map(String);
    if (used.has(a) || used.has(b)) continue;
    if (hips.some((h) => { const s = new Set(h.facets.map(String)); return s.has(a) || s.has(b); })) continue; // dormers have no hips
    const hostsA = new Set(valleys.filter((v) => v.facets.map(String).includes(a)).map((v) => other(v, a)));
    const hostsB = new Set(valleys.filter((v) => v.facets.map(String).includes(b)).map((v) => other(v, b)));
    const common = [...hostsA].filter((h) => hostsB.has(h) && h !== a && h !== b);
    if (common.length !== 1) continue;
    const host = common[0];
    const vA = valleys.find((v) => { const s = new Set(v.facets.map(String)); return s.has(a) && s.has(host); });
    const vB = valleys.find((v) => { const s = new Set(v.facets.map(String)); return s.has(b) && s.has(host); });
    if (!vA || !vB) continue;
    const [left, right] = [a, b].sort();
    dormers.push({ planes: [left, right], host, ridge: r, valleyByPlane: { [a]: vA, [b]: vB } });
    used.add(a); used.add(b);
  }
  if (!dormers.length) return null;
  if (dormers.some((d) => used.has(d.host))) return null; // a dormer hosting another dormer -> too complex
  const coreMids = base.constraints.planes.map((p) => String(p.measurement_facet_id)).filter((m) => !used.has(m));
  return { dormers, coreMids, dormerMids: used };
}

// Restrict `base` (foundation result) to a subset of plane ids for solving the core alone.
function scopeBase(base, coreSet) {
  return {
    ...base,
    constraints: {
      ...base.constraints,
      planes: base.constraints.planes.filter((p) => coreSet.has(String(p.measurement_facet_id))),
      adjacency: base.constraints.adjacency.filter((a) => a.facets.map(String).every((f) => coreSet.has(f))),
    },
  };
}

// Append a dormer's two triangular planes onto an existing doc, seated on the host slope frame.
function seatDormer(doc, ids, dormer, planeByMid, lineById, host, approximations) {
  const [leftMid, rightMid] = dormer.planes;
  const p0 = planeByMid[leftMid];
  const hw = planRunFromSlope(num(p0.width_ft), p0.pitch_rise) || host.L / (host.count + 1) * 0.25 || 3;
  let dd = num(p0.length_ft);
  if (dd == null || !(dd > 0)) dd = host.depth * 0.5;
  const margin = Math.max(host.depth * 0.15, 1);
  dd = Math.min(dd, host.depth - margin * 1.2);
  if (!(dd > 0)) { dd = host.depth * 0.5; }
  const cx = rnd(host.L * (host.index + 1) / (host.count + 1));
  const yf = rnd(host.eaveY + host.up * margin);
  const yb = rnd(yf + host.up * dd);
  const P = (x, y) => ({ x: rnd(x), y: rnd(y) });
  const A = P(cx, yf), FL = P(cx - hw, yf), FR = P(cx + hw, yf), PK = P(cx, yb);

  const vid = (pt) => { const id = `dv_${ids.v++}`; doc.vertices.push({ id, x: pt.x, y: pt.y }); return id; };
  const idA = vid(A), idFL = vid(FL), idFR = vid(FR), idPK = vid(PK);
  const edge = (v1, v2, type, line, a, b) => {
    const drawn = rnd(Math.hypot(b.x - a.x, b.y - a.y));
    const e = line
      ? { id: `mse_${line.id}`, measurement_edge_id: String(line.id), relational_edge_id: String(line.id), v1, v2, type: line.edge_type, confirmed_length_ft: num(line.length_ft), locked: num(line.length_ft) != null, drawn_length_ft: drawn }
      : { id: `de_${ids.e++}`, measurement_edge_id: null, v1, v2, type, confirmed_length_ft: null, locked: false, drawn_length_ft: drawn };
    doc.edges.push(e); return e;
  };
  const ridgeLine = lineById[String(dormer.ridge.measurement_edge_id)];
  const valLeft = lineById[String(dormer.valleyByPlane[leftMid].measurement_edge_id)];
  const valRight = lineById[String(dormer.valleyByPlane[rightMid].measurement_edge_id)];
  const eRidge = edge(idA, idPK, "ridge", ridgeLine, A, PK);
  const eEaveL = edge(idA, idFL, "eave", null, A, FL);
  const eValL = edge(idFL, idPK, "valley", valLeft, FL, PK);
  const eEaveR = edge(idA, idFR, "eave", null, A, FR);
  const eValR = edge(idFR, idPK, "valley", valRight, FR, PK);
  doc.facets.push({ ...facetRecord(planeByMid[leftMid], leftMid, [eEaveL.id, eValL.id, eRidge.id]), vertexIds: [idA, idFL, idPK] });
  doc.facets.push({ ...facetRecord(planeByMid[rightMid], rightMid, [eEaveR.id, eValR.id, eRidge.id]), vertexIds: [idA, idFR, idPK] });
  approximations.push({ severity: "warning", code: "approx_dormer_position", target_type: "facet", target_id: leftMid,
    message: `Dormer ${(planeByMid[leftMid] && planeByMid[leftMid].label) || leftMid}/${(planeByMid[rightMid] && planeByMid[rightMid].label) || rightMid} seated on ${(planeByMid[host] && planeByMid[host].label) || host}; exact position along the slope is approximate.` });
}

function frameWithDormers(base, edgesIn, cls) {
  const coreSet = new Set(cls.coreMids);
  const coreBase = scopeBase(base, coreSet);
  const coreEdges = edgesIn.filter((e) => coreSet.has(String(e.facet_id)) && (e.facet_id_secondary == null || coreSet.has(String(e.facet_id_secondary))));
  const core = trySingleCore(coreBase, coreEdges); // dormers currently seat only on a single-core host
  if (!core || !core.frame) return null;
  const frame = core.frame;
  const planeByMid = {}; base.constraints.planes.forEach((p) => { planeByMid[String(p.measurement_facet_id)] = p; });
  const lineById = {}; edgesIn.forEach((e) => { lineById[String(e.id)] = e; });
  const doc = core.doc;
  const approximations = (core.approximations || []).slice();

  // Group dormers by host; seat each, spread along the host eave.
  const byHost = {}; cls.dormers.forEach((d) => (byHost[d.host] = byHost[d.host] || []).push(d));
  const ids = { v: 0, e: 0 };
  let unresolved = [];
  Object.keys(byHost).sort().forEach((hostMid) => {
    let eaveY, up, depth;
    if (hostMid === frame.frontMid) { eaveY = 0; up = 1; depth = frame.ridgeY; }
    else if (hostMid === frame.backMid) { eaveY = frame.W; up = -1; depth = frame.W - frame.ridgeY; }
    else { unresolved = unresolved.concat(byHost[hostMid].flatMap((d) => d.planes)); return; } // host is a hip end -> defer these
    const list = byHost[hostMid].slice().sort((a, b) => (a.planes[0] < b.planes[0] ? -1 : 1));
    list.forEach((d, i) => seatDormer(doc, ids, d, planeByMid, lineById, { L: frame.L, eaveY, up, depth, index: i, count: list.length }, approximations));
  });

  // Overlapping dormers-on-host are honest overlapping polygons -> manual_polygon mode. Populate vertexIds
  // on every facet (core facets from their edge loop) so the manual-polygon boundary resolver has them.
  const emap = edgeMap(doc);
  doc.facets.forEach((f) => {
    if (!f.vertexIds || !f.vertexIds.length) {
      const seq = edgeLoopVertices((f.edgeIds || []).map((id) => emap[id]).filter(Boolean));
      if (seq) f.vertexIds = seq;
    }
  });
  doc.edit_mode = "manual_polygon";

  autoPlacePenetrations(doc);
  const v = validateSketch(doc);
  const resolved = core.resolved.concat(cls.dormers.flatMap((d) => d.planes).filter((m) => !unresolved.includes(m)));
  return { doc, resolved, unresolved, approximations, valid: v.valid, validation: v, method: "single_core_with_dormers", frame };
}

// Public entry. Returns null to DEFER (caller falls back) when the topology is not yet solved.
function frameRoof(base, edgesIn, resolutions) {
  if (!base || !base.constraints || !Array.isArray(base.constraints.planes)) return null;
  const edges = (edgesIn || []).filter((e) => e && e.id != null);
  const cross = tryCrossGable(base, edges);
  if (cross && cross.valid) return cross;
  const cls = classifyDormers(base);
  if (cls) { const withDormers = frameWithDormers(base, edges, cls); if (withDormers && withDormers.valid) return withDormers; }
  const single = trySingleCore(base, edges);
  if (single) return single;
  const l = tryLRoof(base, edges);
  if (l && l.valid) return l;
  return null;
}

module.exports = { frameRoof, trySingleCore, LEN_TOL };
