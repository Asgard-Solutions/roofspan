"use strict";
// Structure-safe scoping + explicit one-to-one facet/edge mapping contracts (Node, no React).
const assert = require("assert");
const path = require("path");
const Module = require("module");
const babel = require("@babel/core");

function load(rel) {
  const file = path.resolve(__dirname, rel);
  const { code } = babel.transformFileSync(file, { plugins: ["@babel/plugin-transform-modules-commonjs"] });
  const m = new Module(file, module);
  m.filename = file; m.paths = Module._nodeModulePaths(path.dirname(file));
  m._compile(code, file);
  return m.exports;
}

const C = load("../commands.js");
const S = load("../scopeMeasurements.js");
const H = load("../historyCore.js");
const core = require("@roofspan/roof-sketch-core");

let n = 0;
const ok = (name) => { n++; console.log("  \u2713 " + name); };

// relational fixtures across TWO structures
const facets = [
  { id: "MF1", structure_id: "S1", facet_label: "F1", area_sqft: 412 },
  { id: "MF2", structure_id: "S1", facet_label: "F2", area_sqft: 298 },
  { id: "MF3", structure_id: "S2", facet_label: "F3", area_sqft: 150 }, // other structure
];
const edges = [
  { id: "ME1", facet_id: "MF1", edge_type: "eave", length_ft: 24.5 },
  { id: "ME2", facet_id: "MF2", facet_id_secondary: "MF1", edge_type: "valley", length_ft: 12.2 }, // shared, in-structure
  { id: "ME3", facet_id: "MF3", edge_type: "ridge", length_ft: 18 }, // other structure
];
const pens = [
  { id: "MP1", facet_id: "MF1", pen_type: "pipe_boot" },
  { id: "MP3", facet_id: "MF3", pen_type: "vent" }, // other structure
];

// ---- scoping ----
{
  const scoped = S.scopeForStructure({ structure: { id: "S1" }, facets, edges, penetrations: pens });
  assert.deepStrictEqual(scoped.facets.map((f) => f.id), ["MF1", "MF2"]); ok("facets scoped to current structure only");
  assert.deepStrictEqual(scoped.edges.map((e) => e.id).sort(), ["ME1", "ME2"]); ok("edges scoped by facet ownership incl. shared secondary facet");
  assert.ok(!scoped.edges.some((e) => e.id === "ME3")); ok("cross-structure edge excluded");
  assert.deepStrictEqual(scoped.penetrations.map((p) => p.id), ["MP1"]); ok("penetrations scoped to current structure only");
}

// ---- fresh facet starts Unmapped, explicit map, undo/redo ----
{
  let d = core.createSketchDocument({ structureId: "S1" });
  const a = C.createFacet(C.addVertex(d, 0, 0).doc, []); // just need a facet row
  d = a.doc; const fid = a.facetId;
  assert.ok(!C.fById(d, fid).measurement_facet_id); ok("fresh sketch facet starts Unmapped");
  let h = H.makeHistory(d);
  const mapped = C.setFacetMeasurementLink(d, fid, "MF1");
  h = H.push(h, mapped);
  assert.strictEqual(C.fById(h.present, fid).measurement_facet_id, "MF1"); ok("facet maps explicitly to current-structure MF1");
  h = H.undo(h);
  assert.ok(!C.fById(h.present, fid).measurement_facet_id); ok("undo returns facet to Unmapped");
  h = H.redo(h);
  assert.strictEqual(C.fById(h.present, fid).measurement_facet_id, "MF1"); ok("redo re-applies facet mapping");
}

