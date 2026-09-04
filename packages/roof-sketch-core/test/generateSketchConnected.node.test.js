"use strict";
const assert = require("assert");
const { generateSketchGeometry, validateSketch } = require("..");

let n = 0;
function ok(name) { n++; console.log("  \u2713 " + name); }

// -------------------------------------------------------------------------------------------------
// Standard hip: rectangle 48 x 32, ridge = 48-32 = 16. Trapezoids T1/T2 (long eaves 48), triangles
// P3/P4 (short eaves 32). Adjacency: ridge(T1,T2) + 4 hips (T1-P3, T1-P4, T2-P3, T2-P4). Pitch 6 all.
// -------------------------------------------------------------------------------------------------
function basicHip() {
  return {
    structure: { id: "H" },
    facets: [
      { id: "T1", structure_id: "H", facet_label: "Front", pitch_rise: 6, area_sqft: 800, sort: 0 },
      { id: "T2", structure_id: "H", facet_label: "Back", pitch_rise: 6, area_sqft: 800, sort: 1 },
      { id: "P3", structure_id: "H", facet_label: "Left", pitch_rise: 6, area_sqft: 300, sort: 2 },
      { id: "P4", structure_id: "H", facet_label: "Right", pitch_rise: 6, area_sqft: 300, sort: 3 },
    ],
    edges: [
      { id: "RIDGE", edge_type: "ridge", length_ft: 16, facet_id: "T1", facet_id_secondary: "T2", sort: 0 },
      { id: "HFL", edge_type: "hip", length_ft: 23, facet_id: "T1", facet_id_secondary: "P3", sort: 1 },
      { id: "HFR", edge_type: "hip", length_ft: 23, facet_id: "T1", facet_id_secondary: "P4", sort: 2 },
      { id: "HBL", edge_type: "hip", length_ft: 23, facet_id: "T2", facet_id_secondary: "P3", sort: 3 },
      { id: "HBR", edge_type: "hip", length_ft: 23, facet_id: "T2", facet_id_secondary: "P4", sort: 4 },
      { id: "E_T1", edge_type: "eave", length_ft: 48, facet_id: "T1", sort: 5 },
      { id: "E_T2", edge_type: "eave", length_ft: 48, facet_id: "T2", sort: 6 },
      { id: "E_P3", edge_type: "eave", length_ft: 32, facet_id: "P3", sort: 7 },
      { id: "E_P4", edge_type: "eave", length_ft: 32, facet_id: "P4", sort: 8 },
    ],
    penetrations: [],
  };
}

let r = generateSketchGeometry(basicHip());
assert.strictEqual(r.ok, true); ok("hip: ok");
assert.strictEqual(r.confidence, "high"); ok("hip: high confidence");
assert.strictEqual(r.document.vertices.length, 6); ok("hip: 6 vertices");
assert.strictEqual(r.document.edges.length, 9); ok("hip: 9 edges (4 eave + 4 hip + 1 ridge)");
assert.strictEqual(r.document.facets.length, 4); ok("hip: 4 facets");
assert.strictEqual(validateSketch(r.document).valid, true); ok("hip: passes canonical validator");
assert.strictEqual(r.document.scale.feetPerUnit, 1); ok("hip: real-world scale (feet)");
// adjacency graph reported, from Primary/Secondary only
assert.ok(r.graph && r.graph.node_count === 4 && r.graph.components === 1); ok("hip: adjacency graph connected (1 component)");
assert.strictEqual(r.graph.shared_edges.length, 5); ok("hip: 5 shared roof lines in graph (1 ridge + 4 hips)");

