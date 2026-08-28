"use strict";
// Phase 3 Part A live-gesture contracts (Node, no React): insertExistingVertexIntoEdge, the pure gesture
// resolvers (drawSnap/dragSnap/candidateFor), and the atomic gesture applications (applyDrawPoint/
// applyVertexDrop). Proves protected blocking, incident-edge ineligibility, split+insert topology,
// vertex-merge, manual-mode protection, stale-decision drop, and single-mutation (one-history) results.
const assert = require("assert");
const path = require("path");
const babel = require("@babel/core");

// Transform local ESM roof-sketch modules (and their nested relative imports) to CommonJS on require.
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

function rect() {
  let d = core.createSketchDocument({ structureId: "S" });
  const v = [];
  for (const [x, y] of [[0, 0], [10, 0], [10, 8], [0, 8]]) { const r = C.addVertex(d, x, y); d = r.doc; v.push(r.vertexId); }
  const eids = [];
  for (const [i, j, t] of [[0, 1, "eave"], [1, 2, "rake"], [2, 3, "ridge"], [3, 0, "rake"]]) { const r = C.addEdge(d, v[i], v[j], t); d = r.doc; eids.push(r.edgeId); }
  const f = C.createFacet(d, eids, { pitch_rise: 6 }); d = f.doc;
  return { d, v, eids, facetId: f.facetId };
}

// ---- insertExistingVertexIntoEdge ----
{
  // free-standing vertex dropped onto an eave edge interior
  const { d, eids } = rect();
  const nv = C.addVertex(d, 5, -6); let d2 = nv.doc;
  const r = C.insertExistingVertexIntoEdge(d2, nv.vertexId, eids[0], 5.3, 0.9);
  assert.ok(r.ok); ok("insertExistingVertexIntoEdge succeeds on an eligible edge");
  assert.strictEqual(C.vById(r.doc, nv.vertexId).y, 0); ok("dragged vertex is moved to the PROJECTED point on the segment (y=0)");
  assert.ok(Math.abs(C.vById(r.doc, nv.vertexId).x - 5.3) < 1e-9); ok("dragged vertex x = projected x (reused, not a new vertex)");
  assert.strictEqual((r.doc.vertices || []).length, (d2.vertices || []).length); ok("no new vertex created (existing id reused)");
  assert.ok(!C.eById(r.doc, eids[0])); ok("target edge replaced");
  assert.strictEqual((r.doc.edges || []).length, (d2.edges || []).length + 1); ok("one edge became two");
  const f = r.doc.facets[0];
  assert.ok(f.edgeIds.includes(r.edgeIds[0]) && f.edgeIds.includes(r.edgeIds[1])); ok("facet loop references both child edges");
  assert.strictEqual(core.validateSketch(r.doc).errors.length, 0); ok("insert result validates (closed loop preserved)");
}
{
  // protected target refused, doc unchanged
  const { d, eids } = rect();
  const nv = C.addVertex(d, 5, -6); let d2 = nv.doc;
  const prot = { ...d2, edges: d2.edges.map((e) => (e.id === eids[0] ? { ...e, locked: true, confirmed_length_ft: 20 } : e)) };
  const r = C.insertExistingVertexIntoEdge(prot, nv.vertexId, eids[0], 5, 0);
  assert.ok(!r.ok && r.reason === "edge_protected"); assert.strictEqual(r.doc, prot); ok("insert into protected edge refused, doc unchanged");
}
{
  // an edge already incident to the vertex is not a valid target
  const { d, eids, v } = rect();
  const r = C.insertExistingVertexIntoEdge(d, v[0], eids[0], 5, 0); // v0 is an endpoint of eids[0]
  assert.ok(!r.ok && r.reason === "vertex_on_edge"); ok("cannot insert a vertex into an edge it already belongs to");
}
{
  // connected-graph only
  const man = { ...core.createSketchDocument({ structureId: "S" }), edit_mode: "manual_polygon" };
  assert.strictEqual(C.insertExistingVertexIntoEdge(man, "v", "e", 0, 0).reason, "connected_graph_required"); ok("insertExistingVertexIntoEdge rejected in manual_polygon");
}
{
  // stale edge proposal decision dropped after insert
  const { d, eids } = rect();
  const nv = C.addVertex(d, 5, -6); let d2 = nv.doc;
  d2 = C.setProposalDecision(d2, { targetType: "edge", targetId: eids[0], metric: "length_ft", decision: "keep_current", value: 10 });
  assert.ok(C.decisionFor(d2, "edge", eids[0], "length_ft")); ok("edge decision present before insert");
  const r = C.insertExistingVertexIntoEdge(d2, nv.vertexId, eids[0], 5, 0);
  assert.ok(r.ok && !C.decisionFor(r.doc, "edge", eids[0], "length_ft")); ok("insert drops the stale decision for the replaced edge");
}

