"use strict";
// Pure editor command + history + state tests (Node). Loads the ESM modules by transforming import/
// export to CommonJS so no browser/React runtime is needed. Run: node <thisfile>
const assert = require("assert");
const path = require("path");
const Module = require("module");
const babel = require("@babel/core");

function load(rel) {
  const file = path.resolve(__dirname, rel);
  const { code } = babel.transformFileSync(file, { plugins: ["@babel/plugin-transform-modules-commonjs"] });
  const m = new Module(file, module);
  m.filename = file;
  m.paths = Module._nodeModulePaths(path.dirname(file));
  m._compile(code, file);
  return m.exports;
}

const C = load("../commands.js");
const H = load("../historyCore.js");
const core = require("@roofspan/roof-sketch-core");

let n = 0;
const ok = (name) => { n++; console.log("  \u2713 " + name); };
const doc0 = () => core.createSketchDocument({ structureId: "s1" });

// --- vertices ---
let r = C.addVertex(doc0(), 1, 2);
assert.strictEqual(r.doc.vertices.length, 1);
assert.deepStrictEqual([r.doc.vertices[0].x, r.doc.vertices[0].y], [1, 2]); ok("addVertex");
let d = C.moveVertex(r.doc, r.vertexId, 5, 6);
assert.deepStrictEqual([C.vById(d, r.vertexId).x, C.vById(d, r.vertexId).y], [5, 6]); ok("moveVertex");

// --- shared vertex affects all connected geometry ---
{
  let a = C.addVertex(doc0(), 0, 0); let v0 = a.vertexId;
  let b = C.addVertex(a.doc, 10, 0); let v1 = b.vertexId;
  let c = C.addVertex(b.doc, 0, 10); let v2 = c.vertexId;
  let e1 = C.addEdge(c.doc, v0, v1); let e2 = C.addEdge(e1.doc, v0, v2);
  let dd = e2.doc;
  assert.strictEqual(dd.edges.length, 2); ok("addEdge x2 sharing v0");
  dd = C.moveVertex(dd, v0, -3, -4);
  const eA = dd.edges.find((e) => e.id === e1.edgeId), eB = dd.edges.find((e) => e.id === e2.edgeId);
  const shared = C.vById(dd, v0);
  assert.ok(eA.v1 === v0 && eB.v1 === v0 && shared.x === -3 && shared.y === -4);
  ok("moving a shared vertex updates every connected edge (single graph node)");
}

// --- split edge preserves loop + creates two edges ---
{
  const verts = [[0, 0], [10, 0], [10, 10], [0, 10]];
  let dd = doc0(); const ids = [];
  verts.forEach(([x, y]) => { const a = C.addVertex(dd, x, y); dd = a.doc; ids.push(a.vertexId); });
  const eids = [];
  for (let i = 0; i < 4; i++) { const a = C.addEdge(dd, ids[i], ids[(i + 1) % 4]); dd = a.doc; eids.push(a.edgeId); }
  const cf = C.createFacet(dd, eids); dd = cf.doc;
  assert.strictEqual(core.validateSketch(dd).valid, true); ok("createFacet from a closed edge loop is valid");
  const before = dd.edges.length;
  dd = C.splitEdge(dd, eids[0], 5, 0);
  assert.strictEqual(dd.edges.length, before + 1); ok("splitEdge adds one edge");
  assert.strictEqual(core.validateSketch(dd).valid, true); ok("split facet loop remains valid");
}

// --- calibration + locked edge authority ---
{
  let a = C.addVertex(doc0(), 0, 0); let b = C.addVertex(a.doc, 10, 0);
  let e = C.addEdge(b.doc, a.vertexId, b.vertexId); // v0->v1
  let dd = e.doc; const eid = e.edgeId;
  dd = C.setScale(dd, { edgeId: eid, realFeet: 25 });
  assert.ok(dd.scale.resolved && Math.abs(dd.scale.feetPerUnit - 2.5) < 1e-9); ok("setScale calibrates feetPerUnit from a known edge");
  dd = C.setConfirmedEdgeLength(dd, eid, 25);
  dd = C.lockEdge(dd, eid);
  dd = C.moveVertex(dd, b.vertexId, 20, 0); // geometry now 20 units * 2.5 = 50ft, but confirmed stays 25
  const edge = dd.edges.find((x) => x.id === eid);
  assert.ok(edge.locked === true && edge.confirmed_length_ft === 25); ok("locked confirmed length is not overwritten when geometry moves");
  const props = core.deriveProposals(dd);
  assert.ok(props.some((p) => p.code === "locked_edge_discrepancy" && p.confirmed === 25));
  ok("locked edge yields a discrepancy notice, never an overwrite proposal");
}

// --- manual polygon state ---
{
  let dd = C.setEditMode(doc0(), "manual_polygon");
  assert.strictEqual(dd.edit_mode, "manual_polygon"); ok("setEditMode -> manual_polygon");
  const pts = [[0, 0], [8, 0], [8, 8], [0, 8]]; const ids = [];
  pts.forEach(([x, y]) => { const a = C.addVertex(dd, x, y); dd = a.doc; ids.push(a.vertexId); });
  const cf = C.createManualFacet(dd, ids); dd = cf.doc;
  assert.strictEqual(core.validateSketch(dd).valid, true); ok("manual polygon facet from vertexIds is valid");
}

// --- proposal decisions: accept + keep-current are explicit and recorded ---
{
  let dd = doc0();
  dd = C.setProposalDecision(dd, { targetType: "facet", targetId: "f1", metric: "area_sqft", decision: "accepted", value: 428 });
  let dec = C.decisionFor(dd, "facet", "f1", "area_sqft");
  assert.ok(dec.decision === "accepted" && dec.value === 428); ok("setProposalDecision records an explicit accept");
  dd = C.setProposalDecision(dd, { targetType: "facet", targetId: "f1", metric: "area_sqft", decision: "keep_current" });
  dec = C.decisionFor(dd, "facet", "f1", "area_sqft");
  assert.ok(dec.decision === "keep_current" && dd.proposal_decisions.length === 1); ok("keep-current replaces the prior decision (no duplicates)");
}

// --- history: undo / redo / cap 100 / redo cleared after a new edit ---
{
  let h = H.makeHistory("s0");
  h = H.push(h, "s1"); h = H.push(h, "s2");
  assert.strictEqual(h.present, "s2");
  h = H.undo(h); assert.strictEqual(h.present, "s1"); ok("history undo");
  h = H.redo(h); assert.strictEqual(h.present, "s2"); ok("history redo");
  h = H.undo(h); h = H.push(h, "s9");
  assert.strictEqual(h.present, "s9"); assert.strictEqual(H.canRedo(h), false); ok("a new edit after undo clears the redo branch");
  let big = H.makeHistory(0);
  for (let i = 1; i <= 150; i++) big = H.push(big, i);
  assert.strictEqual(big.past.length, H.MAX_HISTORY); ok("history capped at 100 states");
}

console.log("\nROOF SKETCH EDITOR (commands + history): all " + n + " assertions passed");
