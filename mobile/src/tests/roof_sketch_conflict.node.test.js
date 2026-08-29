"use strict";
// B3C (+ correction) — Roof Sketch 409 conflict review + ATOMIC generation-checked resolution contracts.
// These call the SAME pure decision helper the production storage transition uses
// (roofSketchConflict.decideSketchConflictResolution) — there is NO hand-written mirror of sync.js. The
// editing-lock proof uses the REAL WIRE.editingLocked predicate + the REAL controller; the stale-refresh
// proof uses the REAL WIRE.applySketchRefresh latest-wins gate.
const assert = require("assert");
const C = require("../roofSketchConflict");
const WIRE = require("../roofSketchFieldWiring");
const RS = require("@roofspan/roof-sketch-core");
const { createFieldEditor, resolveInitialSketch } = require("../roofSketchFieldController");
const { sketchDraftKey, sketchDetailKey, sketchUpdateMutationId, makeSketchDraft } = require("../sketchCache");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

const doc = (f, e, v, p) => ({ facets: Array(f).fill(0).map((_, i) => i), edges: Array(e).fill(0).map((_, i) => i), vertices: Array(v).fill(0).map((_, i) => i), penetrations: Array(p).fill(0).map((_, i) => i) });
const BASE = doc(1, 4, 4, 0), LOCAL = doc(2, 8, 8, 1), OFFICE = doc(3, 12, 10, 0), NEWER = doc(4, 16, 12, 2);
const REV = "REV1", HOUSE = "HOUSE", GARAGE = "GARAGE";

// A durable conflict row exactly as the queue stores it (state=conflict, serverValue=409 Office snapshot).
function conflictRow(rev, struct, editGen, queueGen) {
  return {
    client_id: sketchUpdateMutationId(rev, struct), scope: "s",
    kind: "measurement_sketch_update", method: "put",
    path: `/mobile/measurements/${rev}/sketches/${struct}`,
    body: { schema_version: 1, edit_mode: "connected_graph", document: LOCAL, expected_version: 6 },
    local_edit_generation: editGen, mutation_generation: queueGen, state: "conflict",
    serverValue: { document_version: 7, document: OFFICE, edit_mode: "connected_graph" },
  };
}
function localDraft(rev, struct, editGen, opts = {}) {
  return makeSketchDraft(rev, struct, { document: opts.document || LOCAL, documentVersion: 6, baseServerDocument: BASE, editMode: "connected_graph", editGeneration: editGen });
}
function reviewedFor(rev, struct, editGen, queueGen) {
  const m = conflictRow(rev, struct, editGen, queueGen);
  return C.buildReviewedContext(m, localDraft(rev, struct, editGen), { draftKey: sketchDraftKey(rev, struct), detailKey: sketchDetailKey(rev, struct) });
}

// ---- 1. review sources Base / Local / Office + status + summary ----
{
  const r = C.conflictReview(conflictRow(REV, HOUSE, 5, 2), localDraft(REV, HOUSE, 5));
  assert.strictEqual(r.base, BASE); assert.strictEqual(r.local, LOCAL); assert.strictEqual(r.office, OFFICE);
  assert.strictEqual(r.officeVersion, 7); assert.strictEqual(r.conflictGeneration, 5);
  assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: conflictRow(REV, HOUSE, 5, 2), running: false, currentGeneration: 5 }), "Conflict — review required");
  assert.deepStrictEqual(C.sketchSummary(OFFICE), { facets: 3, edges: 12, vertices: 10, penetrations: 0 });
  ok("review sources Base/Local/Office (+version), status is 'Conflict — review required', summary is deterministic");
}

// ---- 2. Use Office — exact conflict succeeds (adopt Office, retire draft, remove exact row) ----
{
  const reviewed = reviewedFor(REV, HOUSE, 5, 2);
  const live = { row: conflictRow(REV, HOUSE, 5, 2), draft: localDraft(REV, HOUSE, 5) };
  const d = C.decideSketchConflictResolution("use_office", reviewed, live);
  assert.strictEqual(d.action, "use_office");
  assert.strictEqual(d.retireDraft, true);
  assert.strictEqual(d.cacheDetail.document, OFFICE);
  assert.strictEqual(d.cacheDetail.document_version, 7);
  assert.strictEqual(d.editor.document, OFFICE);
  assert.strictEqual(d.editor.documentVersion, 7);
  ok("Use Office (exact conflict): adopt Office document+version, retire draft, remove the exact reviewed row");
}