// ---- candidateFor / drawSnap / dragSnap ----
{
  const { d, eids } = rect();
  const near = G.candidateFor(d, { type: "edge", edgeId: eids[0], point: [5, 0] });
  assert.strictEqual(near.type, "edge"); ok("candidateFor: non-protected edge stays an edge candidate");
  const prot = { ...d, edges: d.edges.map((e) => (e.id === eids[0] ? { ...e, locked: true } : e)) };
  const blocked = G.candidateFor(prot, { type: "edge", edgeId: eids[0], point: [5, 0] });
  assert.strictEqual(blocked.type, "blocked"); ok("candidateFor: protected edge becomes a BLOCKED candidate (never free)");
  assert.strictEqual(G.candidateFor(d, { type: "vertex", vertexId: "x", point: [0, 0] }).type, "vertex"); ok("candidateFor: vertex candidate passes through");
}
{
  const { d, eids } = rect();
  // point near the middle of eave edge eids[0] (interior), far from any vertex
  const conn = G.drawSnap(d, [5, 0.2], core.projectPointToSegment ? 0.6 : 0.6);
  assert.strictEqual(conn.type, "edge"); ok("drawSnap (connected): interior point snaps to an edge candidate");
  const man = G.drawSnap(d, [5, 0.2], 0.6, { manual: true });
  assert.notStrictEqual(man.type, "edge"); ok("drawSnap (manual): never returns an edge candidate (no split in manual mode)");
}
{
  const { d, v, eids } = rect();
  // dragging v0 near its own incident edge eids[0] must NOT treat that edge as an eligible target
  const snap = G.dragSnap(d, v[0], [5, 0.2], 0.6);
  assert.ok(!(snap.type === "edge" && snap.edgeId === eids[0])); ok("dragSnap: the dragged vertex's own incident edge is not an eligible target");
  // dragging v0 onto v1 (a different vertex) snaps to that vertex
  const snapV = G.dragSnap(d, v[0], [10, 0.05], 0.6);
  assert.ok(snapV.type === "vertex" && snapV.vertexId === v[1]); ok("dragSnap: snaps to a different vertex, excluding itself");
}

// ---- applyDrawPoint (atomic single-mutation) ----
{
  const { d, v } = rect();
  const before = { ...d };
  // draw a new free point chained from v1
  const r = G.applyDrawPoint(d, { type: "free", point: [3, 12] }, v[1]);
  assert.ok(r.ok); ok("applyDrawPoint(free): places a vertex");
  assert.strictEqual(r.doc.vertices.length, before.vertices.length + 1); ok("applyDrawPoint(free): exactly one new vertex");
  assert.strictEqual(r.doc.edges.length, before.edges.length + 1); ok("applyDrawPoint(free): chained exactly one edge from the previous vertex");
}
{
  const { d, eids, v } = rect();
  // draw onto an edge interior -> split + chain, in ONE resulting doc
  const before = d.edges.length;
  const r = G.applyDrawPoint(d, { type: "edge", edgeId: eids[2], point: [5, 8] }, v[0]);
  assert.ok(r.ok); ok("applyDrawPoint(edge): split+chain succeeds");
  assert.ok(!C.eById(r.doc, eids[2])); ok("applyDrawPoint(edge): the split edge is gone (replaced by two + a chain)");
  assert.strictEqual(r.doc.edges.length, before + 2); ok("applyDrawPoint(edge): net +2 edges (split into two, then one chain edge) in a single doc");
  assert.ok(r.doc.edges.some((e) => (e.v1 === v[0] && e.v2 === r.vertexId) || (e.v2 === v[0] && e.v1 === r.vertexId))); ok("applyDrawPoint(edge): chained an edge from the previous vertex to the new split vertex");
}
{
  const { d, eids, v } = rect();
  const prot = { ...d, edges: d.edges.map((e) => (e.id === eids[0] ? { ...e, measurement_edge_id: "ME1" } : e)) };
  const r = G.applyDrawPoint(prot, { type: "blocked", edgeId: eids[0], point: [5, 0] }, v[1]);
  assert.ok(!r.ok && r.reason === "edge_protected"); assert.strictEqual(r.doc, prot); ok("applyDrawPoint(blocked): protected edge makes no change");
}

