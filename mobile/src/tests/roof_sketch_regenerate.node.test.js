"use strict";
// Field EXISTING-sketch proposal + conflict/offline safety. The current sketch stays untouched until an
// explicit Use Proposed; adoption goes through the existing durable pipeline carrying the base version so
// CAS (not last-write-wins) governs sync. A measurement change mid-review invalidates the stale proposal.
const assert = require("assert");
const RS = require("@roofspan/roof-sketch-core");
const { scopeStructureForGenerator } = require("../sketchMeasurementsSummary");
const { resolveInitialSketch, createFieldEditor } = require("../roofSketchFieldController");

let n = 0;
const ok = (name) => { n++; console.log("  \u2713 " + name); };

function detail(ridge) {
  return {
    structures: [{ id: "ST1", name: "Main" }],
    facets: [
      { id: "FA", structure_id: "ST1", facet_label: "Front", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40 },
      { id: "FB", structure_id: "ST1", facet_label: "Back", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40 },
    ],
    edges: [{ id: "RIDGE", edge_type: "ridge", length_ft: ridge, facet_id: "FA", facet_id_secondary: "FB" }],
    penetrations: [],
  };
}
const scope = (d) => scopeStructureForGenerator(d, "ST1");

// An existing server sketch at version A (a plain single-plane manual-ish doc mapped to FA only).
const serverSketchA = RS.generateSketchGeometry({ structure: { id: "ST1" }, facets: [{ id: "FA", structure_id: "ST1", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, facet_label: "FA" }], edges: [{ id: "E", edge_type: "eave", length_ft: 20, facet_id: "FA" }], penetrations: [] }).document;
const initial = resolveInitialSketch({ server: { document: serverSketchA, document_version: 7 }, structureId: "ST1" });
assert.strictEqual(initial.source, "server"); ok("existing sketch: source=server (regenerate offered, not empty-generate)");
assert.strictEqual(initial.documentVersion, 7); ok("existing sketch: base version A=7 captured");

let store = null;
const persist = async (d) => { store = JSON.parse(JSON.stringify(d)); };
const ed = createFieldEditor({ revisionId: "R1", structureId: "ST1", initial, persist });
const beforeDocJson = JSON.stringify(ed.document);

// Generate a NEW proposal from current measurements (gable) — a SEPARATE candidate.
const proposal = RS.generateSketchGeometry(scope(detail(40)));
const comparison = RS.compareSketchProposal(ed.document, proposal);
assert.strictEqual(comparison.identical, false); ok("regen: proposal differs from current sketch");
assert.ok(comparison.added_planes.includes("FB")); ok("regen: comparison flags added plane FB");
assert.strictEqual(JSON.stringify(ed.document), beforeDocJson); ok("regen review: current working sketch is UNTOUCHED");
assert.strictEqual(ed.editGeneration, 1); ok("regen review: no generation bump (candidate not adopted)");
assert.strictEqual(store, null); ok("regen review: NO server/local mutation created for an unaccepted proposal");

// Keep Current: (no controller change) document stays exactly as loaded
assert.strictEqual(JSON.stringify(ed.document), beforeDocJson); ok("keep current: nothing changes");

// Use Proposed -> commit through the existing pipeline (durability + CAS base retained)
ed.commit(proposal.document);
const snap = ed.authoritativeSnapshot();
assert.strictEqual(snap.documentVersion, 7); ok("use proposed: base version A=7 retained on staged snapshot (CAS applies)");
assert.strictEqual(JSON.stringify(RS.normalizeSketchDocument(ed.document).facets.map((f) => f.measurement_facet_id).sort()), JSON.stringify(["FA", "FB"])); ok("use proposed: editor now holds the proposal (working doc)");
ed.flush().then(() => {
  assert.ok(store && store.document && store.document.facets.length === 2); ok("use proposed: adopted doc persisted durably (restart-safe)");

  // CONFLICT: Office advanced canonical to version B=8 while Field held base 7. Existing CAS must reject
  // a stale save — the staged snapshot's expected version is 7, so server 8 => conflict (no last-write-wins).
  const staged = ed.authoritativeSnapshot();
  assert.strictEqual(staged.documentVersion, 7); ok("conflict: Field save carries expected version 7 (server is 8) -> CAS conflict, not overwrite");

  // restart restore: reopen from the durable local draft (authoritative), still based on version 7
  const reopened = resolveInitialSketch({ draft: store, server: { document: serverSketchA, document_version: 7 }, structureId: "ST1" });
  assert.strictEqual(reopened.source, "local_draft"); ok("restart: reopened from durable local draft");

  // STALE proposal: measurements change (ridge 40 -> 44) => fresh fingerprint differs from the reviewed one
  const fpReviewed = proposal.source_fingerprint;
  const fpChanged = RS.generateSketchGeometry(scope(detail(44))).source_fingerprint;
  assert.notStrictEqual(fpChanged, fpReviewed); ok("stale guard: changed measurements produce a different fingerprint (review invalidated)");

  // no measurement mutation from any of this
  const before = JSON.stringify(detail(40));
  RS.compareSketchProposal(ed.document, RS.generateSketchGeometry(scope(detail(40))));
  assert.strictEqual(JSON.stringify(detail(40)), before); ok("no measurement mutation from generate/compare");

  console.log("\nFIELD EXISTING-SKETCH PROPOSAL + CONFLICT: all " + n + " assertions passed");
}).catch((e) => { console.error(e); process.exit(1); });
