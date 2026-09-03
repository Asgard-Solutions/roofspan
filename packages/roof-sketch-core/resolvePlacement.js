"use strict";
// Resolution-driven placement for CONNECTED complex roofs (Office + Field share this identically).
//
// When measurements establish adjacency (Hip/Valley/Ridge between planes) but do not uniquely establish
// WHICH SIDE a plane sits on, the deterministic generator refuses to guess. This module lets the user
// resolve those choices explicitly: it emits a placement scaffold (per unresolved plane: its parent, the
// junction type, and the parent's four sides to choose from) and, given the user's side choices, lays the
// roof out deterministically by attaching each plane as a rectangle to the chosen side of its parent.
//
// Never fabricates dimensions silently: each plane's plan depth comes from its measured sloped Width
// (deprojected by its own pitch) or its Length; where measurements under-constrain a plane the layout is
// still drawn at the resolved position and an APPROXIMATION diagnostic is emitted (never a silent guess).

const { createSketchDocument } = require("./schema");
const { planRunFromSlope } = require("./geometry");

const num = (v) => { if (v === "" || v == null) return null; const n = Number(v); return Number.isFinite(n) ? n : null; };
const SIDES = ["N", "E", "S", "W"];
const SIDE_LABEL = { N: "North", E: "East", S: "South", W: "West" };
const rnd = (n) => Math.round(Number(n) * 1000) / 1000;

function planeDepth(f) {
  const d = planRunFromSlope(num(f && f.width_ft), f && f.pitch_rise);
  if (d != null && d > 0) return { v: rnd(d), approx: false };
  const L = num(f && f.length_ft);
  if (L != null && L > 0) return { v: rnd(L), approx: true };
  return { v: null, approx: true };
}
function planeAlong(f) {
  const L = num(f && f.length_ft);
  if (L != null && L > 0) return rnd(L);
  const d = planRunFromSlope(num(f && f.width_ft), f && f.pitch_rise);
  return d != null && d > 0 ? rnd(d) : null;
}

// Deterministic BFS scaffold from the largest-area plane. parent = first-discovered neighbour.
function planPlacement(base) {
  const planes = base.constraints.planes.map((p) => ({
    id: String(p.measurement_facet_id), label: p.label || String(p.measurement_facet_id), area: num(p.area_sqft) || 0,
  }));
  const byId = {}; planes.forEach((p) => { byId[p.id] = p; });
  const adj = {}; planes.forEach((p) => { adj[p.id] = []; });
  base.constraints.adjacency.forEach((a) => {
    const [x, y] = a.facets.map(String);
    if (byId[x] && byId[y]) {
      adj[x].push({ o: y, type: a.edge_type, edge: String(a.measurement_edge_id) });
      adj[y].push({ o: x, type: a.edge_type, edge: String(a.measurement_edge_id) });
    }
  });
  Object.values(adj).forEach((l) => l.sort((m, n) => (m.o < n.o ? -1 : m.o > n.o ? 1 : 0)));
  const anchor = planes.slice().sort((a, b) => (b.area - a.area) || (a.id < b.id ? -1 : 1))[0];
  const steps = []; const seen = new Set();
  if (anchor) {
    seen.add(anchor.id); const q = [anchor.id];
    while (q.length) {
      const cur = q.shift();
      for (const nb of adj[cur]) {
        if (!seen.has(nb.o)) { seen.add(nb.o); steps.push({ plane: nb.o, parent: cur, viaType: nb.type, viaEdge: nb.edge }); q.push(nb.o); }
      }
    }
  }
  const title = (t) => (t === "dead_valley" ? "Dead Valley" : String(t || "").charAt(0).toUpperCase() + String(t || "").slice(1));
  const requests = steps.map((s) => ({
    plane: s.plane, label: byId[s.plane].label, parent: s.parent, parentLabel: byId[s.parent].label,
    via_type: s.viaType, via_edge: s.viaEdge,
    prompt: `Which side of ${byId[s.parent].label} does ${byId[s.plane].label} sit on? (${title(s.viaType)} junction)`,
    options: SIDES.map((sd) => ({ key: sd, label: `${byId[s.parent].label} — ${SIDE_LABEL[sd]} side` })),
  }));
  return { anchor_id: anchor ? anchor.id : null, steps, requests, plane_ids: planes.map((p) => p.id) };
}