// ---- duplicate facet mapping is refused (no silent steal) ----
{
  let d = core.createSketchDocument({ structureId: "S1" });
  const a = C.createFacet(d, []); d = a.doc; const A = a.facetId;
  const b = C.createFacet(d, []); d = b.doc; const B = b.facetId;
  d = C.setFacetMeasurementLink(d, A, "MF1");
  assert.strictEqual(C.isMeasurementFacetTaken(d, "MF1", B), true); ok("MF1 reported as taken for a different facet");
  const attempt = C.setFacetMeasurementLink(d, B, "MF1");
  assert.ok(!C.fById(attempt, B).measurement_facet_id); ok("facet B refused MF1 (still Unmapped)");
  assert.strictEqual(C.fById(attempt, A).measurement_facet_id, "MF1"); ok("facet A mapping is NOT stolen");
  // unmap A then B can take MF1
  const freed = C.setFacetMeasurementLink(d, A, null);
  const now = C.setFacetMeasurementLink(freed, B, "MF1");
  assert.strictEqual(C.fById(now, B).measurement_facet_id, "MF1"); ok("after A unmapped, B may map to MF1");
}

// ---- cross-structure facet is never a candidate ----
{
  const scoped = S.scopeForStructure({ structure: { id: "S1" }, facets, edges, penetrations: pens });
  assert.ok(!scoped.facets.some((f) => f.id === "MF3")); ok("MF3 (other structure) not offered to S1 editor");
}

// ---- edge mapping: explicit, aliases coherent, one-to-one, undo/redo ----
{
  let d = core.createSketchDocument({ structureId: "S1" });
  let a = C.addVertex(d, 0, 0); let b = C.addVertex(a.doc, 10, 0);
  const e = C.addEdge(b.doc, a.vertexId, b.vertexId); d = e.doc; const gEdge = e.edgeId;
  assert.ok(!C.eById(d, gEdge).measurement_edge_id); ok("fresh sketch edge starts Unmapped");
  let h = H.makeHistory(d);
  const mapped = C.setEdgeMeasurementLink(d, gEdge, "ME1"); h = H.push(h, mapped);
  const me = C.eById(h.present, gEdge);
  assert.ok(me.measurement_edge_id === "ME1" && me.relational_edge_id === "ME1"); ok("edge maps explicitly; both canonical aliases coherent");
  h = H.undo(h); assert.ok(!C.eById(h.present, gEdge).measurement_edge_id); ok("undo returns edge to Unmapped");
  h = H.redo(h); assert.strictEqual(C.eById(h.present, gEdge).measurement_edge_id, "ME1"); ok("redo re-applies edge mapping");
  // duplicate refused
  const g2 = C.addEdge(h.present, a.vertexId, b.vertexId); // duplicate coords rejected -> add distinct
  let d2 = C.addVertex(h.present, 0, 5); const v3 = d2.vertexId;
  const e2 = C.addEdge(d2.doc, a.vertexId, v3); d2 = e2.doc;
  const attempt = C.setEdgeMeasurementLink(d2, e2.edgeId, "ME1");
  assert.ok(!C.eById(attempt, e2.edgeId).measurement_edge_id); ok("duplicate edge mapping to ME1 refused");
}

// ---- summarizeScoped: read-only Roof Sketch measurements reference ----
{
  const sum = S.summarizeScoped(S.scopeForStructure({ structure: { id: "S1" }, facets, edges, penetrations: pens }));
  assert.deepStrictEqual(sum.planes.map((p) => p.id), ["MF1", "MF2"]); ok("summary planes scoped to structure");
  assert.strictEqual(sum.lines.find((l) => l.type === "valley").lf, 12.2); ok("summary groups roof lines by type with LF");
  assert.ok(!sum.lines.some((l) => l.type === "ridge")); ok("summary excludes other-structure roof lines");
  assert.strictEqual(sum.pens.find((p) => p.type === "pipe_boot").qty, 1); ok("summary groups penetrations by type × qty");
  assert.strictEqual(sum.totals.area, 710); ok("summary structure total area = 412 + 298");
  assert.strictEqual(sum.totals.planeCount, 2); ok("summary structure plane count");
}

console.log("\nROOF SKETCH MAPPING: all " + n + " assertions passed");