// DUPLICATE / SHARED EDGE PREVENTION: each shared roof line == ONE canonical sketch edge in BOTH planes.
const ids = r.document.edges.map((e) => e.id);
assert.strictEqual(new Set(ids).size, 9); ok("hip: no duplicate sketch edges");
function refCount(mid) { return r.document.facets.filter((f) => f.edgeIds.includes(`mse_${mid}`)).length; }
assert.strictEqual(refCount("RIDGE"), 2); ok("hip: ridge is ONE edge shared by exactly 2 planes");
["HFL", "HFR", "HBL", "HBR"].forEach((h) => assert.strictEqual(refCount(h), 2));
ok("hip: each hip is ONE edge shared by exactly its 2 planes");
["E_T1", "E_T2", "E_P3", "E_P4"].forEach((e) => assert.strictEqual(refCount(e), 1));
ok("hip: eaves remain exterior (one plane each)");
// relational mapping preserved; measured lengths kept as confirmed
assert.deepStrictEqual(r.mappings.facets.map((m) => m.measurement_facet_id).sort(), ["P3", "P4", "T1", "T2"]); ok("hip: facets mapped by relational id");
assert.strictEqual(r.mappings.edges.length, 9); ok("hip: all 9 roof lines mapped");
const ridgeEdge = r.document.edges.find((e) => e.measurement_edge_id === "RIDGE");
assert.strictEqual(ridgeEdge.confirmed_length_ft, 16); ok("hip: ridge confirmed length preserved");
assert.strictEqual(ridgeEdge.locked, true); ok("hip: measured ridge marked confirmed/locked");
// no measurement side effects + determinism
const before = JSON.stringify(basicHip());
const obj = basicHip(); generateSketchGeometry(obj);
assert.strictEqual(JSON.stringify(obj), before); ok("hip: no measurement mutation");
const s = basicHip(); s.facets.reverse(); s.edges.reverse();
assert.strictEqual(JSON.stringify(generateSketchGeometry(s).document.facets.map((f) => f.measurement_facet_id).sort()),
  JSON.stringify(r.document.facets.map((f) => f.measurement_facet_id).sort())); ok("hip: deterministic facet set (order-independent)");

// -------------------------------------------------------------------------------------------------
// Hip with a SHORT ridge: 34 x 32 -> ridge 2.
// -------------------------------------------------------------------------------------------------
function shortRidgeHip() {
  const h = basicHip();
  h.edges = h.edges.map((e) => e.id === "RIDGE" ? { ...e, length_ft: 2 } : e);
  h.edges = h.edges.map((e) => (e.id === "E_T1" || e.id === "E_T2") ? { ...e, length_ft: 34 } : e);
  return h;
}
r = generateSketchGeometry(shortRidgeHip());
assert.strictEqual(r.ok, true); ok("short-ridge hip: ok");
assert.strictEqual(validateSketch(r.document).valid, true); ok("short-ridge hip: valid geometry");
const rr = r.document.vertices.find((v) => v.id === "gv_r1"), rr2 = r.document.vertices.find((v) => v.id === "gv_r2");
assert.strictEqual(Math.round((rr2.x - rr.x) * 10) / 10, 2); ok("short-ridge hip: drawn ridge length = 2");

// -------------------------------------------------------------------------------------------------
// Valley-connected planes (2 planes sharing a Valley) -> unresolved (deferred), adjacency recognized.
// -------------------------------------------------------------------------------------------------
function valleyPair() {
  return {
    structure: { id: "V" },
    facets: [
      { id: "A", structure_id: "V", facet_label: "A", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, sort: 0 },
      { id: "B", structure_id: "V", facet_label: "B", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, sort: 1 },
    ],
    edges: [
      { id: "VALLEY", edge_type: "valley", length_ft: 28, facet_id: "A", facet_id_secondary: "B", sort: 0 },
      { id: "EA", edge_type: "eave", length_ft: 20, facet_id: "A", sort: 1 },
      { id: "EB", edge_type: "eave", length_ft: 20, facet_id: "B", sort: 2 },
    ],
    penetrations: [],
  };
}
r = generateSketchGeometry(valleyPair());
assert.strictEqual(r.status, "needs_review"); ok("valley: needs_review (deferred to next phase)");
assert.ok(r.diagnostics.some((d) => d.code === "unresolved_complex_topology")); ok("valley: unresolved_complex diagnostic");
assert.strictEqual(r.document.vertices.length, 0); ok("valley: NO fabricated geometry");
assert.ok(r.graph.shared_edges.some((e) => e.edge_type === "valley")); ok("valley: valley recognized as shared roof line in graph");

// -------------------------------------------------------------------------------------------------
// Dead Valley relationship -> unresolved (deferred), adjacency recognized.
// -------------------------------------------------------------------------------------------------
function deadValleyPair() {
  const v = valleyPair();
  v.edges = v.edges.map((e) => e.id === "VALLEY" ? { ...e, id: "DV", edge_type: "dead_valley" } : e);
  return v;
}
r = generateSketchGeometry(deadValleyPair());
assert.strictEqual(r.status, "needs_review"); ok("dead valley: needs_review");
assert.ok(r.graph.shared_edges.some((e) => e.edge_type === "dead_valley")); ok("dead valley: recognized as shared roof line");
assert.strictEqual(r.document.vertices.length, 0); ok("dead valley: NO fabricated geometry");

