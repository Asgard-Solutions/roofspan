"use strict";
// Phase 3 FINAL topology-integrity contracts (Node, no React). Covers: merge self-loop facet safety,
// protected self-loop rejection, degenerate-facet rejection, insert duplicate-edge rejection, shared-facet
// insert, graph-decision invalidation (removed/rewired/incident/free-move; relational UUIDs preserved),
// join (normal/cyclic/shared-facet/protected/decisions), merge type + protected-duplicate matrices, and the
// shared-core duplicate_edge validator.
const assert = require("assert");
const path = require("path");
const babel = require("@babel/core");

const origJs = require.extensions[".js"];
require.extensions[".js"] = function (mod, filename) {
  if (filename.includes(`${path.sep}roof-sketch${path.sep}`) && !filename.includes("node_modules")) {
    const { code } = babel.transformFileSync(filename, { plugins: ["@babel/plugin-transform-modules-commonjs"] });
    return mod._compile(code, filename);
  }
  return origJs(mod, filename);
};

const C = require("../commands.js");
const G = require("../gestures.js");
const core = require("@roofspan/roof-sketch-core");

let n = 0; const ok = (name) => { n++; console.log("  \u2713 " + name); };
const abUuid = "ME-11111111-2222-3333-4444-555555555555";

// A closed connected rectangle facet A-B-C-D. Returns ids for each corner/edge.
function rect() {
  let d = core.createSketchDocument({ structureId: "S" });
  const v = {};
  for (const [name, x, y] of [["A", 0, 0], ["B", 10, 0], ["C", 10, 8], ["D", 0, 8]]) { const r = C.addVertex(d, x, y); d = r.doc; v[name] = r.vertexId; }
  const e = {};
  for (const [name, a, b, t] of [["AB", "A", "B", "eave"], ["BC", "B", "C", "rake"], ["CD", "C", "D", "ridge"], ["DA", "D", "A", "rake"]]) { const r = C.addEdge(d, v[a], v[b], t); d = r.doc; e[name] = r.edgeId; }
  const f = C.createFacet(d, [e.AB, e.BC, e.CD, e.DA], { pitch_rise: 6 }); d = f.doc;
  return { d, v, e, facetId: f.facetId };
}

function triangle() {
  let d = core.createSketchDocument({ structureId: "S" });
  const v = {};
  for (const [name, x, y] of [["A", 0, 0], ["B", 10, 0], ["C", 5, 8]]) { const r = C.addVertex(d, x, y); d = r.doc; v[name] = r.vertexId; }
  const e = {};
  for (const [name, a, b] of [["AB", "A", "B"], ["BC", "B", "C"], ["CA", "C", "A"]]) { const r = C.addEdge(d, v[a], v[b], "eave"); d = r.doc; e[name] = r.edgeId; }
  const f = C.createFacet(d, [e.AB, e.BC, e.CA], {}); d = f.doc;
  return { d, v, e, facetId: f.facetId };
}
const setDec = (d, id) => C.setProposalDecision(d, { targetType: "edge", targetId: id, metric: "length_ft", decision: "keep_current", value: 1 });
const hasDec = (d, id) => !!C.decisionFor(d, "edge", id, "length_ft");

