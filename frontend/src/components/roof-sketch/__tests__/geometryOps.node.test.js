"use strict";
// Phase 3 geometry closure contracts: projection, split (+protection/shared-facet), merge, join, snap,
// dimensions. Node, no React. Topology is re-validated with the shared-core validateSketch.
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
const SNAP = load("../snapping.js");
const DIM = load("../edgeDimensions.js");
const core = require("@roofspan/roof-sketch-core");

let n = 0; const ok = (name) => { n++; console.log("  \u2713 " + name); };

// ---- project-to-segment matrix ----
{
  const A = [0, 0], B = [10, 0];
  assert.strictEqual(core.projectPointToSegment([5, 3], A, B).t, 0.5); ok("horizontal projection midpoint t=0.5");
  assert.deepStrictEqual(core.projectPointToSegment([5, 3], A, B).point, [5, 0]); ok("projected point lies on the segment");
  assert.strictEqual(core.projectPointToSegment([-4, 2], A, B).t, 0); ok("point before A clamps t=0");
  assert.strictEqual(core.projectPointToSegment([99, 2], A, B).t, 1); ok("point after B clamps t=1");
  assert.strictEqual(core.projectPointToSegment([3, 0], [0, 0], [0, 10]).point[0], 0); ok("vertical projection stays on line");
  const zero = core.projectPointToSegment([2, 2], [1, 1], [1, 1]); assert.ok(zero.t === 0 && isFinite(zero.distance)); ok("zero-length segment handled safely");
}

// ---- shared scaled length == proposal source ----
{
  let d = core.createSketchDocument({ structureId: "S" });
  let a = C.addVertex(d, 0, 0); let b = C.addVertex(a.doc, 10, 0);
  const e = C.addEdge(b.doc, a.vertexId, b.vertexId, "eave"); d = e.doc;
  assert.strictEqual(core.edgeGeometryLengthFeet(d, C.eById(d, e.edgeId)), null); ok("unresolved scale -> length null");
  d = C.setScale(d, { edgeId: e.edgeId, realFeet: 20 });
  assert.strictEqual(core.edgeGeometryLengthFeet(d, C.eById(d, e.edgeId)), 20); ok("resolved scale -> 20 LF (10 units * 2 ft/unit)");
}

// build a rectangle with 4 graph edges + a facet
function rect() {
  let d = core.createSketchDocument({ structureId: "S" });
  const v = [];
  for (const [x, y] of [[0, 0], [10, 0], [10, 8], [0, 8]]) { const r = C.addVertex(d, x, y); d = r.doc; v.push(r.vertexId); }
  const eids = [];
  for (const [i, j, t] of [[0, 1, "eave"], [1, 2, "rake"], [2, 3, "ridge"], [3, 0, "rake"]]) { const r = C.addEdge(d, v[i], v[j], t); d = r.doc; eids.push(r.edgeId); }
  const f = C.createFacet(d, eids, { pitch_rise: 6 }); d = f.doc;
  return { d, v, eids, facetId: f.facetId };
}

// ---- basic + projected split; validation ----
{
  const { d, eids } = rect();
  const r = C.splitEdgeSafe(d, eids[0], 5.2, 0.9); // off-edge pointer
  assert.ok(r.ok); ok("basic edge split succeeds");
  assert.strictEqual(C.vById(r.doc, r.vertexId).y, 0); ok("split vertex uses PROJECTED point (y=0), not raw pointer (0.9)");
  assert.strictEqual(C.vById(r.doc, r.vertexId).x, 5.2); ok("split vertex x = projected x");
  assert.strictEqual((r.doc.edges || []).length, 5); ok("one edge replaced by two");
  const facet = r.doc.facets[0];
  assert.ok(facet.edgeIds.includes(r.edgeIds[0]) && facet.edgeIds.includes(r.edgeIds[1])); ok("facet loop references both child edges");
  assert.strictEqual(core.validateSketch(r.doc).errors.length, 0); ok("split result validates (closed loop)");
}

// ---- endpoint reuse (no split) ----
{
  const { d, eids } = rect();
  const r = C.splitEdgeSafe(d, eids[0], 0.0000001, 0, { endpointTol: 0.01 });
  assert.ok(!r.ok && r.reason === "endpoint_reuse"); ok("near-endpoint split is refused (endpoint reused, no zero-length child)");
}

