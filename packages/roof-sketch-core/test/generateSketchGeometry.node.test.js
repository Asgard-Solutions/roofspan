"use strict";
const assert = require("assert");
const { generateSketchGeometry, validateSketch, polygonArea } = require("..");

let n = 0;
function ok(name) { n++; console.log("  \u2713 " + name); }

const vmap = (doc) => { const m = {}; doc.vertices.forEach((v) => { m[v.id] = v; }); return m; };
// Ordered points for a facet's edgeIds loop (connected_graph) — used to check drawn shape/area.
function facetPoints(doc, f) {
  const em = {}; doc.edges.forEach((e) => { em[e.id] = e; });
  const vm = vmap(doc);
  const edges = f.edgeIds.map((id) => em[id]);
  // thread the loop
  const pts = [];
  let cur = edges[0].v1; let start = cur;
  const nextV = (e, from) => (e.v1 === from ? e.v2 : e.v1);
  // orient first edge so it starts at a shared vertex with the last edge
  const last = edges[edges.length - 1];
  if (last.v1 !== edges[0].v1 && last.v2 !== edges[0].v1) { cur = edges[0].v2; start = cur; }
  for (const e of edges) { pts.push(vm[cur]); cur = nextV(e, cur); }
  return pts.map((v) => [v.x, v.y]);
}

// -------------------------------------------------------------------------------------------------
// FIXTURE 1 — rectangular single-plane roof (shed). 40 x 24 = 960 sf, pitch 4.
// -------------------------------------------------------------------------------------------------
function singlePlane() {
  return {
    structure: { id: "S1" },
    facets: [{ id: "F1", structure_id: "S1", facet_label: "Shed", pitch_rise: 4, area_sqft: 960, width_ft: 24, length_ft: 40, sort: 0 }],
    edges: [
      { id: "E_EAVE", edge_type: "eave", length_ft: 40, facet_id: "F1", sort: 0 },
      { id: "E_RIDGE", edge_type: "ridge", length_ft: 40, facet_id: "F1", sort: 1 },
      { id: "E_RAKE_L", edge_type: "rake", length_ft: 24, facet_id: "F1", sort: 2 },
      { id: "E_RAKE_R", edge_type: "rake", length_ft: 24, facet_id: "F1", sort: 3 },
    ],
    penetrations: [{ id: "P1", pen_type: "pipe_boot", quantity: 1, facet_id: "F1", sort: 0 }],
  };
}

let r = generateSketchGeometry(singlePlane());
assert.strictEqual(r.ok, true); ok("single: ok");
assert.strictEqual(r.status, "generated"); ok("single: generated");
assert.strictEqual(r.confidence, "high"); ok("single: high confidence");
assert.strictEqual(r.geometry_status, "generated"); ok("single: geometry_status generated");
assert.strictEqual(r.document.vertices.length, 4); ok("single: 4 vertices");
assert.strictEqual(r.document.edges.length, 4); ok("single: 4 edges");
assert.strictEqual(r.document.facets.length, 1); ok("single: 1 facet");
assert.strictEqual(r.document.scale.resolved, true); ok("single: real-world scale resolved");
assert.strictEqual(r.document.scale.feetPerUnit, 1); ok("single: feetPerUnit = 1 (feet)");
// canonical validator must accept the generated topology
assert.strictEqual(validateSketch(r.document).valid, true); ok("single: passes canonical validator");
// drawn plan area == width * length
assert.strictEqual(Math.round(polygonArea(facetPoints(r.document, r.document.facets[0]))), 960); ok("single: drawn area = 960 (W*L)");
// facet -> measurement plane mapping (relational)
assert.strictEqual(r.document.facets[0].measurement_facet_id, "F1"); ok("single: facet mapped to F1");
assert.strictEqual(r.document.facets[0].pitch_rise, 4); ok("single: pitch carried");
assert.strictEqual(r.document.facets[0].confirmed_area_sqft, 960); ok("single: confirmed area carried");
// every measurement roof line maps to a generated edge (by relational id)
const mappedMids = r.mappings.edges.map((m) => m.measurement_edge_id).sort();
assert.deepStrictEqual(mappedMids, ["E_EAVE", "E_RAKE_L", "E_RAKE_R", "E_RIDGE"]); ok("single: all 4 roof lines mapped to edges");
const eave = r.document.edges.find((e) => e.measurement_edge_id === "E_EAVE");
assert.strictEqual(eave.confirmed_length_ft, 40); ok("single: eave confirmed length preserved (40)");
assert.strictEqual(eave.locked, true); ok("single: measured eave marked confirmed/locked");
// penetration position NOT fabricated
assert.strictEqual(r.document.penetrations[0].x, null); ok("single: penetration XY not fabricated");
assert.strictEqual(r.document.penetrations[0].position_known, false); ok("single: penetration position_known false");