// ===================== MERGE SELF-LOOP SAFETY =====================
{
  const { d, v, e } = rect();
  const r = C.mergeVertices(d, v.A, v.B);
  assert.ok(r.ok); ok("adjacent rectangle vertex merge valid (becomes a triangle)");
  const f = r.doc.facets[0];
  assert.ok(!f.edgeIds.includes(e.AB)); ok("removed self-loop edge absent from facet.edgeIds");
  assert.strictEqual(f.edgeIds.length, 3); ok("facet collapses to exactly three boundary edges");
  assert.ok(!C.eById(r.doc, e.AB)); ok("self-loop edge removed from edge list");
  const val = core.validateSketch(r.doc);
  assert.strictEqual(val.errors.length, 0); ok("merge result validates (no broken_edge_reference / hard errors)");
  assert.deepStrictEqual(f.vertexIds, []); ok("stale facet vertexIds cleared after merge");
}
// protected self-loop collapse rejected — 4 states
for (const [label, mut] of [
  ["mapping (measurement_edge_id)", (e2) => ({ ...e2, measurement_edge_id: abUuid })],
  ["relational mapping (relational_edge_id)", (e2) => ({ ...e2, relational_edge_id: abUuid })],
  ["confirmed (confirmed_length_ft)", (e2) => ({ ...e2, confirmed_length_ft: 10 })],
  ["locked (locked=true)", (e2) => ({ ...e2, locked: true })],
]) {
  const { d, v, e } = rect();
  const prot = { ...d, edges: d.edges.map((x) => (x.id === e.AB ? mut(x) : x)) };
  const r = C.mergeVertices(prot, v.A, v.B);
  assert.ok(!r.ok && r.reason === "protected_edge_collapse", `${label}: ${r.reason}`);
  assert.strictEqual(r.doc, prot); ok(`protected self-loop collapse blocked — ${label} (doc unchanged)`);
}
// degenerate triangle merge rejected + original restored
{
  const { d, v } = triangle();
  const r = C.mergeVertices(d, v.A, v.B);
  assert.ok(!r.ok); ok("triangle degenerate merge rejected");
  assert.strictEqual(r.reason, "facet_would_be_invalid"); ok("degenerate merge reason = facet_would_be_invalid");
  assert.strictEqual(r.doc, d); ok("degenerate merge leaves original document unchanged");
}

// ===================== INSERT SAFETY =====================
function insertSetup(connectVTo) {
  // free vertex V (far off) optionally pre-connected to A or B; target edge A-B belongs to a rect facet.
  const { d: base, v, e } = rect();
  let d = base; const vr = C.addVertex(d, 5, -6); d = vr.doc; const V = vr.vertexId;
  if (connectVTo) { const er = C.addEdge(d, V, v[connectVTo], "rake"); d = er.doc; }
  return { d, v, e, V };
}
{
  const { d, v, e, V } = insertSetup("A"); // V-A already exists -> child A-V duplicates it
  const r = C.insertExistingVertexIntoEdge(d, V, e.AB, 5, 0);
  assert.ok(!r.ok && r.reason === "duplicate_edge_creation"); ok("insert rejected when child A-V duplicates existing edge");
  assert.strictEqual(r.doc, d); ok("insert duplicate (A-side) leaves original document unchanged");
}
{
  const { d, v, e, V } = insertSetup("B"); // V-B already exists -> child V-B duplicates it
  const r = C.insertExistingVertexIntoEdge(d, V, e.AB, 5, 0);
  assert.ok(!r.ok && r.reason === "duplicate_edge_creation"); ok("insert rejected when child V-B duplicates existing edge");
  assert.strictEqual(r.doc, d); ok("insert duplicate (B-side) leaves original document unchanged");
}
{
  const { d, e, V } = insertSetup(null); // free V, no incident edges -> valid insert
  const r = C.insertExistingVertexIntoEdge(d, V, e.AB, 5, 0);
  assert.ok(r.ok); ok("free-vertex insert into an eligible edge succeeds");
  assert.strictEqual(C.vById(r.doc, V).y, 0); ok("same dragged vertex id reused, projected onto the segment");
  assert.strictEqual(core.validateSketch(r.doc).errors.length, 0); ok("insert result validates");
}
// shared-facet insert regression: two facets share edge A-B
function sharedFacet() {
  let d = core.createSketchDocument({ structureId: "S" });
  const v = {};
  for (const [name, x, y] of [["A", 0, 0], ["B", 10, 0], ["C", 10, 8], ["D", 0, 8], ["E", 10, -8], ["F", 0, -8]]) { const r = C.addVertex(d, x, y); d = r.doc; v[name] = r.vertexId; }
  const e = {};
  for (const [name, a, b, t] of [["AB", "A", "B", "eave"], ["BC", "B", "C", "rake"], ["CD", "C", "D", "ridge"], ["DA", "D", "A", "rake"], ["BE", "B", "E", "rake"], ["EF", "E", "F", "eave"], ["FA", "F", "A", "rake"]]) { const r = C.addEdge(d, v[a], v[b], t); d = r.doc; e[name] = r.edgeId; }
  const f1 = C.createFacet(d, [e.AB, e.BC, e.CD, e.DA], {}); d = f1.doc;
  const f2 = C.createFacet(d, [e.AB, e.BE, e.EF, e.FA], {}); d = f2.doc;
  return { d, v, e, f1: f1.facetId, f2: f2.facetId };
}
{
  const { d, e } = sharedFacet();
  const vr = C.addVertex(d, 30, 0); const V = vr.vertexId;
  const r = C.insertExistingVertexIntoEdge(vr.doc, V, e.AB, 5, 0);
  assert.ok(r.ok); ok("shared-facet insert still passes");
  const f1 = r.doc.facets[0], f2 = r.doc.facets[1];
  assert.ok(f1.edgeIds.includes(r.edgeIds[0]) && f1.edgeIds.includes(r.edgeIds[1])); ok("shared-facet insert updates facet 1 (A-V + V-B)");
  assert.ok(f2.edgeIds.includes(r.edgeIds[0]) && f2.edgeIds.includes(r.edgeIds[1])); ok("shared-facet insert updates facet 2 (shared topology preserved)");
  assert.strictEqual(C.vById(r.doc, V).x, 5); ok("shared-facet insert reuses the same dragged vertex id");
  assert.strictEqual(core.validateSketch(r.doc).errors.length, 0); ok("shared-facet insert result validates");
}

