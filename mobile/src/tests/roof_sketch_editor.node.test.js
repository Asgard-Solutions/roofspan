"use strict";
// Field Roof Sketch editor/controller contracts (Node, no device). Exercises the pure controller +
// the shared engine it delegates to, plus a static no-duplication check on the new Field files.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const RS = require("@roofspan/roof-sketch-core");
const { resolveInitialSketch, createFieldEditor } = require("../roofSketchFieldController");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

// in-memory persistence keyed by draft key; records write order + generations
function makeStore() {
  const store = {}; const order = [];
  const persist = async (draft, gen) => {
    const key = `${draft.revision_id}:${draft.structure_id}`;
    order.push({ key, gen, doc: draft.document });
    store[key] = draft; // last write wins (chain guarantees generation order)
  };
  return { store, order, persist };
}
function editor(structureId, initialOverride, persist) {
  const initial = initialOverride || resolveInitialSketch({ structureId });
  return createFieldEditor({ revisionId: "rev1", structureId, initial, persist });
}
function connectedRect() {
  const d = RS.createSketchDocument({ structureId: "sX" });
  d.vertices = [{ id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }, { id: "v3", x: 10, y: 8 }, { id: "v4", x: 0, y: 8 }];
  d.edges = [
    { id: "e1", v1: "v1", v2: "v2", type: "eave" }, { id: "e2", v1: "v2", v2: "v3", type: "rake" },
    { id: "e3", v1: "v3", v2: "v4", type: "eave" }, { id: "e4", v1: "v4", v2: "v1", type: "rake" },
  ];
  d.facets = [{ id: "f1", label: "F1", edgeIds: ["e1", "e2", "e3", "e4"], vertexIds: [], pitch_rise: 6 }];
  return d;
}