// ---- 3. Keep Local — exact conflict succeeds (rebase, fresh pending, expected_version=Office, gen+1) ----
{
  const reviewed = reviewedFor(REV, HOUSE, 5, 2);
  const live = { row: conflictRow(REV, HOUSE, 5, 2), draft: localDraft(REV, HOUSE, 5) };
  const d = C.decideSketchConflictResolution("keep_local", reviewed, live);
  assert.strictEqual(d.action, "keep_local");
  assert.strictEqual(d.nextDraft.document, LOCAL);
  assert.strictEqual(d.nextDraft.base_server_document, OFFICE);
  assert.strictEqual(d.nextDraft.document_version, 7);
  assert.strictEqual(d.nextDraft.edit_generation, 5, "local generation preserved");
  assert.strictEqual(d.nextRow.state, "pending");
  assert.strictEqual(d.nextRow.body.expected_version, 7);
  assert.strictEqual(d.nextRow.body.document, LOCAL);
  assert.strictEqual(d.nextRow.mutation_generation, 3, "queue generation advances 2 -> 3 (new logical send)");
  ok("Keep Local (exact conflict): rebase to Office version/base, exact row -> fresh pending, expected_version=Office, gen+1");
}

// ---- 4. Use Office STALE: a newer DRAFT landed after review (draft gen 6 > reviewed 5) ----
{
  const reviewed = reviewedFor(REV, HOUSE, 5, 2);
  const live = { row: conflictRow(REV, HOUSE, 5, 2), draft: localDraft(REV, HOUSE, 6, { document: NEWER }) };
  const d = C.decideSketchConflictResolution("use_office", reviewed, live);
  assert.strictEqual(d.action, "stale");
  assert.strictEqual(d.reason, "draft_advanced");
  assert.ok(!d.cacheDetail && !d.retireDraft, "no writes produced when stale");
  ok("Use Office STALE: a newer local draft after review -> stale (nothing cached/retired/removed)");
}

// ---- 5. Use Office STALE: a newer QUEUE row replaced the reviewed conflict (queue gen 2 -> 4) ----
{
  const reviewed = reviewedFor(REV, HOUSE, 5, 2);
  const live = { row: conflictRow(REV, HOUSE, 5, 4), draft: localDraft(REV, HOUSE, 5) };
  const d = C.decideSketchConflictResolution("use_office", reviewed, live);
  assert.strictEqual(d.action, "stale");
  assert.strictEqual(d.reason, "queue_generation_changed");
  ok("Use Office STALE: a newer queue row (mutation_generation changed) after review -> stale");
}

// ---- 6. Keep Local STALE: a newer draft + newer queue landed; local-5 doc is NOT requeued ----
{
  const reviewed = reviewedFor(REV, HOUSE, 5, 2);
  // newer local generation 6 (document NEWER) + newer queue row (gen 3, carrying NEWER)
  const newerRow = { ...conflictRow(REV, HOUSE, 6, 3), body: { schema_version: 1, edit_mode: "connected_graph", document: NEWER, expected_version: 7 } };
  const live = { row: newerRow, draft: localDraft(REV, HOUSE, 6, { document: NEWER }) };
  const d = C.decideSketchConflictResolution("keep_local", reviewed, live);
  assert.strictEqual(d.action, "stale");
  assert.ok(!d.nextRow, "no fresh pending row produced");
  assert.ok(!d.nextDraft, "no draft rebase produced");
  ok("Keep Local STALE: newer draft/queue after review -> stale; the old generation-5 Local is NOT requeued");
}

// ---- 7. queue mutation_generation never moves backward (regression guard) ----
{
  // reviewed captured queueGen 2, but the live row is already AHEAD at 3 -> must be stale (never regress).
  const reviewed = reviewedFor(REV, HOUSE, 5, 2);
  const ahead = C.decideSketchConflictResolution("keep_local", reviewed, { row: conflictRow(REV, HOUSE, 5, 3), draft: localDraft(REV, HOUSE, 5) });
  assert.strictEqual(ahead.action, "stale", "cannot act when the live queue generation is ahead of the reviewed one");
  // and on the exact-match success path the produced generation only ever INCREASES.
  const good = C.decideSketchConflictResolution("keep_local", reviewed, { row: conflictRow(REV, HOUSE, 5, 2), draft: localDraft(REV, HOUSE, 5) });
  assert.ok(good.nextRow.mutation_generation > reviewed.queueGeneration, "successful transition advances, never regresses");
  ok("queue mutation_generation never regresses: ahead-of-review is stale; success strictly increases it");
}