// Cardinal sides of an AXIS-ALIGNED rectangle, keyed to the SCREEN compass. The canvas is SVG (y grows
// DOWN), so North = top = min y. This keeps the user's N/E/S/W choice matching what they see drawn.
function cardinalSides(corners) {
  const xs = corners.map((c) => c.x), ys = corners.map((c) => c.y);
  const minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys);
  const at = (x, y) => corners.find((c) => Math.abs(c.x - x) < 1e-6 && Math.abs(c.y - y) < 1e-6) || { x, y };
  const NW = at(minx, miny), NE = at(maxx, miny), SW = at(minx, maxy), SE = at(maxx, maxy);
  return {
    N: { a: NW, b: NE, n: { x: 0, y: -1 } },
    S: { a: SW, b: SE, n: { x: 0, y: 1 } },
    E: { a: NE, b: SE, n: { x: 1, y: 0 } },
    W: { a: NW, b: SW, n: { x: -1, y: 0 } },
  };
}
// Place an axis-aligned rectangle from base segment a->b, extending by depth along outward normal n.
function placeRect(a, b, n, depth) {
  const fb = { x: rnd(b.x + n.x * depth), y: rnd(b.y + n.y * depth) };
  const fa = { x: rnd(a.x + n.x * depth), y: rnd(a.y + n.y * depth) };
  return cardinalSides([a, b, fb, fa]);
}

