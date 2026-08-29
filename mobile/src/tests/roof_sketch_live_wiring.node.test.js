"use strict";
// B2A live-wiring / data-integrity contracts (Node). Exercises the SAME pure adapters the RoofSketch
// screen + canvas call in production (roofSketchFieldWiring) plus controller persistence truthfulness.
const assert = require("assert");
const RS = require("@roofspan/roof-sketch-core");
const WIRE = require("../roofSketchFieldWiring");
const { createFieldEditor } = require("../roofSketchFieldController");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };
function rect() {
  const d = RS.createSketchDocument({ structureId: "sX" });
  d.vertices = [{ id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }, { id: "v3", x: 10, y: 8 }, { id: "v4", x: 0, y: 8 }];
  d.edges = [
    { id: "e1", v1: "v1", v2: "v2", type: "eave" }, { id: "e2", v1: "v2", v2: "v3", type: "rake" },
    { id: "e3", v1: "v3", v2: "v4", type: "eave" }, { id: "e4", v1: "v4", v2: "v1", type: "rake" },
  ];
  d.facets = [{ id: "f1", label: "F1", edgeIds: ["e1", "e2", "e3", "e4"], vertexIds: [], pitch_rise: 6 }];
  return d;
}

(async () => {
  // ---- §1 load integration: cache envelope ----
  {
    const fresh = WIRE.resolveFieldSketchLoad({ draft: null, sketchResult: { data: { document: { edit_mode: "connected_graph", vertices: [{ id: "v1", x: 1, y: 1 }] }, document_version: 9, edit_mode: "connected_graph" }, stale: false }, structureId: "sX" });
    assert.strictEqual(fresh.initial.source, "server");
    assert.strictEqual(fresh.initial.documentVersion, 9);
    assert.strictEqual(fresh.initial.document.vertices.length, 1);
    assert.strictEqual(fresh.statusMeta.stale, false); ok("cache envelope.data is used as the server sketch + document_version retained");

    const stale = WIRE.resolveFieldSketchLoad({ draft: null, sketchResult: { data: { document: { vertices: [{ id: "v9", x: 2, y: 2 }] }, document_version: 3 }, stale: true, cachedAt: "t0" }, structureId: "sX" });
    assert.strictEqual(stale.initial.source, "server");
    assert.strictEqual(stale.statusMeta.stale, true); ok("stale cached envelope opens as the server sketch");

    const draftWins = WIRE.resolveFieldSketchLoad({ draft: { document: { vertices: [{ id: "vD", x: 5, y: 5 }] }, edit_generation: 4 }, sketchResult: { data: { vertices: [{ id: "v1", x: 1, y: 1 }] }, stale: false }, structureId: "sX" });
    assert.strictEqual(draftWins.initial.source, "local_draft");
    assert.strictEqual(draftWins.initial.document.vertices[0].id, "vD"); ok("local draft still wins over a present cache envelope");

    const none = WIRE.resolveFieldSketchLoad({ draft: null, sketchResult: { data: null, stale: true, error: new Error("offline") }, structureId: "sX" });
    assert.strictEqual(none.initial.source, "new"); ok("empty cache envelope (offline, no cache) falls back to a new sketch");
  }

  // ---- §2 identity mapping ----
  {
    const store = {};
    const args = WIRE.makeFieldEditorArgs({ revision_id: "REV9", structure_id: "STR7", initial: WIRE.resolveFieldSketchLoad({ structureId: "STR7" }).initial, persist: async (d) => { store.last = d; } });
    assert.strictEqual(args.revisionId, "REV9");
    assert.strictEqual(args.structureId, "STR7"); ok("makeFieldEditorArgs maps revision_id->revisionId, structure_id->structureId");
    const ed = createFieldEditor(args);
    ed.commit(RS.addVertex(ed.document, 1, 1).doc);
    await ed.flush();
    assert.strictEqual(store.last.revision_id, "REV9");
    assert.strictEqual(store.last.structure_id, "STR7"); ok("persisted draft carries the correct revision_id + structure_id (no undefined identity)");
  }

  // ---- §3 facet label preserves the whole sketch (through the current-doc commit adapter) ----
  {
    const ed = createFieldEditor({ revisionId: "r", structureId: "s", initial: { document: rect(), editMode: "connected_graph", editGeneration: 1, source: "new" }, persist: async () => {} });
    const before = ed.document;
    // same style the inspector uses: onCommit((d) => RS.setFacetLabel(d, facetId, label))
    const next = ((d) => RS.setFacetLabel(d, "f1", "North Main"))(ed.document);
    ed.commit(next);
    assert.strictEqual(ed.document.vertices.length, 4, "vertices preserved");
    assert.strictEqual(ed.document.edges.length, 4, "edges preserved");
    assert.strictEqual(ed.document.facets.length, 1, "single facet preserved");
    assert.strictEqual(ed.document.facets[0].id, "f1", "same facet id");
    assert.strictEqual(ed.document.facets[0].label, "North Main", "label changed");
    assert.notStrictEqual(ed.document, before); ok("facet label edit preserves the entire sketch (no empty-document data loss)");
  }

  // ---- §4/§6 manual + connected facet build (valid commit, invalid reject) ----
  {
    let m = RS.setEditMode(RS.createSketchDocument({ structureId: "s" }), "manual_polygon");
    const a = RS.addVertex(m, 0, 0), b = RS.addVertex(a.doc, 10, 0), c = RS.addVertex(b.doc, 5, 8);
    const ids = [a.vertexId, b.vertexId, c.vertexId];
    const good = WIRE.commitManualCreate(c.doc, ids);
    assert.ok(good.ok && good.facetId); ok("commitManualCreate finalizes a valid polygon");
    const tooFew = WIRE.commitManualCreate(c.doc, ids.slice(0, 2));
    assert.ok(!tooFew.ok && tooFew.reason === "polygon_needs_three_points"); ok("manual polygon with <3 points rejected");

    const graph = rect(); graph.facets = []; // graph edges present, no facet yet
    const okFacet = WIRE.commitFacetCreate(graph, ["e1", "e2", "e3", "e4"]);
    assert.ok(okFacet.ok && okFacet.facetId); ok("commitFacetCreate finalizes a valid closed loop");
    const openLoop = WIRE.commitFacetCreate(graph, ["e1", "e2", "e3"]); // open boundary
    assert.ok(!openLoop.ok && openLoop.doc.facets.length === 0); ok("invalid (open-loop) connected facet rejected, original document preserved");
  }

  // ---- §7 synchronous release candidate ----
  {
    const gVertex = { snapCandidate: { type: "vertex", vertexId: "v1" } };
    assert.strictEqual(WIRE.pickReleaseCandidate(gVertex, { type: "free", point: [9, 9] }).type, "vertex"); ok("pickReleaseCandidate returns the synchronous vertex candidate (not a fallback free move)");
    const withFree = rect(); withFree.vertices.push({ id: "v5", x: 5, y: 3 });
    const insert = RS.applyVertexDrop(withFree, "v5", { type: "edge", edgeId: "e1", point: [5, 3] });
    assert.ok(insert.ok && !RS.eById(insert.doc, "e1")); ok("edge release candidate drives an insert (split)");
    const merge = RS.applyVertexDrop(rect(), "v4", WIRE.pickReleaseCandidate({ snapCandidate: { type: "vertex", vertexId: "v1" } }));
    assert.ok(merge.ok && !RS.vById(merge.doc, "v4")); ok("vertex release candidate drives a merge");
  }

  // ---- §8 tap vs drag threshold (screen points) ----
  {
    assert.strictEqual(WIRE.movedBeyondThreshold([100, 100], [103, 101]), false); ok("small movement stays a tap (no drag)");
    assert.strictEqual(WIRE.movedBeyondThreshold([100, 100], [140, 100]), true); ok("large movement becomes a drag");
  }

  // ---- §10 two-finger pan + pinch ----
  {
    const view = { scale: 1, tx: 0, ty: 0 };
    const doc = rect(); const snap = JSON.stringify(doc);
    const panned = WIRE.applyTwoTouchView(view, { mid: [100, 100], dist: 50 }, { mid: [120, 100], dist: 50 });
    assert.ok(Math.abs(panned.tx - 20) < 1e-6 && panned.scale === 1); ok("constant-separation two-finger move pans (+20px) with unchanged scale");
    const both = WIRE.applyTwoTouchView(view, { mid: [100, 100], dist: 50 }, { mid: [110, 100], dist: 100 });
    assert.ok(both.scale === 2 && both.tx !== 0); ok("changing separation + moving midpoint applies BOTH zoom and pan");
    assert.strictEqual(JSON.stringify(doc), snap); ok("two-touch view math leaves the sketch document unchanged");
  }

  // ---- §12 join type-conflict UI contract ----
  {
    // split e1 into two edges of different classified types then join
    const base = rect();
    base.vertices.push({ id: "vm", x: 5, y: 0 });
    base.edges = base.edges.filter((e) => e.id !== "e1").concat([
      { id: "e1a", v1: "v1", v2: "vm", type: "eave" }, { id: "e1b", v1: "vm", v2: "v2", type: "rake" },
    ]);
    base.facets = [{ id: "f1", edgeIds: ["e1a", "e1b", "e2", "e3", "e4"], vertexIds: [] }];
    const conflict = WIRE.attemptJoin(base, "e1a", "e1b");
    assert.ok(!conflict.ok && conflict.needsType); ok("classified type conflict does not silently fail — needsType flagged");
    const resolved = WIRE.attemptJoin(base, "e1a", "e1b", "hip");
    assert.ok(resolved.ok && RS.eById(resolved.doc, resolved.edgeId).type === "hip"); ok("explicit result type resolves the join");
    // compatible inherit
    base.edges = base.edges.map((e) => e.id === "e1b" ? { ...e, type: "eave" } : e);
    const compat = WIRE.attemptJoin(base, "e1a", "e1b");
    assert.ok(compat.ok); ok("compatible types join immediately");
    // failure surfaces a reason (protected source)
    const prot = RS.lockEdge(base, "e1a");
    const fail = WIRE.attemptJoin(prot, "e1a", "e1b");
    assert.ok(!fail.ok && !fail.needsType && fail.reason === "edge_protected"); ok("protected join failure surfaces a reason (not silent)");
  }

  // ---- §13/§14/§15 truthful local durability ----
  {
    let mode = "fail";
    const persist = async () => { if (mode === "fail") throw new Error("disk full"); };
    const ed = createFieldEditor({ revisionId: "r", structureId: "s", initial: { document: rect(), editMode: "connected_graph", editGeneration: 1, source: "new" }, persist });
    const workingBefore = ed.document;
    ed.commit(RS.setFacetPitch(ed.document, "f1", 8));
    let res = await ed.flush();
    assert.strictEqual(res.ok, false, "flush reports failure"); ok("failed durable write does NOT report 'saved' (flush ok=false)");
    assert.strictEqual(ed.document.facets[0].pitch_rise, 8, "in-memory doc retained"); ok("persistence failure retains the in-memory document");
    assert.ok(ed.persistError, "persistError recorded"); ok("persistence failure is recorded, not swallowed");
    mode = "ok";
    res = await ed.retry();
    assert.strictEqual(res.ok, true, "retry succeeds"); ok("retry succeeds once storage recovers");
    // later generation still persists after recovery
    ed.commit(RS.setFacetPitch(ed.document, "f1", 9));
    res = await ed.flush();
    assert.strictEqual(res.ok, true); ok("serialized later generations continue to persist after recovery");
  }

  console.log("\nFIELD LIVE WIRING: all " + n + " assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