// ===================== DECISION INVALIDATION =====================
{
  const { d, v, e } = rect();
  let doc = setDec(setDec(setDec(setDec(d, e.AB), e.DA), e.CD), abUuid); // AB(removed), DA(rewired), CD(unrelated), relational UUID
  const r = C.mergeVertices(doc, v.A, v.B);
  assert.ok(r.ok);
  assert.ok(!hasDec(r.doc, e.AB)); ok("removed-edge decision cleared on merge");
  assert.ok(!hasDec(r.doc, e.DA)); ok("rewired surviving-edge decision cleared on merge (endpoints changed)");
  assert.ok(hasDec(r.doc, e.CD)); ok("unrelated graph decision preserved on merge");
  assert.ok(hasDec(r.doc, abUuid)); ok("relational MeasurementEdge-UUID decision preserved on merge");
}
{
  // insert: moved-vertex incident graph decision cleared; target edge decision cleared
  let d = core.createSketchDocument({ structureId: "S" });
  const v = {};
  for (const [name, x, y] of [["A", 0, 0], ["B", 10, 0], ["C", 10, 8], ["D", 0, 8], ["G", 5, -8]]) { const r = C.addVertex(d, x, y); d = r.doc; v[name] = r.vertexId; }
  const e = {};
  for (const [name, a, b] of [["AB", "A", "B"], ["BC", "B", "C"], ["CD", "C", "D"], ["DA", "D", "A"]]) { const r = C.addEdge(d, v[a], v[b], "eave"); d = r.doc; e[name] = r.edgeId; }
  d = C.createFacet(d, [e.AB, e.BC, e.CD, e.DA], {}).doc;
  const vr = C.addVertex(d, 5, -4); const V = vr.vertexId; d = vr.doc;
  const eg = C.addEdge(d, V, v.G, "rake"); d = eg.doc; const VG = eg.edgeId;
  let doc = setDec(setDec(setDec(d, e.AB), VG), abUuid);
  const r = C.insertExistingVertexIntoEdge(doc, V, e.AB, 5, 0);
  assert.ok(r.ok);
  assert.ok(!hasDec(r.doc, e.AB)); ok("insert clears the replaced target-edge decision");
  assert.ok(!hasDec(r.doc, VG)); ok("insert clears the moved vertex's incident-edge decision");
  assert.ok(hasDec(r.doc, abUuid)); ok("insert preserves relational MeasurementEdge-UUID decision");
}
{
  // free vertex move (pointer-up) invalidates incident graph decisions only
  let d = core.createSketchDocument({ structureId: "S" });
  const v = {};
  for (const [name, x, y] of [["P", 5, 5], ["Q", 0, 0], ["R", 10, 0]]) { const r = C.addVertex(d, x, y); d = r.doc; v[name] = r.vertexId; }
  const e = {};
  for (const [name, a, b] of [["PQ", "P", "Q"], ["PR", "P", "R"], ["QR", "Q", "R"]]) { const r = C.addEdge(d, v[a], v[b], "eave"); d = r.doc; e[name] = r.edgeId; }
  let doc = setDec(setDec(setDec(setDec(d, e.PQ), e.PR), e.QR), abUuid);
  const r = G.applyVertexDrop(doc, v.P, { type: "free", point: [6, 6] });
  assert.ok(r.ok);
  assert.ok(!hasDec(r.doc, e.PQ) && !hasDec(r.doc, e.PR)); ok("free move clears incident graph-edge decisions (E1,E2)");
  assert.ok(hasDec(r.doc, e.QR)); ok("free move preserves unrelated graph-edge decision");
  assert.ok(hasDec(r.doc, abUuid)); ok("free move preserves relational MeasurementEdge-UUID decision");
}