// ---- protected split blocked (each of the 4 semantics) ----
for (const patch of [{ measurement_edge_id: "ME1" }, { relational_edge_id: "RE1" }, { confirmed_length_ft: 24.5 }, { locked: true }]) {
  const { d, eids } = rect();
  const d2 = { ...d, edges: d.edges.map((e) => (e.id === eids[0] ? { ...e, ...patch } : e)) };
  const r = C.splitEdgeSafe(d2, eids[0], 5, 0);
  assert.ok(!r.ok && r.reason === "edge_protected"); assert.strictEqual(r.doc, d2);
  ok(`protected split blocked (${Object.keys(patch)[0]}) and document unchanged`);
}

// ---- shared-facet split updates BOTH facets ----
{
  // two facets sharing edge eids[0]; build a second facet reusing that edge
  const { d, v, eids, facetId } = rect();
  let d2 = d;
  const r5 = C.addVertex(d2, 5, -6); d2 = r5.doc;               // apex below the shared eave
  const e5 = C.addEdge(d2, v[0], r5.vertexId, "rake"); d2 = e5.doc;
  const e6 = C.addEdge(d2, r5.vertexId, v[1], "rake"); d2 = e6.doc;
  const f2 = C.createFacet(d2, [eids[0], e6.edgeId, e5.edgeId], { pitch_rise: 6 }); d2 = f2.doc;
  const r = C.splitEdgeSafe(d2, eids[0], 5, 0);
  assert.ok(r.ok);
  const fa = r.doc.facets.find((f) => f.id === facetId);
  const fb = r.doc.facets.find((f) => f.id === f2.facetId);
  assert.ok(fa.edgeIds.includes(r.edgeIds[0]) && fa.edgeIds.includes(r.edgeIds[1])); ok("shared split: facet A references both children");
  assert.ok(fb.edgeIds.includes(r.edgeIds[0]) && fb.edgeIds.includes(r.edgeIds[1])); ok("shared split: facet B references both children (shared topology preserved)");
}

// ---- merge vertices ----
{
  let d = core.createSketchDocument({ structureId: "S" });
  const a = C.addVertex(d, 0, 0); d = a.doc; const b = C.addVertex(d, 10, 0); d = b.doc;
  const c = C.addVertex(d, 10, 0.05); d = c.doc; const dd = C.addVertex(d, 5, 5); d = dd.doc;
  const e1 = C.addEdge(d, a.vertexId, b.vertexId, "eave"); d = e1.doc;
  const e2 = C.addEdge(d, c.vertexId, dd.vertexId, "rake"); d = e2.doc;
  const r = C.mergeVertices(d, c.vertexId, b.vertexId);
  assert.ok(r.ok && !C.vById(r.doc, c.vertexId)); ok("merge removes the moving vertex and rewires its edges");
  assert.ok(C.eById(r.doc, e2.edgeId).v1 === b.vertexId); ok("merge rewires the incident edge to the target vertex");
}
{
  // incompatible protected duplicate collapse -> rejected
  let d = core.createSketchDocument({ structureId: "S" });
  const a = C.addVertex(d, 0, 0); d = a.doc; const b = C.addVertex(d, 10, 0); d = b.doc; const c = C.addVertex(d, 5, 5); d = c.doc;
  let e1 = C.addEdge(d, a.vertexId, b.vertexId, "eave"); d = e1.doc;
  let e2 = C.addEdge(d, a.vertexId, c.vertexId, "ridge"); d = e2.doc;
  d = { ...d, edges: d.edges.map((e) => (e.id === e2.edgeId ? { ...e, measurement_edge_id: "MEx" } : (e.id === e1.edgeId ? { ...e, measurement_edge_id: "MEy" } : e))) };
  const r = C.mergeVertices(d, c.vertexId, b.vertexId); // would make a-b duplicate with conflicting mapping
  assert.ok(!r.ok && r.reason === "incompatible_duplicate_edges"); assert.strictEqual(r.doc, d); ok("merge with incompatible protected duplicates rejected, doc unchanged");
}