;(async () => {
// ---- load resolution ----
{
  const empty = resolveInitialSketch({ structureId: "sX" });
  assert.strictEqual(empty.source, "new");
  assert.deepStrictEqual(empty.document.vertices, []); ok("new empty sketch created for a fresh structure");

  const server = resolveInitialSketch({ server: { document: { edit_mode: "connected_graph", vertices: [{ id: "v1", x: 1, y: 2 }] }, document_version: 5 }, structureId: "sX" });
  assert.strictEqual(server.source, "server");
  assert.strictEqual(server.documentVersion, 5);
  assert.strictEqual(server.document.vertices.length, 1); ok("server sketch loaded + normalized when no local draft");

  const draft = resolveInitialSketch({
    draft: { document: { edit_mode: "manual_polygon", vertices: [{ id: "vA", x: 9, y: 9 }] }, document_version: 2, edit_generation: 7 },
    server: { document: { vertices: [{ id: "v1", x: 1, y: 1 }] }, document_version: 5 },
    structureId: "sX",
  });
  assert.strictEqual(draft.source, "local_draft");
  assert.strictEqual(draft.editGeneration, 7);
  assert.strictEqual(draft.document.vertices[0].id, "vA"); ok("local draft WINS over server sketch (B2A authoritative-local)");
}

// ---- commit / preview / generation / persistence ----
{
  const { store, order, persist } = makeStore();
  const ed = editor("sX", null, persist);
  const a = RS.addVertex(ed.document, 3, 4);
  ed.commit(a.doc);
  assert.strictEqual(ed.editGeneration, 2, "commit bumps edit_generation"); ok("committed edit bumps generation");
  const before = ed.editGeneration;
  ed.preview(RS.addVertex(ed.document, 9, 9).doc);
  assert.strictEqual(ed.editGeneration, before, "preview does NOT bump generation"); ok("preview does not change edit generation");
  ed.restore();
  assert.strictEqual(ed.document.vertices.length, 1, "restore discards preview"); ok("restore() discards preview to last committed doc");
  await ed.flush();
  assert.ok(store["rev1:sX"], "committed edit persisted locally"); ok("committed edit persisted to local draft store");
  assert.strictEqual(order.filter((o) => o.key === "rev1:sX").length, 1, "preview produced no persist"); ok("preview produced no local persistence write");
}

// ---- serialized writes: generation order preserved, latest wins ----
{
  const { store, order, persist } = makeStore();
  const ed = editor("sX", null, persist);
  ed.commit(RS.addVertex(ed.document, 1, 1).doc);   // gen 2
  ed.commit(RS.addVertex(ed.document, 2, 2).doc);   // gen 3
  await ed.flush();
  const gens = order.map((o) => o.gen);
  assert.deepStrictEqual(gens, [...gens].sort((x, y) => x - y), "writes drained in generation order"); ok("serialized writes drain in strict generation order");
  assert.strictEqual(store["rev1:sX"].edit_generation, 3, "generation 3 is the final local draft"); ok("latest generation wins as the final local draft");
}

// ---- reopen restores latest draft ----
{
  const { store, persist } = makeStore();
  const ed = editor("sX", null, persist);
  ed.commit(RS.addVertex(ed.document, 5, 6).doc);
  await ed.flush();
  const reopened = editor("sX", resolveInitialSketch({ draft: store["rev1:sX"], structureId: "sX" }), persist);
  assert.strictEqual(reopened.document.vertices.length, 1);
  assert.strictEqual(reopened.document.vertices[0].x, 5); ok("leave + reopen restores the latest local draft (no network)");
}

// ---- structure isolation ----
{
  const { store, persist } = makeStore();
  const house = editor("main_house", null, persist);
  const garage = editor("garage", null, persist);
  house.commit(RS.addVertex(house.document, 1, 1).doc);
  await house.flush();
  assert.strictEqual(garage.document.vertices.length, 0, "garage unaffected by house edit"); ok("different structures are isolated (separate document + draft key)");
  assert.ok(store["rev1:main_house"] && !store["rev1:garage"], "separate draft keys"); ok("structures persist to separate draft keys");
}

// ---- draw / snap / topology through the controller + shared engine ----
{
  const ed = editor("sX", { document: connectedRect(), editMode: "connected_graph", editGeneration: 1, documentVersion: 0, source: "new" });
  // connected draw free point
  const tol = RS.modelTolerance(14, 1);
  const candFree = RS.drawSnap(ed.document, [50, 50], tol);
  assert.strictEqual(candFree.type, "free"); ok("connected draw resolves a free point away from geometry");
  const drawn = RS.applyDrawPoint(ed.document, candFree, null);
  ed.commit(drawn.doc);
  assert.ok(RS.vById(ed.document, drawn.vertexId)); ok("draw free point adds a vertex via shared applyDrawPoint");

  // vertex snapping priority
  const candV = RS.drawSnap(connectedRect(), [0.4, 0.3], 2);
  assert.strictEqual(candV.type, "vertex"); ok("draw snap prefers an existing vertex");
  // edge-interior snapping
  const candE = RS.drawSnap(connectedRect(), [5, -1], 2);
  assert.strictEqual(candE.type, "edge"); ok("draw snap resolves an edge interior");
  // protected edge blocked
  const locked = RS.lockEdge(connectedRect(), "e1");
  const blocked = RS.candidateFor(locked, { type: "edge", edgeId: "e1", point: [5, 0] });
  assert.strictEqual(blocked.type, "blocked"); ok("protected edge candidate is blocked (not free)");

  // draw -> edge split
  const split = RS.applyDrawPoint(connectedRect(), { type: "edge", edgeId: "e1", point: [5, 0] }, null);
  assert.ok(split.ok && !RS.eById(split.doc, "e1")); ok("draw onto an edge performs the safe split");

  // vertex -> vertex merge
  const merge = RS.applyVertexDrop(connectedRect(), "v4", { type: "vertex", vertexId: "v1" });
  assert.ok(merge.ok && !RS.vById(merge.doc, "v4")); ok("vertex->vertex drop merges");
  // vertex -> edge insert
  const withFree = connectedRect(); withFree.vertices.push({ id: "v5", x: 5, y: 3 });
  const insert = RS.applyVertexDrop(withFree, "v5", { type: "edge", edgeId: "e1", point: [5, 3] });
  assert.ok(insert.ok && !RS.eById(insert.doc, "e1")); ok("vertex->edge drop inserts (split)");
  // free vertex move
  const moved = RS.applyVertexDrop(connectedRect(), "v1", { type: "free", point: [-3, -3] });
  assert.ok(moved.ok && RS.vById(moved.doc, "v1").x === -3); ok("free drop repositions via moveVertexFinal");
  // failed drag restores original (protected)
  const lockedDoc = RS.lockEdge(connectedRect(), "e1");
  const failed = RS.applyVertexDrop(lockedDoc, "v3", { type: "blocked", edgeId: "e1", point: [5, 0] });
  assert.ok(!failed.ok && failed.doc === lockedDoc); ok("failed (blocked) drop returns the original document");
}

// ---- facet creation, manual polygon, manual blocks graph ops ----
{
  const ed = editor("sX", { document: RS.setEditMode(connectedRect(), "connected_graph"), editMode: "connected_graph", editGeneration: 1, source: "new" });
  const cf = RS.createFacet(ed.document, ["e1", "e2", "e3", "e4"]);
  assert.ok(cf.facetId); ok("connected facet creation via createFacet");

  let manual = RS.createSketchDocument({ structureId: "sX" });
  manual = RS.setEditMode(manual, "manual_polygon");
  const v1 = RS.addVertex(manual, 0, 0); const v2 = RS.addVertex(v1.doc, 10, 0); const v3 = RS.addVertex(v2.doc, 5, 8);
  const poly = RS.createManualFacet(v3.doc, [v1.vertexId, v2.vertexId, v3.vertexId]);
  assert.strictEqual(poly.doc.facets[0].vertexIds.length, 3); ok("manual polygon creation via createManualFacet");
  const blocked = RS.splitEdgeSafe(RS.setEditMode(connectedRect(), "manual_polygon"), "e1", 5, 3);
  assert.ok(!blocked.ok && blocked.reason === "connected_graph_required"); ok("manual mode blocks graph topology operations");
}

// ---- inspector-oriented commands: type / pitch / orientation / calibration / LF / confirmed / lock ----
{
  const rect = connectedRect();
  assert.strictEqual(RS.eById(RS.setEdgeType(rect, "e1", "ridge"), "e1").type, "ridge"); ok("edge type via setEdgeType");
  assert.strictEqual(RS.fById(RS.setFacetPitch(rect, "f1", 8), "f1").pitch_rise, 8); ok("pitch via setFacetPitch");
  assert.strictEqual(RS.fById(RS.setFacetOrientation(rect, "f1", "N"), "f1").orientation, "N"); ok("orientation via setFacetOrientation");
  const scaled = RS.setScale(rect, { edgeId: "e1", realFeet: 10 });
  assert.strictEqual(scaled.scale.feetPerUnit, 1); ok("calibration via setScale (10ft / 10u = 1)");
  const dimUnscaled = RS.edgeDimension(rect, RS.eById(rect, "e1"));
  assert.strictEqual(dimUnscaled.source, "unavailable"); ok("no fake LF before calibration");
  const dim = RS.edgeDimension(scaled, RS.eById(scaled, "e1"));
  assert.strictEqual(dim.valueFeet, 10); assert.strictEqual(RS.formatFeet(10), "10.0 LF"); ok("real LF label after calibration");
  const conf = RS.setConfirmedEdgeLength(scaled, "e1", 8);
  assert.strictEqual(RS.eById(conf, "e1").confirmed_length_ft, 8); ok("confirmed LF via setConfirmedEdgeLength");
  const locked = RS.lockEdge(conf, "e1");
  const dl = RS.edgeDimension(locked, RS.eById(locked, "e1"));
  assert.strictEqual(dl.source, "confirmed_locked"); assert.strictEqual(dl.valueFeet, 8); assert.strictEqual(dl.discrepancy, 2); ok("lock keeps confirmed LF authoritative; discrepancy = geometry - confirmed (+2)");
  assert.strictEqual(RS.eById(RS.unlockEdge(locked, "e1"), "e1").locked, false); ok("unlock via unlockEdge");
}

// ---- penetration add/move/type/delete + Join Edge ----
{
  const rect = connectedRect();
  const pp = RS.placePenetration(rect, 5, 4);
  assert.ok(pp.penetrationId && pp.doc.penetrations.length === 1); ok("penetration add via placePenetration");
  assert.strictEqual(RS.movePenetration(pp.doc, pp.penetrationId, 6, 5).penetrations[0].x, 6); ok("penetration move via movePenetration");
  assert.strictEqual(RS.setPenetrationType(pp.doc, pp.penetrationId, "skylight").penetrations[0].pen_type, "skylight"); ok("penetration type via setPenetrationType");
  assert.strictEqual(RS.deletePenetration(pp.doc, pp.penetrationId).penetrations.length, 0); ok("penetration delete via deletePenetration");
  // Join: rectangle e4 + e1 share v1 (cyclic)
  const joined = RS.joinEdges(rect, "e4", "e1", { resultType: "eave" });
  assert.ok(joined.ok); ok("Join Edge via joinEdges (cyclic wrap)");
}

// ---- undo / redo through the controller ----
{
  const ed = editor("sX", { document: connectedRect(), editMode: "connected_graph", editGeneration: 1, source: "new" });
  ed.commit(RS.setFacetPitch(ed.document, "f1", 9));
  assert.strictEqual(RS.fById(ed.document, "f1").pitch_rise, 9);
  assert.ok(ed.canUndo());
  ed.undo();
  assert.strictEqual(RS.fById(ed.document, "f1").pitch_rise, 6); ok("undo restores previous committed document");
  assert.ok(ed.canRedo());
  ed.redo();
  assert.strictEqual(RS.fById(ed.document, "f1").pitch_rise, 9); ok("redo re-applies");
}

// ---- one gesture = one commit; preview never commits ----
{
  const { order, persist } = makeStore();
  const ed = editor("sX", { document: connectedRect(), editMode: "connected_graph", editGeneration: 1, source: "new" });
  ed._noop; // placeholder
  const ed2 = editor("sX2", null, persist);
  const start = ed2.document;
  ed2.preview(RS.addVertex(start, 1, 1).doc);
  ed2.preview(RS.addVertex(start, 2, 2).doc); // multiple previews
  ed2.commitFrom(start, RS.addVertex(start, 3, 3).doc); // single commit at pointer-up
  await ed2.flush();
  assert.strictEqual(order.filter((o) => o.key === "rev1:sX2").length, 1, "exactly one persist for the gesture"); ok("one gesture (many previews) = exactly one commit + one persist");
}

// ---- static no-duplication check on the Field files ----
{
  const FILES = ["../roofSketchFieldController.js", "../screens/RoofSketch.js", "../components/RoofSketchCanvas.js", "../components/SketchInspector.js"];
  const FORBIDDEN = [
    /function\s+splitEdgeSafe\b/, /function\s+mergeVertices\b/, /function\s+insertExistingVertexIntoEdge\b/,
    /function\s+joinEdges\b/, /function\s+snapTarget\b/, /function\s+edgeDimension\b/,
    /function\s+makeHistory\b/, /function\s+historyPush\b/, /\bfunction\s+clone\b/, /\bfunction\s+pairKey\b/,
  ];
  const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^[ \t]*\/\/.*$/gm, "");
  for (const rel of FILES) {
    const raw = fs.readFileSync(path.resolve(__dirname, rel), "utf8");
    assert.ok(/@roofspan\/roof-sketch-core/.test(raw), rel + " must import the shared engine");
    const code = strip(raw);
    for (const re of FORBIDDEN) assert.ok(!re.test(code), rel + " must NOT redefine shared algorithm: " + re);
  }
  ok("Field editor files consume the shared engine and define no local geometry/topology/history algorithm");
}

console.log("\nFIELD ROOF SKETCH EDITOR: all " + n + " assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