// NO measurement side effects: input must be byte-identical after generation
const inBefore = JSON.stringify(singlePlane());
const inObj = singlePlane(); generateSketchGeometry(inObj);
assert.strictEqual(JSON.stringify(inObj), inBefore); ok("single: no measurement mutation side effects");
// determinism (order-independent)
const a1 = generateSketchGeometry(singlePlane());
const shuf = singlePlane(); shuf.edges.reverse();
const a2 = generateSketchGeometry(shuf);
assert.strictEqual(JSON.stringify(a2.document), JSON.stringify(a1.document)); ok("single: deterministic regardless of input order");

// -------------------------------------------------------------------------------------------------
// FIXTURE 2 — symmetric simple gable. Ridge 40; each plane 40 x 18 (=720), pitch 6.
// -------------------------------------------------------------------------------------------------
function symGable() {
  return {
    structure: { id: "S1" },
    facets: [
      { id: "FA", structure_id: "S1", facet_label: "Front", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40, sort: 0 },
      { id: "FB", structure_id: "S1", facet_label: "Back", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40, sort: 1 },
    ],
    edges: [
      { id: "RIDGE", edge_type: "ridge", length_ft: 40, facet_id: "FA", facet_id_secondary: "FB", sort: 0 },
      { id: "EAVE_A", edge_type: "eave", length_ft: 40, facet_id: "FA", sort: 1 },
      { id: "EAVE_B", edge_type: "eave", length_ft: 40, facet_id: "FB", sort: 2 },
      { id: "RAKE_A1", edge_type: "rake", length_ft: 18, facet_id: "FA", sort: 3 },
      { id: "RAKE_A2", edge_type: "rake", length_ft: 18, facet_id: "FA", sort: 4 },
      { id: "RAKE_B1", edge_type: "rake", length_ft: 18, facet_id: "FB", sort: 5 },
      { id: "RAKE_B2", edge_type: "rake", length_ft: 18, facet_id: "FB", sort: 6 },
    ],
    penetrations: [],
  };
}

r = generateSketchGeometry(symGable());
assert.strictEqual(r.ok, true); ok("gable: ok");
assert.strictEqual(r.confidence, "high"); ok("gable: high confidence");
assert.strictEqual(r.document.vertices.length, 6); ok("gable: 6 vertices");
assert.strictEqual(r.document.edges.length, 7); ok("gable: 7 edges (shared ridge)");
assert.strictEqual(r.document.facets.length, 2); ok("gable: 2 facets");
assert.strictEqual(validateSketch(r.document).valid, true); ok("gable: passes canonical validator");
// shared ridge edge referenced by BOTH facets, mapped to the RIDGE roof line
const ridge = r.document.edges.find((e) => e.measurement_edge_id === "RIDGE");
assert.ok(ridge && r.document.facets.every((f) => f.edgeIds.includes(ridge.id))); ok("gable: ridge shared by both facets");
assert.strictEqual(ridge.confirmed_length_ft, 40); ok("gable: ridge confirmed length preserved");
// each drawn plane area = 720 (40 x 18)
r.document.facets.forEach((f) => {
  assert.strictEqual(Math.round(polygonArea(facetPoints(r.document, f))), 720);
}); ok("gable: each plane drawn area = 720");
// facet mappings by relational id
assert.deepStrictEqual(r.mappings.facets.map((m) => m.measurement_facet_id).sort(), ["FA", "FB"]); ok("gable: facets mapped FA/FB");
// all 7 roof lines mapped
assert.strictEqual(r.mappings.edges.length, 7); ok("gable: all 7 roof lines mapped");
// no side effects
const gBefore = JSON.stringify(symGable());
const gObj = symGable(); generateSketchGeometry(gObj);
assert.strictEqual(JSON.stringify(gObj), gBefore); ok("gable: no measurement mutation");
// deterministic
const g1 = generateSketchGeometry(symGable());
const g2s = symGable(); g2s.facets.reverse(); g2s.edges.reverse();
const g2 = generateSketchGeometry(g2s);
assert.strictEqual(JSON.stringify(g2.document.facets.map((f) => f.measurement_facet_id).sort()),
  JSON.stringify(g1.document.facets.map((f) => f.measurement_facet_id).sort())); ok("gable: deterministic facet set");

// -------------------------------------------------------------------------------------------------
// FIXTURE 3 — asymmetric but sufficiently constrained gable (different depths/pitches, same ridge).
// -------------------------------------------------------------------------------------------------
function asymGable() {
  const g = symGable();
  g.facets[1] = { id: "FB", structure_id: "S1", facet_label: "Back", pitch_rise: 9, area_sqft: 1000, width_ft: 25, length_ft: 40, sort: 1 };
  g.edges = g.edges.map((e) => (e.id === "RAKE_B1" || e.id === "RAKE_B2") ? { ...e, length_ft: 25 } : e);
  return g;
}
r = generateSketchGeometry(asymGable());
assert.strictEqual(r.ok, true); ok("asym gable: ok (sufficiently constrained)");
assert.strictEqual(r.confidence, "high"); ok("asym gable: high confidence");
assert.strictEqual(validateSketch(r.document).valid, true); ok("asym gable: passes validator");
const fa = r.document.facets.find((f) => f.measurement_facet_id === "FA");
const fb = r.document.facets.find((f) => f.measurement_facet_id === "FB");
assert.strictEqual(Math.round(polygonArea(facetPoints(r.document, fa))), 720); ok("asym gable: front area 720");
assert.strictEqual(Math.round(polygonArea(facetPoints(r.document, fb))), 1000); ok("asym gable: back area 1000 (different depth)");

