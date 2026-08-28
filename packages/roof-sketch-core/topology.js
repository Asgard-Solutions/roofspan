"use strict";
// Topology & structural validation for the sketch graph.
const { distance, segmentsCross } = require("./geometry");
const { normalizeSketchDocument } = require("./schema");

function vertexMap(doc) {
  const m = {};
  (doc.vertices || []).forEach((v) => { m[v.id] = v; });
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

// Ordered [x,y] points for a facet loop, from its vertexIds.
function facetPoints(doc, facet, vmap) {
  const ids = facet.vertexIds || [];
  const pts = ids.map((id) => vmap[id]).filter(Boolean).map((v) => [Number(v.x), Number(v.y)]);
  return pts;
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

function validateSketch(input) {
  const doc = normalizeSketchDocument(input);
  const vmap = vertexMap(doc);
  const errors = [];
  const warnings = [];

  // zero-length edges
  (doc.edges || []).forEach((e) => {
    const a = vmap[e.v1], b = vmap[e.v2];
    if (a && b && distance([a.x, a.y], [b.x, b.y]) < 1e-6) {
      errors.push({ code: "zero_length_edge", edge_id: e.id, message: "Edge has zero length" });
    }
    if (!a || !b) {
      errors.push({ code: "dangling_edge", edge_id: e.id, message: "Edge references a missing vertex" });
    }
  });

  // per-facet loop checks
  (doc.facets || []).forEach((f) => {
    const pts = facetPoints(doc, f, vmap);
    if (pts.length < 3) {
      errors.push({ code: "open_facet_loop", facet_id: f.id, message: "Facet has fewer than 3 vertices" });
      return;
    }
    if (polygonSelfIntersects(pts)) {
      errors.push({ code: "self_intersection", facet_id: f.id, message: "Facet outline crosses itself" });
    }
  });

  // soft warnings: facets sharing no edges in connected mode (possible gap)
  if (doc.edit_mode === "connected_graph" && (doc.facets || []).length >= 2) {
    const shared = findSharedEdges(doc);
    if (shared.length === 0) {
      warnings.push({ code: "possible_gap", message: "Connected roof has multiple facets but no shared edges" });
    }
  }

  return { valid: errors.length === 0, errors, warnings };
}

module.exports = { findSharedEdges, validateSketch, polygonSelfIntersects, facetPoints, vertexMap };