// -------------------------------------------------------------------------------------------------
// Disconnected planes (two separate gables, no linking shared line) -> needs_review, never forced.
// -------------------------------------------------------------------------------------------------
function disconnected() {
  return {
    structure: { id: "D" },
    facets: [
      { id: "A", structure_id: "D", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, sort: 0 },
      { id: "B", structure_id: "D", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, sort: 1 },
      { id: "C", structure_id: "D", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, sort: 2 },
      { id: "D2", structure_id: "D", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, sort: 3 },
    ],
    edges: [
      { id: "R1", edge_type: "ridge", length_ft: 20, facet_id: "A", facet_id_secondary: "B", sort: 0 },
      { id: "R2", edge_type: "ridge", length_ft: 20, facet_id: "C", facet_id_secondary: "D2", sort: 1 },
    ],
    penetrations: [],
  };
}
r = generateSketchGeometry(disconnected());
assert.strictEqual(r.status, "needs_review"); ok("disconnected: needs_review");
assert.ok(r.diagnostics.some((d) => d.code === "disconnected_planes")); ok("disconnected: disconnected_planes diagnostic");
assert.strictEqual(r.graph.components, 2); ok("disconnected: graph reports 2 components (not forced together)");
assert.strictEqual(r.document.vertices.length, 0); ok("disconnected: NO fabricated geometry");

// -------------------------------------------------------------------------------------------------
// Contradictory adjacency (a hip whose Primary == Secondary) -> needs_review, never guesses.
// -------------------------------------------------------------------------------------------------
function contradictoryAdj() {
  const h = basicHip();
  h.edges = h.edges.map((e) => e.id === "HFL" ? { ...e, facet_id_secondary: "T1" } : e); // T1<->T1
  return h;
}
r = generateSketchGeometry(contradictoryAdj());
assert.strictEqual(r.status, "needs_review"); ok("contradictory adjacency: needs_review");
assert.ok(r.diagnostics.some((d) => d.code === "contradictory_adjacency")); ok("contradictory adjacency: diagnosed");
assert.strictEqual(r.document.vertices.length, 0); ok("contradictory adjacency: NO fabricated geometry");

// contradictory DIMENSIONS on an otherwise-valid hip (ridge != longEave - shortEave) -> needs_review
function contradictoryHipDims() {
  const h = basicHip();
  h.edges = h.edges.map((e) => e.id === "RIDGE" ? { ...e, length_ft: 40 } : e); // should be 16
  return h;
}
r = generateSketchGeometry(contradictoryHipDims());
assert.strictEqual(r.status, "needs_review"); ok("hip contradictory dims: needs_review");
assert.ok(r.diagnostics.some((d) => d.code === "contradictory_dimensions")); ok("hip contradictory dims: diagnosed");

// asymmetric hip (unequal end pitch) -> now SOLVED by the ridge-based framing solver (Uneven Pitches).
function asymmetricHip() {
  const h = basicHip();
  h.facets = h.facets.map((f) => f.id === "P3" ? { ...f, pitch_rise: 9 } : f);
  return h;
}
r = generateSketchGeometry(asymmetricHip());
assert.strictEqual(r.ok, true); ok("asymmetric hip: now generated by the framing solver");
assert.strictEqual(r.document.facets.length, 4); ok("asymmetric hip: 4 planes drawn");
assert.strictEqual(validateSketch(r.document).valid, true); ok("asymmetric hip: passes canonical validator");

// gable + single-plane still work through the same entry (regression)
r = generateSketchGeometry({ structure: { id: "S" }, facets: [{ id: "F1", structure_id: "S", pitch_rise: 4, area_sqft: 200, width_ft: 10, length_ft: 20, facet_label: "F1", sort: 0 }], edges: [], penetrations: [] });
assert.strictEqual(r.ok, true); ok("regression: single plane still generates");

console.log("\nGENERATE SKETCH CONNECTED (hip + multi-plane adjacency): all " + n + " assertions passed");
