"use strict";
// Topology & structural validation for the sketch graph.
//
// Authority rule (connected_graph mode): the ordered `edgeIds` loop is the single authoritative
// boundary definition for a facet. `vertexIds`, when present, must describe the SAME cyclic loop
// (rotation/reflection allowed) or the facet is rejected — two independent boundary definitions are
// never permitted. In manual_polygon mode independent polygons are allowed, so disconnected
// components are not, by themselves, errors.
const { distance, segmentsCross } = require("./geometry");
const { normalizeSketchDocument } = require("./schema");

const EPS = 1e-9;

function vertexMap(doc) {
  const m = {};
  (doc.vertices || []).forEach((v) => { m[v.id] = v; });
  return m;
}

function edgeMap(doc) {
  const m = {};
  (doc.edges || []).forEach((e) => { m[e.id] = e; });
  return m;
}

// Edges referenced by two or more facets are shared roof lines (ridge/hip/valley).
function findSharedEdges(doc) {
  const counts = {};
  (doc.facets || []).forEach((f) => {
    (f.edgeIds || []).forEach((eid) => {
      counts[eid] = counts[eid] || [];
      counts[eid].push(f.id);
    });
  });
  return Object.keys(counts)
    .filter((eid) => counts[eid].length >= 2)
    .map((eid) => ({ edgeId: eid, facetIds: counts[eid] }))
    .sort((a, b) => (a.edgeId < b.edgeId ? -1 : 1));
}

// Ordered [x,y] points for a facet loop, from an explicit vertex-id sequence.
function loopPoints(ids, vmap) {
  return (ids || []).map((id) => vmap[id]).filter(Boolean).map((v) => [Number(v.x), Number(v.y)]);
}

// Legacy helper (kept for callers): ordered points from a facet's vertexIds.
function facetPoints(doc, facet, vmap) {
  return loopPoints(facet.vertexIds || [], vmap);
}

// Derive the ordered vertex loop from an ordered list of edge objects.
// Returns the vertex-id sequence (length === edges.length) for a single closed simple cycle,
// or null when the ordered edges do not thread a closed connected loop.
function edgeLoopVertices(edges) {
  const n = edges.length;
  if (n < 3) return null;
  const deg = {};
  for (const e of edges) {
    if (e.v1 == null || e.v2 == null) return null;
    deg[e.v1] = (deg[e.v1] || 0) + 1;
    deg[e.v2] = (deg[e.v2] || 0) + 1;
  }
  // A single simple cycle over n edges has exactly n distinct vertices, each of degree 2.
  if (Object.keys(deg).length !== n) return null;
  if (Object.values(deg).some((d) => d !== 2)) return null;

  const e0 = edges[0], e1 = edges[1];
  let start, cur;
  if (e0.v1 === e1.v1 || e0.v1 === e1.v2) { start = e0.v2; cur = e0.v1; }
  else if (e0.v2 === e1.v1 || e0.v2 === e1.v2) { start = e0.v1; cur = e0.v2; }
  else return null; // first two edges are not adjacent in the given order
  const seq = [start, cur];
  for (let i = 1; i < n; i++) {
    const e = edges[i];
    let nxt;
    if (e.v1 === cur) nxt = e.v2;
    else if (e.v2 === cur) nxt = e.v1;
    else return null; // ordered edges do not connect end-to-end
    if (i < n - 1) { seq.push(nxt); cur = nxt; }
    else if (nxt !== start) return null; // last edge must close back to the start
  }
  return seq; // length n
}

// Two id-cycles are equal if one is a rotation of the other or of its reversal.
function sameCycle(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  const n = a.length;
  const rotEq = (arr) => {
    for (let s = 0; s < n; s++) {
      let ok = true;
      for (let i = 0; i < n; i++) { if (arr[(s + i) % n] !== b[i]) { ok = false; break; } }
      if (ok) return true;
    }
    return false;
  };
  return rotEq(a) || rotEq(a.slice().reverse());
}

// A closed polygon self-intersects if any pair of non-adjacent edges cross.
function polygonSelfIntersects(points) {
  const n = points.length;
  if (n < 4) return false;
  for (let i = 0; i < n; i++) {
    const a1 = points[i], a2 = points[(i + 1) % n];
    for (let j = i + 1; j < n; j++) {
      if (j === i) continue;
      if (i === (j + 1) % n || j === (i + 1) % n) continue; // adjacent share a vertex
      const b1 = points[j], b2 = points[(j + 1) % n];
      if (segmentsCross(a1, a2, b1, b2)) return true;
    }
  }
  return false;
}

function polygonSignedArea(points) {
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    sum += x1 * y2 - x2 * y1;
  }
  return sum / 2;
}

function cross3(o, a, b) {
  return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
}

function pointOnSegment(p, a, b) {
  if (Math.abs(cross3(a, b, p)) > 1e-6) return false;
  const dot = (p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1]);
  const len2 = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2;
  return dot >= -EPS && dot <= len2 + EPS;
}

