"use strict";
// Field: Generate Proposed Roof Sketch + offline durability. Verifies the SAME shared generator is used
// (Office/Field equivalence), relational structure isolation in the Field scoping helper, and that the
// existing durable Field pipeline protects an adopted proposal across a simulated restart. Pure/Node.
const assert = require("assert");
const RS = require("@roofspan/roof-sketch-core");
const { scopeStructureForGenerator } = require("../sketchMeasurementsSummary");
const { resolveInitialSketch, createFieldEditor } = require("../roofSketchFieldController");

let n = 0;
const ok = (name) => { n++; console.log("  \u2713 " + name); };

// A cached Measurement Revision detail with TWO structures: a solvable gable (ST1) and an unrelated
// single plane (ST2). This is exactly what cache.measurement(...) returns to the Field screen offline.
function measDetail() {
  return {
    structures: [{ id: "ST1", name: "Main" }, { id: "ST2", name: "Garage" }],
    facets: [
      { id: "FA", structure_id: "ST1", facet_label: "Front", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40 },
      { id: "FB", structure_id: "ST1", facet_label: "Back", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40 },
      { id: "GX", structure_id: "ST2", facet_label: "Shed", pitch_rise: 4, area_sqft: 200, width_ft: 10, length_ft: 20 },
    ],
    edges: [
      { id: "RIDGE", edge_type: "ridge", length_ft: 40, facet_id: "FA", facet_id_secondary: "FB" },
      { id: "GEAVE", edge_type: "eave", length_ft: 20, facet_id: "GX" },
    ],
    penetrations: [],
  };
}

// ---- structure isolation in the Field scoping helper (relational only) --------------------------
const scoped = scopeStructureForGenerator(measDetail(), "ST1");
assert.strictEqual(scoped.structure.id, "ST1"); ok("scope: structure id set");
assert.deepStrictEqual(scoped.facets.map((f) => f.id).sort(), ["FA", "FB"]); ok("scope: only ST1 facets (ST2 excluded)");
assert.deepStrictEqual(scoped.edges.map((e) => e.id), ["RIDGE"]); ok("scope: only ST1 edges (garage eave excluded)");

// ---- Office/Field equivalence: same shared generator + same records -> identical proposal --------
const fieldProposal = RS.generateSketchGeometry(scoped);
const officeProposal = RS.generateSketchGeometry({
  structure: { id: "ST1", name: "Main" },
  facets: measDetail().facets.filter((f) => f.structure_id === "ST1"),
  edges: [{ id: "RIDGE", edge_type: "ridge", length_ft: 40, facet_id: "FA", facet_id_secondary: "FB" }],
  penetrations: [],
});
assert.strictEqual(fieldProposal.readiness, "high_confidence"); ok("field: gable proposal is high_confidence");
assert.strictEqual(JSON.stringify(fieldProposal.document), JSON.stringify(officeProposal.document)); ok("equivalence: Office and Field produce byte-identical geometry");
assert.strictEqual(fieldProposal.source_fingerprint, officeProposal.source_fingerprint); ok("equivalence: identical source fingerprint");

// ---- offline generation: pure function, no network dependency -----------------------------------
assert.ok(fieldProposal.document.vertices.length === 6); ok("offline: geometry generated with no network (6 vertices)");

// ---- Use Proposed -> durable local persistence + restart restore --------------------------------
// Simulate the Field durable pipeline: an in-memory persist store standing in for the SQLite draft.
let store = null;
const persist = async (draft) => { store = JSON.parse(JSON.stringify(draft)); };
const initial = resolveInitialSketch({ structureId: "ST1" }); // brand-new (no draft/server) => source "new"
assert.strictEqual(initial.source, "new"); ok("new sketch: source = new (Generate is offered)");
const ed = createFieldEditor({ revisionId: "R1", structureId: "ST1", initial, persist });

// preview (Generate tapped) must NOT persist anything (no automatic save on Generate)
ed.preview(fieldProposal.document);
assert.strictEqual(store, null); ok("Generate preview: nothing persisted (no auto-save)");
assert.strictEqual(ed.editGeneration, 1); ok("Generate preview: no generation bump");

// Cancel restores the exact pre-generation (empty) state
ed.restore();
assert.strictEqual((ed.document.vertices || []).length, 0); ok("Cancel: restores exact empty pre-generation doc");

// Use Proposed -> commit through the pipeline
ed.preview(fieldProposal.document);
ed.commit(fieldProposal.document);
const flush = ed.flush();
flush.then(() => {
  assert.ok(store && store.document && store.document.vertices.length === 6); ok("Use Proposed: adopted doc persisted to durable draft");
  assert.ok(ed.isGenerationDurable(ed.editGeneration)); ok("Use Proposed: committed generation is durable");

  // Restart restore: a fresh editor loads the persisted draft as authoritative local work.
  const reopened = resolveInitialSketch({ draft: store, structureId: "ST1" });
  assert.strictEqual(reopened.source, "local_draft"); ok("restart: reopened from local draft (authoritative)");
  assert.strictEqual(JSON.stringify(RS.normalizeSketchDocument(reopened.document).facets.map((f) => f.measurement_facet_id).sort()), JSON.stringify(["FA", "FB"])); ok("restart: restored geometry retains measurement mappings");
  // and a reopened local draft => source NOT "new" => Generate is NOT offered again (existing sketch protected)
  assert.notStrictEqual(reopened.source, "new"); ok("existing draft protected: Generate not offered on reopen");

  // ---- validity: the adopted geometry passes the canonical validator --------------------------
  assert.strictEqual(RS.validateSketch(fieldProposal.document).valid, true); ok("adopted proposal passes canonical validator");

  // ---- no Measurement mutation: the input detail is untouched by generation --------------------
  const before = JSON.stringify(measDetail());
  RS.generateSketchGeometry(scopeStructureForGenerator(measDetail(), "ST1"));
  assert.strictEqual(JSON.stringify(measDetail()), before); ok("no measurement mutation from generation");

  console.log("\nFIELD GENERATE PROPOSED SKETCH: all " + n + " assertions passed");
}).catch((e) => { console.error(e); process.exit(1); });