// ---- applyVertexDrop (atomic single-mutation) ----
{
  // vertex -> vertex merge
  let d = core.createSketchDocument({ structureId: "S" });
  const a = C.addVertex(d, 0, 0); d = a.doc; const b = C.addVertex(d, 10, 0); d = b.doc;
  const c = C.addVertex(d, 10, 0.05); d = c.doc; const dd = C.addVertex(d, 5, 5); d = dd.doc;
  d = C.addEdge(d, a.vertexId, b.vertexId, "eave").doc;
  d = C.addEdge(d, c.vertexId, dd.vertexId, "rake").doc;
  const r = G.applyVertexDrop(d, c.vertexId, { type: "vertex", vertexId: b.vertexId, point: [10, 0] });
  assert.ok(r.ok && !C.vById(r.doc, c.vertexId)); ok("applyVertexDrop(vertex): merges dragged vertex onto target");
}
{
  // edge -> split + insert (single mutation)
  const { d, eids } = rect();
  const nv = C.addVertex(d, 5, -6); let d2 = nv.doc;
  const r = G.applyVertexDrop(d2, nv.vertexId, { type: "edge", edgeId: eids[0], point: [5, 0] });
  assert.ok(r.ok && r.edgeIds && r.edgeIds.length === 2); ok("applyVertexDrop(edge): split+insert produces two child edges in one op");
  assert.strictEqual(C.vById(r.doc, nv.vertexId).y, 0); ok("applyVertexDrop(edge): dragged vertex reused on the segment");
}
{
  // blocked -> refused, doc unchanged
  const { d, eids } = rect();
  const nv = C.addVertex(d, 5, -6); let d2 = nv.doc;
  const r = G.applyVertexDrop(d2, nv.vertexId, { type: "blocked", edgeId: eids[0], point: [5, 0] });
  assert.ok(!r.ok && r.reason === "edge_protected"); assert.strictEqual(r.doc, d2); ok("applyVertexDrop(blocked): refused, doc unchanged");
}
{
  // free -> plain reposition
  const { d, v } = rect();
  const r = G.applyVertexDrop(d, v[0], { type: "free", point: [-3, -4] });
  assert.ok(r.ok); assert.deepStrictEqual([C.vById(r.doc, v[0]).x, C.vById(r.doc, v[0]).y], [-3, -4]); ok("applyVertexDrop(free): plain moveVertex reposition");
}

// ---- merge stale-decision drop (correction) ----
{
  let d = core.createSketchDocument({ structureId: "S" });
  const a = C.addVertex(d, 0, 0); d = a.doc; const b = C.addVertex(d, 10, 0); d = b.doc;
  const c = C.addVertex(d, 10, 0.05); d = c.doc; const dd = C.addVertex(d, 5, 5); d = dd.doc;
  // two edges that will become duplicates a-b after merging c onto b (a-b and a-... ) — build a collapsible dup
  const e1 = C.addEdge(d, a.vertexId, b.vertexId, "eave"); d = e1.doc;
  const e2 = C.addEdge(d, a.vertexId, c.vertexId, "eave"); d = e2.doc; // a-c ; merging c->b makes a-b duplicate of e1
  d = C.setProposalDecision(d, { targetType: "edge", targetId: e2.edgeId, metric: "length_ft", decision: "keep_current", value: 9 });
  const r = C.mergeVertices(d, c.vertexId, b.vertexId);
  assert.ok(r.ok); ok("merge collapses a compatible duplicate edge");
  assert.ok(!C.decisionFor(r.doc, "edge", e2.edgeId, "length_ft")); ok("merge drops the stale decision for a collapsed duplicate edge");
}

// ---- manual polygon protection for all graph ops ----
{
  const man = { ...core.createSketchDocument({ structureId: "S" }), edit_mode: "manual_polygon" };
  assert.strictEqual(C.splitEdgeSafe(man, "e", 0, 0).reason, "connected_graph_required");
  assert.strictEqual(C.mergeVertices(man, "a", "b").reason, "connected_graph_required");
  assert.strictEqual(C.joinEdges(man, "a", "b").reason, "connected_graph_required");
  assert.strictEqual(C.insertExistingVertexIntoEdge(man, "v", "e", 0, 0).reason, "connected_graph_required");
  ok("all graph topology ops (split/merge/join/insert) are blocked in manual_polygon");
}

console.log("\nROOF SKETCH GESTURE OPS (Phase 3 Part A): all " + n + " assertions passed");