// ===================== SHARED VALIDATION =====================
{
  const d = core.createSketchDocument({ structureId: "S" });
  d.vertices = [{ id: "a", x: 0, y: 0 }, { id: "b", x: 10, y: 0 }];
  d.edges = [{ id: "e1", v1: "a", v2: "b", type: "eave" }, { id: "e2", v1: "b", v2: "a", type: "rake" }];
  const errs = core.validateSketch(d).errors;
  assert.ok(errs.some((e) => e.code === "duplicate_edge")); ok("shared core: A-B / B-A hard-fail as duplicate_edge");
}
{
  const d = core.createSketchDocument({ structureId: "S" });
  d.vertices = [{ id: "a", x: 0, y: 0 }, { id: "b", x: 10, y: 0 }, { id: "c", x: 20, y: 0 }];
  d.edges = [{ id: "e1", v1: "a", v2: "b", type: "eave" }, { id: "e2", v1: "b", v2: "c", type: "rake" }];
  assert.ok(!core.validateSketch(d).errors.some((e) => e.code === "duplicate_edge")); ok("shared core: A-B / B-C is NOT a duplicate");
}

// ===================== JOIN =====================
// facet with a degree-2 middle vertex M between A and B
function joinRect(order) {
  let d = core.createSketchDocument({ structureId: "S" });
  const v = {};
  for (const [name, x, y] of [["A", 0, 0], ["M", 5, 0], ["B", 10, 0], ["C", 10, 8], ["D", 0, 8]]) { const r = C.addVertex(d, x, y); d = r.doc; v[name] = r.vertexId; }
  const e = {};
  for (const [name, a, b, t] of [["AM", "A", "M", "eave"], ["MB", "M", "B", "eave"], ["BC", "B", "C", "rake"], ["CD", "C", "D", "ridge"], ["DA", "D", "A", "rake"]]) { const r = C.addEdge(d, v[a], v[b], t); d = r.doc; e[name] = r.edgeId; }
  const loop = order; // array of edge names
  const f = C.createFacet(d, loop.map((k) => e[k]), {}); d = f.doc;
  return { d, v, e, facetId: f.facetId };
}
{
  const { d, e } = joinRect(["AM", "MB", "BC", "CD", "DA"]); // in-array adjacency at 0,1
  const r = C.joinEdges(d, e.AM, e.MB);
  assert.ok(r.ok); ok("normal in-array facet join succeeds");
  const f = r.doc.facets[0];
  assert.strictEqual(f.edgeIds.filter((id) => id === r.edgeId).length, 1); ok("normal join: joined edge appears exactly once");
  assert.strictEqual(f.edgeIds.length, 4); ok("normal join: facet reduced by one edge");
  assert.strictEqual(core.validateSketch(r.doc).errors.length, 0); ok("normal join result validates");
}
{
  const { d, e } = joinRect(["MB", "BC", "CD", "DA", "AM"]); // AM last, MB first -> cyclic adjacency
  const r = C.joinEdges(d, e.MB, e.AM);
  assert.ok(r.ok); ok("cyclic last->first facet join succeeds");
  const f = r.doc.facets[0];
  assert.strictEqual(f.edgeIds.filter((id) => id === r.edgeId).length, 1); ok("cyclic join: joined edge appears exactly once (no double-J)");
  assert.strictEqual(f.edgeIds.length, 4); ok("cyclic join: facet reduced by one edge");
  assert.strictEqual(core.validateSketch(r.doc).errors.length, 0); ok("cyclic join result validates");
}
// shared-facet join: two facets share the consecutive pair A-M, M-B
function joinShared() {
  let d = core.createSketchDocument({ structureId: "S" });
  const v = {};
  for (const [name, x, y] of [["A", 0, 0], ["M", 5, 0], ["B", 10, 0], ["C", 10, 8], ["D", 0, 8], ["E", 10, -8], ["F", 0, -8]]) { const r = C.addVertex(d, x, y); d = r.doc; v[name] = r.vertexId; }
  const e = {};
  for (const [name, a, b, t] of [["AM", "A", "M", "eave"], ["MB", "M", "B", "eave"], ["BC", "B", "C", "rake"], ["CD", "C", "D", "ridge"], ["DA", "D", "A", "rake"], ["BE", "B", "E", "rake"], ["EF", "E", "F", "eave"], ["FA", "F", "A", "rake"]]) { const r = C.addEdge(d, v[a], v[b], t); d = r.doc; e[name] = r.edgeId; }
  const f1 = C.createFacet(d, [e.AM, e.MB, e.BC, e.CD, e.DA], {}); d = f1.doc;
  const f2 = C.createFacet(d, [e.AM, e.MB, e.BE, e.EF, e.FA], {}); d = f2.doc;
  return { d, v, e, f1: f1.facetId, f2: f2.facetId };
}
{
  const { d, e } = joinShared();
  const r = C.joinEdges(d, e.AM, e.MB);
  assert.ok(r.ok); ok("shared-facet join succeeds");
  const f1 = r.doc.facets[0], f2 = r.doc.facets[1];
  assert.ok(f1.edgeIds.includes(r.edgeId) && f2.edgeIds.includes(r.edgeId)); ok("shared-facet join: joined edge shared by both facets");
  assert.strictEqual(f1.edgeIds.filter((id) => id === r.edgeId).length, 1); ok("shared-facet join: single J in facet 1");
  assert.strictEqual(f2.edgeIds.filter((id) => id === r.edgeId).length, 1); ok("shared-facet join: single J in facet 2");
  assert.strictEqual(core.validateSketch(r.doc).errors.length, 0); ok("shared-facet join result validates");
}
// protected join matrix (all four states on a source edge) + both-order
for (const [label, mut] of [
  ["measurement_edge_id", (x) => ({ ...x, measurement_edge_id: abUuid })],
  ["relational_edge_id", (x) => ({ ...x, relational_edge_id: abUuid })],
  ["confirmed_length_ft", (x) => ({ ...x, confirmed_length_ft: 5 })],
  ["locked", (x) => ({ ...x, locked: true })],
]) {
  const { d, e } = joinRect(["AM", "MB", "BC", "CD", "DA"]);
  const prot = { ...d, edges: d.edges.map((x) => (x.id === e.AM ? mut(x) : x)) };
  const r1 = C.joinEdges(prot, e.AM, e.MB);
  const r2 = C.joinEdges(prot, e.MB, e.AM);
  assert.ok(!r1.ok && r1.reason === "edge_protected" && r1.doc === prot);
  assert.ok(!r2.ok && r2.reason === "edge_protected" && r2.doc === prot);
  ok(`protected join rejected — ${label} (both source orders, doc unchanged)`);
}
{
  const { d, e } = joinRect(["AM", "MB", "BC", "CD", "DA"]);
  let doc = setDec(setDec(d, e.AM), e.MB);
  const r = C.joinEdges(doc, e.AM, e.MB);
  assert.ok(r.ok && !hasDec(r.doc, e.AM) && !hasDec(r.doc, e.MB)); ok("join invalidates both source graph decisions");
}