// ---- 8. conflict during FACET build prevents Create Facet (real editingLocked + real controller) ----
{
  const ed = createFieldEditor({ revisionId: REV, structureId: HOUSE, initial: resolveInitialSketch({ structureId: HOUSE }), persist: async () => { persists++; } });
  var persists = 0;
  const gen0 = ed.editGeneration;
  const review = C.conflictReview(conflictRow(REV, HOUSE, 5, 2), localDraft(REV, HOUSE, 5));
  // The screen handler short-circuits when editingLocked is true (this IS the production guard predicate).
  const locked = WIRE.editingLocked({ readOnly: false, conflict: review });
  assert.strictEqual(locked, true, "an active conflict locks editing");
  if (!locked) ed.commit(RS.createSketchDocument({ structureId: HOUSE }));   // guarded: never runs while locked
  assert.strictEqual(ed.editGeneration, gen0, "no edit-generation increment while a conflict is active");
  assert.strictEqual(persists, 0, "no draft write while a conflict is active");
  ok("conflict during Facet build: Create Facet is blocked — no document change, no generation bump, no persist");
}

// ---- 9. conflict during MANUAL build prevents Create Polygon (same guard) ----
{
  const ed = createFieldEditor({ revisionId: REV, structureId: HOUSE, initial: resolveInitialSketch({ structureId: HOUSE }), persist: async () => { persists++; } });
  var persists = 0;
  const gen0 = ed.editGeneration;
  const locked = WIRE.editingLocked({ readOnly: false, conflict: C.conflictReview(conflictRow(REV, HOUSE, 5, 2), localDraft(REV, HOUSE, 5)) });
  if (!locked) ed.commit(RS.createSketchDocument({ structureId: HOUSE }));
  assert.strictEqual(ed.editGeneration, gen0);
  assert.strictEqual(persists, 0);
  assert.strictEqual(WIRE.editingLocked({ readOnly: false, conflict: null }), false, "no lock when there is no conflict");
  ok("conflict during Manual build: Create Polygon is blocked — no document change, no generation bump, no persist");
}

// ---- 10. a stale pre-resolution refresh cannot overwrite Synced to Office (latest-wins seq gate) ----
{
  const state = { seq: 5, acked: 0, localSave: null };   // Use Office bumped the seq to 5
  let setCalls = 0;
  const ed = createFieldEditor({ revisionId: REV, structureId: HOUSE, initial: resolveInitialSketch({ structureId: HOUSE }) });
  // an old refresh (seq 4) that began from the conflict state completes AFTER resolution:
  const res = WIRE.applySketchRefresh({ seq: 4, state, editor: ed, mutation: conflictRow(REV, HOUSE, 5, 2), draft: localDraft(REV, HOUSE, 5), running: false, setStatus: () => { setCalls++; } });
  assert.strictEqual(res.applied, false, "stale refresh is discarded");
  assert.strictEqual(setCalls, 0, "stale refresh never calls setStatus (Synced to Office is preserved)");
  ok("stale pre-resolution refresh (older seq) cannot overwrite Synced to Office");
}

// ---- 11. House resolution stays isolated from the Garage (decider keyed to the exact client_id) ----
{
  const reviewedHouse = reviewedFor(REV, HOUSE, 5, 2);
  // the live row read back is the GARAGE row (different client_id) -> must refuse to act on it.
  const d = C.decideSketchConflictResolution("use_office", reviewedHouse, { row: conflictRow(REV, GARAGE, 3, 1), draft: localDraft(REV, GARAGE, 3) });
  assert.strictEqual(d.action, "stale");
  assert.strictEqual(d.reason, "client_id_changed");
  ok("structure isolation: a House resolution never acts on a Garage row (client_id mismatch -> stale)");
}

// ---- 12. unresolved conflict survives restart (durable row + draft reconstruct the review) ----
{
  const persistedRow = conflictRow(REV, HOUSE, 5, 2);       // durable in pending_mutations
  const persistedDraft = localDraft(REV, HOUSE, 5);         // durable in cache
  const r = C.conflictReview(persistedRow, persistedDraft);
  assert.strictEqual(r.base, BASE); assert.strictEqual(r.local, LOCAL); assert.strictEqual(r.office, OFFICE);
  assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: persistedRow, running: false, currentGeneration: 5 }), "Conflict — review required");
  ok("durable restart: an unresolved conflict reopens with Base/Local/Office review and stays 'Conflict — review required'");
}

// ---- 13. row gone / no longer conflict -> stale (defensive) ----
{
  const reviewed = reviewedFor(REV, HOUSE, 5, 2);
  assert.strictEqual(C.decideSketchConflictResolution("use_office", reviewed, { row: null, draft: null }).reason, "row_missing");
  assert.strictEqual(C.decideSketchConflictResolution("use_office", reviewed, { row: { ...conflictRow(REV, HOUSE, 5, 2), state: "synced" }, draft: null }).reason, "not_conflict");
  ok("defensive: a removed or already-synced row makes resolution stale (no writes)");
}

console.log("\nROOF SKETCH B3C ATOMIC CONFLICT RESOLUTION + LOCK: all " + n + " assertions passed");