// -------------------------------------------------------------------------------------------------
// FIXTURE 4 — missing Ridge relationship (two planes, no shared ridge) -> Needs Review.
// -------------------------------------------------------------------------------------------------
function noRidge() {
  const g = symGable();
  g.edges[0] = { id: "RIDGE", edge_type: "ridge", length_ft: 40, facet_id: "FA", sort: 0 }; // secondary dropped
  return g;
}
r = generateSketchGeometry(noRidge());
assert.strictEqual(r.ok, false); ok("no-ridge: ok = false");
assert.strictEqual(r.status, "needs_review"); ok("no-ridge: needs_review");
assert.ok(r.diagnostics.some((d) => d.code === "missing_ridge_relationship" || d.code === "unsupported_roof_topology")); ok("no-ridge: diagnosed (no shared ridge)");
assert.strictEqual(r.document.vertices.length, 0); ok("no-ridge: NO fabricated geometry");

// -------------------------------------------------------------------------------------------------
// FIXTURE 5 — contradictory dimensions (area != width*length) -> Needs Review.
// -------------------------------------------------------------------------------------------------
function contradictory() {
  const s = singlePlane();
  s.facets[0].area_sqft = 1500; // 24 * 40 = 960, not 1500
  return s;
}
r = generateSketchGeometry(contradictory());
assert.strictEqual(r.ok, false); ok("contradictory: ok = false");
assert.strictEqual(r.status, "needs_review"); ok("contradictory: needs_review");
assert.ok(r.diagnostics.some((d) => d.code === "contradictory_dimensions")); ok("contradictory: diagnosed");
assert.strictEqual(r.document.vertices.length, 0); ok("contradictory: NO geometry emitted");

// contradiction via edge length (rake != width) also blocks
function contradictoryEdge() {
  const s = singlePlane();
  s.edges = s.edges.map((e) => (e.id === "E_RAKE_L") ? { ...e, length_ft: 99 } : e); // width is 24
  return s;
}
r = generateSketchGeometry(contradictoryEdge());
assert.strictEqual(r.status, "needs_review"); ok("contradictory edge: needs_review");
assert.ok(r.diagnostics.some((d) => d.code === "contradictory_dimensions")); ok("contradictory edge: diagnosed");

// -------------------------------------------------------------------------------------------------
// FIXTURE 6 — insufficient measurements (no dimensions) -> Needs Review, no guessing.
// -------------------------------------------------------------------------------------------------
function insufficient() {
  return {
    structure: { id: "S1" },
    facets: [{ id: "F1", structure_id: "S1", facet_label: "F1", pitch_rise: 6, area_sqft: 500, sort: 0 }], // no width/length
    edges: [{ id: "E1", edge_type: "eave", length_ft: 20, facet_id: "F1", sort: 0 }],
    penetrations: [],
  };
}
r = generateSketchGeometry(insufficient());
assert.strictEqual(r.ok, false); ok("insufficient: ok = false");
assert.strictEqual(r.status, "needs_review"); ok("insufficient: needs_review");
assert.ok(r.diagnostics.some((d) => d.code === "insufficient_dimensions")); ok("insufficient: diagnosed (no width/length)");
assert.strictEqual(r.document.vertices.length, 0); ok("insufficient: NO fabricated geometry");

// unsupported: 3 planes -> not attempted at high confidence this phase (no hip roofs)
function threePlanes() {
  const g = symGable();
  g.facets.push({ id: "FC", structure_id: "S1", facet_label: "C", pitch_rise: 6, area_sqft: 200, width_ft: 10, length_ft: 20, sort: 2 });
  g.edges.push({ id: "HIP", edge_type: "hip", length_ft: 20, facet_id: "FA", facet_id_secondary: "FC", sort: 7 });
  return g;
}
r = generateSketchGeometry(threePlanes());
assert.strictEqual(r.status, "needs_review"); ok("three planes: needs_review (unsupported this phase)");
assert.strictEqual(r.document.vertices.length, 0); ok("three planes: no geometry emitted");

// foundation needs_review (no planes) -> geometry not attempted, still no throw
r = generateSketchGeometry({ structure: { id: "S1" }, facets: [], edges: [], penetrations: [] });
assert.strictEqual(r.status, "needs_review"); ok("no planes: needs_review");
assert.strictEqual(r.geometry_status, "not_attempted"); ok("no planes: geometry not_attempted");

console.log("\nGENERATE SKETCH GEOMETRY (single plane + simple gable): all " + n + " assertions passed");