// ===================== MERGE TYPE MATRIX =====================
function dupMergeSetup(t1, t2, firstIsE1 = true) {
  // edges A-B (t1) and A-C (t2); merge C->B makes A-C a duplicate of A-B.
  let d = core.createSketchDocument({ structureId: "S" });
  const A = C.addVertex(d, 0, 0); d = A.doc; const B = C.addVertex(d, 10, 0); d = B.doc; const Cc = C.addVertex(d, 10, 5); d = Cc.doc;
  let e1, e2;
  if (firstIsE1) { e1 = C.addEdge(d, A.vertexId, B.vertexId, t1); d = e1.doc; e2 = C.addEdge(d, A.vertexId, Cc.vertexId, t2); d = e2.doc; }
  else { e2 = C.addEdge(d, A.vertexId, Cc.vertexId, t2); d = e2.doc; e1 = C.addEdge(d, A.vertexId, B.vertexId, t1); d = e1.doc; }
  return { d, A: A.vertexId, B: B.vertexId, Cc: Cc.vertexId };
}
function mergedType(t1, t2, order) {
  const s = dupMergeSetup(t1, t2, order);
  const r = C.mergeVertices(s.d, s.Cc, s.B);
  if (!r.ok) return { reason: r.reason };
  const surv = r.doc.edges.find((e) => C.eById(r.doc, e.id));
  return { type: r.doc.edges[0].type };
}
for (const order of [true, false]) {
  assert.strictEqual(mergedType("eave", "eave", order).type, "eave");
  assert.strictEqual(mergedType("unclassified", "ridge", order).type, "ridge");
  assert.strictEqual(mergedType("ridge", "unclassified", order).type, "ridge");
  assert.strictEqual(mergedType("ridge", "hip", order).reason, "incompatible_duplicate_edges");
}
ok("merge type matrix: eave+eave→eave, unclassified+ridge→ridge, ridge+unclassified→ridge, ridge+hip→reject (both orders)");