function pointOnBoundary(p, poly) {
  for (let i = 0; i < poly.length; i++) {
    if (pointOnSegment(p, poly[i], poly[(i + 1) % poly.length])) return true;
  }
  return false;
}

// Strictly inside (points ON the boundary are NOT considered inside — so shared edges never
// read as an overlap).
function pointStrictlyInside(p, poly) {
  if (poly.length < 3) return false;
  if (pointOnBoundary(p, poly)) return false;
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
    const intersect = ((yi > p[1]) !== (yj > p[1])) &&
      (p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

// Interiors intersect (positive-area overlap). Touching along a shared edge/vertex is NOT overlap.
function polygonsOverlap(A, B) {
  if (A.length < 3 || B.length < 3) return false;
  for (let i = 0; i < A.length; i++) {
    const a1 = A[i], a2 = A[(i + 1) % A.length];
    for (let j = 0; j < B.length; j++) {
      const b1 = B[j], b2 = B[(j + 1) % B.length];
      if (segmentsCross(a1, a2, b1, b2)) return true;
    }
  }
  if (A.some((p) => pointStrictlyInside(p, B))) return true;
  if (B.some((p) => pointStrictlyInside(p, A))) return true;
  return false;
}

// Do two segments lie on the same line and overlap along more than a single point?
function segmentsCollinearOverlap(a1, a2, b1, b2) {
  if (Math.abs(cross3(a1, a2, b1)) > 1e-6 || Math.abs(cross3(a1, a2, b2)) > 1e-6) return false;
  const dx = a2[0] - a1[0], dy = a2[1] - a1[1];
  const len2 = dx * dx + dy * dy;
  if (len2 < EPS) return false;
  const proj = (p) => ((p[0] - a1[0]) * dx + (p[1] - a1[1]) * dy) / len2;
  const tb = [proj(b1), proj(b2)].sort((x, y) => x - y);
  const lo = Math.max(0, tb[0]);
  const hi = Math.min(1, tb[1]);
  return (hi - lo) * Math.sqrt(len2) > 1e-6; // overlap of positive length
}

function facetSegments(pts) {
  const segs = [];
  for (let i = 0; i < pts.length; i++) segs.push([pts[i], pts[(i + 1) % pts.length]]);
  return segs;
}

// Union-find over facets: connected via shared edge ids.
function facetComponents(doc) {
  const facets = doc.facets || [];
  const parent = facets.map((_, i) => i);
  const find = (i) => { while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i]; } return i; };
  const union = (i, j) => { parent[find(i)] = find(j); };
  const idxById = {};
  facets.forEach((f, i) => { idxById[f.id] = i; });
  findSharedEdges(doc).forEach((s) => {
    for (let k = 1; k < s.facetIds.length; k++) union(idxById[s.facetIds[0]], idxById[s.facetIds[k]]);
  });
  const roots = new Set(facets.map((_, i) => find(i)));
  return roots.size;
}

// SINGLE authoritative boundary resolver. Both validation AND the proposal engine MUST use this so
// there is only one geometry interpretation.
//   connected_graph -> ordered edgeIds loop is authoritative (vertexIds are only a redundant mirror)
//   manual_polygon   -> vertexIds are the polygon boundary
// Returns { points, vertexIds, error } where error (or null) is a hard structural failure.
function resolveFacetBoundary(doc, facet, vmap, emap) {
  vmap = vmap || vertexMap(doc);
  emap = emap || edgeMap(doc);
  const connected = doc.edit_mode === "connected_graph";
  const hasEdgeIds = Array.isArray(facet.edgeIds) && facet.edgeIds.length > 0;
  if (connected) {
    if (!hasEdgeIds) {
      return { points: [], vertexIds: [], error: { code: "facet_missing_edges",
        message: "Connected-graph facet must define an authoritative ordered edgeIds boundary" } };
    }
    const missing = facet.edgeIds.filter((eid) => !emap[eid]);
    if (missing.length) {
      return { points: [], vertexIds: [], error: { code: "broken_edge_reference", edge_ids: missing,
        message: "Facet references an edge that does not exist" } };
    }
    const derived = edgeLoopVertices(facet.edgeIds.map((eid) => emap[eid]));
    if (!derived) {
      return { points: [], vertexIds: [], error: { code: "open_facet_loop",
        message: "Facet edge list does not form a single closed connected loop" } };
    }
    // The edge loop is authoritative. Redundant vertexIds, if supplied, must match it exactly.
    let error = null;
    if (Array.isArray(facet.vertexIds) && facet.vertexIds.length && !sameCycle(derived, facet.vertexIds)) {
      error = { code: "facet_boundary_mismatch", message: "Facet vertexIds contradict the authoritative edge loop" };
    }
    return { points: loopPoints(derived, vmap), vertexIds: derived, error }; // points always from the edge loop
  }
  // manual_polygon: vertexIds are the boundary; no edge-graph connectivity required.
  const ids = facet.vertexIds || [];
  return { points: loopPoints(ids, vmap), vertexIds: ids, error: null };
}