// Lay the roof out from explicit side resolutions. resolutions: array/map of { plane -> side key N/E/S/W }.
function layoutFromResolutions(base, edgesIn, resolutions) {
  const scaffold = planPlacement(base);
  const planeById = {}; base.constraints.planes.forEach((p) => { planeById[String(p.measurement_facet_id)] = p; });
  const lineById = {}; (edgesIn || []).forEach((e) => { if (e && e.id != null) lineById[String(e.id)] = e; });
  const resMap = {};
  if (Array.isArray(resolutions)) resolutions.forEach((r) => { if (r && r.plane != null && r.side) resMap[String(r.plane)] = String(r.side).toUpperCase(); });
  else if (resolutions && typeof resolutions === "object") Object.keys(resolutions).forEach((k) => { resMap[String(k)] = String(resolutions[k]).toUpperCase(); });

  const verts = []; const vidByKey = {};
  const vget = (x, y) => {
    const xr = rnd(x), yr = rnd(y); const key = xr + "|" + yr;
    if (vidByKey[key] != null) return vidByKey[key];
    const id = "rv_" + verts.length; verts.push({ id, x: xr, y: yr }); vidByKey[key] = id; return id;
  };
  const vc = (pt) => ({ x: pt.x, y: pt.y, id: vget(pt.x, pt.y) });

  const placed = {};             // planeId -> { sides: {K: {a,b,n}} }
  const approximations = [];
  const resolved = []; const unresolved = [];
  const edges = []; const facets = [];
  let ei = 0;
  const pushEdge = (aPt, bPt, type, line) => {
    const v1 = vget(aPt.x, aPt.y), v2 = vget(bPt.x, bPt.y);
    const existing = edges.find((e) => (e.v1 === v1 && e.v2 === v2) || (e.v1 === v2 && e.v2 === v1));
    if (existing) return existing;
    const drawn = rnd(Math.hypot(bPt.x - aPt.x, bPt.y - aPt.y));
    const e = line
      ? { id: "mse_" + line.id, measurement_edge_id: String(line.id), relational_edge_id: String(line.id), v1, v2, type: line.edge_type, confirmed_length_ft: num(line.length_ft), locked: num(line.length_ft) != null, drawn_length_ft: drawn }
      : { id: "re_" + (ei++), measurement_edge_id: null, v1, v2, type, confirmed_length_ft: null, locked: false, drawn_length_ft: drawn };
    edges.push(e); return e;
  };
  const addFacet = (mid, sideMap, sharedKey, sharedEdge) => {
    const p = planeById[mid];
    const ids = [];
    for (const k of ["N", "E", "S", "W"]) {
      if (k === sharedKey && sharedEdge) { ids.push(sharedEdge.id); continue; }
      const type = (k === "E" || k === "W") ? "rake" : "eave";
      ids.push(pushEdge(sideMap[k].a, sideMap[k].b, type, null).id);
    }
    facets.push({ id: "rf_" + mid, measurement_facet_id: mid, relational_facet_id: mid, label: (p && p.label) || "F",
      pitch_rise: num(p && p.pitch_rise), confirmed_area_sqft: num(p && p.area_sqft), orientation_azimuth: num(p && p.orientation_azimuth),
      roof_material: null, edgeIds: ids, vertexIds: [] });
  };

  // A hip/valley-end plane is a mitered TRIANGLE: base along the shared junction, apex at the outward
  // midpoint (the two rising edges meet at a point instead of a flat rectangle -> valley-miter/hip fidelity).
  const placeTriangleFacet = (mid, seg, depth, viaEdge, viaType) => {
    const a = { x: seg.a.x, y: seg.a.y }, b = { x: seg.b.x, y: seg.b.y }, n = seg.n;
    const apex = { x: rnd((a.x + b.x) / 2 + n.x * depth), y: rnd((a.y + b.y) / 2 + n.y * depth) };
    const base = pushEdge(a, b, viaType, lineById[viaEdge] || null);
    const eR = pushEdge(b, apex, viaType, null);
    const eL = pushEdge(a, apex, viaType, null);
    const p = planeById[mid];
    facets.push({ id: "rf_" + mid, measurement_facet_id: mid, relational_facet_id: mid, label: (p && p.label) || "F",
      pitch_rise: num(p && p.pitch_rise), confirmed_area_sqft: num(p && p.area_sqft), orientation_azimuth: num(p && p.orientation_azimuth),
      roof_material: null, edgeIds: [base.id, eR.id, eL.id], vertexIds: [] });
    return cardinalSides([a, b, apex]);
  };

  // Anchor placed as an axis-aligned rectangle: x in [0, along], y in [0, depth] (North = top).
  const anchorId = scaffold.anchor_id;
  if (!anchorId) return { error: "no_anchor" };
  const af = planeById[anchorId];
  const aLong = planeAlong(af); const aDepthInfo = planeDepth(af); const aDepth = aDepthInfo.v;
  if (aLong == null || aDepth == null) return { error: "anchor_underconstrained", anchor: anchorId };
  const aSides = cardinalSides([{ x: 0, y: 0 }, { x: aLong, y: 0 }, { x: aLong, y: aDepth }, { x: 0, y: aDepth }]);
  placed[anchorId] = { sides: aSides };
  addFacet(anchorId, aSides, null, null);
  resolved.push(anchorId);
  if (aDepthInfo.approx) approximations.push({ severity: "warning", code: "approx_plane_depth", target_type: "facet", target_id: anchorId,
    message: `${(af && af.label) || anchorId}: depth approximated from Length (no sloped Width + pitch).` });

  for (const step of scaffold.steps) {
    const mid = step.plane; const par = placed[step.parent];
    const side = resMap[mid];
    if (!par) { unresolved.push(mid); continue; }
    if (!side || !par.sides[side]) { unresolved.push(mid); continue; }
    const f = planeById[mid]; const dInfo = planeDepth(f); const depth = dInfo.v;
    if (depth == null) { unresolved.push(mid); approximations.push({ severity: "error", code: "insufficient_dimensions", target_type: "facet", target_id: mid,
      message: `${(f && f.label) || mid}: needs a sloped Width + pitch (or a Length) to size its depth.` }); continue; }
    const seg = par.sides[side];
    if (step.viaType === "hip" || step.viaType === "valley" || step.viaType === "dead_valley") {
      // Hip / valley junctions -> mitered triangle (base = shared junction, two edges rise to an apex).
      const sides = placeTriangleFacet(mid, seg, depth, step.viaEdge, step.viaType);
      placed[mid] = { sides };
    } else {
      const rect = placeRect({ x: seg.a.x, y: seg.a.y }, { x: seg.b.x, y: seg.b.y }, seg.n, depth);
      // Child's side facing the parent (outward normal opposes the parent side's) carries the shared junction.
      const oppKey = (seg.n.y < 0) ? "S" : (seg.n.y > 0) ? "N" : (seg.n.x > 0) ? "W" : "E";
      const shared = pushEdge(rect[oppKey].a, rect[oppKey].b, step.viaType, lineById[step.viaEdge] || null);
      placed[mid] = { sides: rect };
      addFacet(mid, rect, oppKey, shared);
    }
    resolved.push(mid);
    if (dInfo.approx) approximations.push({ severity: "warning", code: "approx_plane_depth", target_type: "facet", target_id: mid,
      message: `${(f && f.label) || mid}: depth approximated from Length (no sloped Width + pitch).` });
  }

  const doc = createSketchDocument({ structureId: base.structure_id });
  doc.scale = { resolved: true, feetPerUnit: 1, feet_per_unit: 1, method: "resolved_placement" };
  doc.vertices = verts;
  doc.edges = edges;
  doc.facets = facets;
  doc.penetrations = base.document.penetrations;
  doc.generated = base.document.generated;
  doc.placement_resolutions = scaffold.steps.filter((s) => resMap[s.plane]).map((s) => ({ plane: s.plane, parent: s.parent, side: resMap[s.plane] }));
  return { doc, resolved, unresolved, approximations, scaffold };
}

module.exports = { planPlacement, layoutFromResolutions };