// ---- join edges ----
function chainABC(typeA, typeB) {
  let d = core.createSketchDocument({ structureId: "S" });
  const A = C.addVertex(d, 0, 0); d = A.doc; const B = C.addVertex(d, 5, 0); d = B.doc; const Cc = C.addVertex(d, 10, 0); d = Cc.doc;
  const e1 = C.addEdge(d, A.vertexId, B.vertexId, typeA); d = e1.doc;
  const e2 = C.addEdge(d, B.vertexId, Cc.vertexId, typeB); d = e2.doc;
  return { d, A: A.vertexId, B: B.vertexId, Ccc: Cc.vertexId, e1: e1.edgeId, e2: e2.edgeId };
}
{
  const { d, B, e1, e2 } = chainABC("eave", "eave");
  const r = C.joinEdges(d, e1, e2);
  assert.ok(r.ok && !C.vById(r.doc, B) && r.doc.edges.length === 1); ok("simple join removes middle vertex -> single edge");
  assert.strictEqual(C.eById(r.doc, r.edgeId).type, "eave"); ok("same-type join inherits the type");
}
{
  const { d, e1, e2 } = chainABC("unclassified", "ridge");
  assert.strictEqual(C.joinEdges(d, e1, e2).doc.edges.length >= 0, true);
  assert.strictEqual(C.eById(C.joinEdges(d, e1, e2).doc, C.joinEdges(d, e1, e2).edgeId).type, "ridge"); ok("unclassified + ridge -> ridge");
}
{
  const { d, e1, e2 } = chainABC("ridge", "hip");
  assert.strictEqual(C.joinEdges(d, e1, e2).reason, "type_conflict"); ok("conflicting types require explicit resolution");
  assert.ok(C.joinEdges(d, e1, e2, { resultType: "ridge" }).ok); ok("explicit resultType resolves the conflict");
}
{
  // branch rejection: middle vertex has a 3rd incident edge
  const { d, B, e1, e2 } = chainABC("eave", "eave");
  const D = C.addVertex(d, 5, 5); const d2 = D.doc; const e3 = C.addEdge(d2, B, D.vertexId, "rake"); 
  const r = C.joinEdges(e3.doc, e1, e2);
  assert.ok(!r.ok && r.reason === "middle_vertex_has_additional_connections"); ok("branch join rejected (middle vertex has extra connection)");
}
{
  // protected join blocked
  const { d, e1, e2 } = chainABC("eave", "eave");
  const d2 = { ...d, edges: d.edges.map((e) => (e.id === e1 ? { ...e, measurement_edge_id: "ME1" } : e)) };
  const r = C.joinEdges(d2, e1, e2);
  assert.ok(!r.ok && r.reason === "edge_protected"); assert.strictEqual(r.doc, d2); ok("protected/mapped join blocked, doc unchanged");
}

// ---- snap priority / nearest / screen tolerance ----
{
  const { d } = chainABC("eave", "eave"); // vertices at (0,0)(5,0)(10,0), edges along x
  const tol = SNAP.modelTolerance(12, 2); // 6 model units at 2x
  const near = SNAP.snapTarget(d, [5.2, 0.1], tol);
  assert.strictEqual(near.type, "vertex"); ok("snap priority: endpoint wins over edge interior when both in range");
  const interior = SNAP.snapTarget(d, [2.5, 0.2], SNAP.modelTolerance(12, 10)); // 1.2 units; not near a vertex
  assert.strictEqual(interior.type, "edge"); assert.ok(Math.abs(interior.point[1]) < 1e-9); ok("edge-interior projection snaps onto the segment");
  const free = SNAP.snapTarget(d, [2.5, 50], tol);
  assert.strictEqual(free.type, "free"); ok("out-of-range pointer returns a free point (no infinite-line snap)");
}

// ---- dimensions ----
{
  let d = core.createSketchDocument({ structureId: "S" });
  const a = C.addVertex(d, 0, 0); d = a.doc; const b = C.addVertex(d, 10, 0); d = b.doc;
  const e = C.addEdge(d, a.vertexId, b.vertexId, "eave"); d = e.doc;
  assert.strictEqual(DIM.edgeDimension(d, C.eById(d, e.edgeId)).source, "unavailable"); ok("uncalibrated edge -> no numeric LF (unavailable)");
  d = C.setScale(d, { edgeId: e.edgeId, realFeet: 20 });
  assert.strictEqual(DIM.edgeDimension(d, C.eById(d, e.edgeId)).valueFeet, 20); ok("calibrated edge -> 20 LF");
  const locked = { ...C.eById(d, e.edgeId), confirmed_length_ft: 18, locked: true };
  const dim = DIM.edgeDimension(d, locked);
  assert.strictEqual(dim.valueFeet, 18); ok("locked confirmed value wins over geometry (18 not 20)");
  assert.ok(dim.discrepancy === -2 && dim.geometryFeet === 20 && dim.locked === true); ok("locked dimension exposes geometry + discrepancy metadata");
}

console.log("\nROOF SKETCH GEOMETRY OPS (Phase 3): all " + n + " assertions passed");