// ===================== MERGE PROTECTED-DUPLICATE MATRIX =====================
for (const [label, m1, m2] of [
  ["unmapped + mapped", {}, { measurement_edge_id: abUuid }],
  ["mapped + unmapped", { measurement_edge_id: abUuid }, {}],
  ["relational + none", { relational_edge_id: abUuid }, {}],
  ["unconfirmed + confirmed", {}, { confirmed_length_ft: 9 }],
  ["confirmed + unconfirmed", { confirmed_length_ft: 9 }, {}],
  ["unlocked + locked", {}, { locked: true }],
  ["locked + unlocked", { locked: true }, {}],
]) {
  for (const order of [true, false]) {
    const s = dupMergeSetup("eave", "eave", order);
    // apply protection: m1 on A-B (e1), m2 on A-C (e2)
    const doc = { ...s.d, edges: s.d.edges.map((e) => {
      if (e.v1 === s.A && e.v2 === s.B) return { ...e, ...m1 };
      if (e.v1 === s.A && e.v2 === s.Cc) return { ...e, ...m2 };
      return e;
    }) };
    const r = C.mergeVertices(doc, s.Cc, s.B);
    assert.ok(!r.ok && r.reason === "protected_duplicate_collapse", `${label} order=${order}: ${r.reason}`);
    assert.strictEqual(r.doc, doc);
  }
  ok(`protected-duplicate merge rejected — ${label} (both orders, doc unchanged)`);
}

console.log("\nROOF SKETCH TOPOLOGY INTEGRITY (Phase 3 FINAL): all " + n + " assertions passed");