function validateSketch(input) {
  const doc = normalizeSketchDocument(input);
  const vmap = vertexMap(doc);
  const emap = edgeMap(doc);
  const connected = doc.edit_mode === "connected_graph";
  const errors = [];
  const warnings = [];
  const push = (arr, o) => arr.push(o);

  // --- edge-level integrity ---
  (doc.edges || []).forEach((e) => {
    const a = vmap[e.v1], b = vmap[e.v2];
    if (!a || !b) {
      push(errors, { code: "dangling_edge", edge_id: e.id, message: "Edge references a missing vertex" });
      return;
    }
    if (distance([a.x, a.y], [b.x, b.y]) < 1e-6) {
      push(errors, { code: "zero_length_edge", edge_id: e.id, message: "Edge has zero length" });
    }
  });

  // --- per-facet boundary resolution + loop/geometry checks (single authoritative resolver) ---
  const facetPolys = {}; // facet.id -> ordered [x,y] points (only for structurally valid facets)
  (doc.facets || []).forEach((f) => {
    const res = resolveFacetBoundary(doc, f, vmap, emap);
    if (res.error) {
      push(errors, Object.assign({ facet_id: f.id }, res.error));
      return;
    }
    const pts = res.points;
    if (pts.length < 3) {
      push(errors, { code: "open_facet_loop", facet_id: f.id, message: "Facet has fewer than 3 vertices" });
      return;
    }
    if (polygonSelfIntersects(pts)) {
      push(errors, { code: "self_intersection", facet_id: f.id, message: "Facet outline crosses itself" });
      return;
    }
    if (Math.abs(polygonSignedArea(pts)) <= 1e-6) {
      push(errors, { code: "non_positive_area", facet_id: f.id, message: "Facet has an impossible (non-positive) area" });
      return;
    }
    facetPolys[f.id] = pts;
  });

  // --- cross-facet structural checks (only structurally valid facets) ---
  const validFacets = (doc.facets || []).filter((f) => facetPolys[f.id]);

  // Duplicate facet: two facets whose CANONICAL resolved polygon geometry is identical (same set of
  // coordinates). Works regardless of how the boundary was expressed — connected edge loops with no
  // vertexIds, or manual polygons built from different vertex ids at the same coordinates.
  const r6 = (x) => Math.round(x * 1e6) / 1e6;
  const polyKey = (pts) => pts.map((p) => `${r6(p[0])},${r6(p[1])}`).sort().join("|");
  const seenPoly = {};
  for (const f of validFacets) {
    const key = polyKey(facetPolys[f.id]);
    if (seenPoly[key] !== undefined) {
      push(errors, { code: "duplicate_facet", facet_ids: [seenPoly[key], f.id],
        message: "Two facets describe the same polygon" });
    } else {
      seenPoly[key] = f.id;
    }
  }

  // Disconnected components are a hard error ONLY in connected_graph mode.
  if (connected && validFacets.length >= 2 && validFacets.length === (doc.facets || []).length) {
    if (facetComponents(doc) > 1) {
      push(errors, { code: "disconnected_component", message: "Connected-graph facets are not all joined by shared edges" });
    }
  }

  // Recoverable geometry anomalies (warnings, never blocks): overlaps and unstitched seams (gaps).
  for (let i = 0; i < validFacets.length; i++) {
    for (let j = i + 1; j < validFacets.length; j++) {
      const a = validFacets[i], b = validFacets[j];
      const pa = facetPolys[a.id], pb = facetPolys[b.id];
      if (polygonsOverlap(pa, pb)) {
        push(warnings, { code: "possible_overlap", facet_ids: [a.id, b.id], message: "Facet interiors overlap" });
      }
      // A seam (touching along a line) without a shared edge id suggests a gap that should be stitched.
      const shareEdge = (a.edgeIds || []).some((e) => (b.edgeIds || []).includes(e));
      if (connected && !shareEdge) {
        const segsA = facetSegments(pa), segsB = facetSegments(pb);
        let seam = false;
        for (const s1 of segsA) { for (const s2 of segsB) { if (segmentsCollinearOverlap(s1[0], s1[1], s2[0], s2[1])) { seam = true; break; } } if (seam) break; }
        if (seam) push(warnings, { code: "possible_gap", facet_ids: [a.id, b.id],
          message: "Facets touch along a line but do not share an edge (possible gap/seam)" });
      }
    }
  }

  return { valid: errors.length === 0, errors, warnings };
}

module.exports = {
  findSharedEdges, validateSketch, polygonSelfIntersects, facetPoints, vertexMap, edgeMap,
  edgeLoopVertices, sameCycle, polygonsOverlap, segmentsCollinearOverlap, pointStrictlyInside,
  facetComponents, loopPoints, resolveFacetBoundary,
};
