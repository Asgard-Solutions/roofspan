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

// ==== B3C FINAL CORRECTION: real all-or-nothing transaction + Undo/Redo defensive lock ====
;(async () => {
// The production storage transition wraps roofSketchConflict.applyResolutionInTx in a REAL SQLite
// transaction (expo-sqlite withTransactionAsync). Here we drive that SAME function with an in-memory
// executor + a snapshot/rollback wrapper that mimics withTransactionAsync (commit on success, restore on
// throw) and inject a mid-transition failure at a named failpoint — proving nothing partial survives.
function mkStore(rev, struct, editGen, queueGen) {
  const cid = sketchUpdateMutationId(rev, struct);
  return { rows: { [cid]: conflictRow(rev, struct, editGen, queueGen) }, cache: { [sketchDraftKey(rev, struct)]: localDraft(rev, struct, editGen) } };
}
function mkExecutor(store, overrides = {}) {
  return Object.assign({
    readConflictRow: async (cid) => store.rows[cid] || null,
    readDraft: async (key) => (key in store.cache ? store.cache[key] : null),
    writeCache: async (key, val) => { store.cache[key] = val; },
    deleteConflictRow: async (cid, qg) => {
      const r = store.rows[cid];
      if (r && r.state === "conflict" && (Number(r.mutation_generation) || 1) === qg) { delete store.rows[cid]; return 1; }
      return 0;
    },
    transitionConflictToPending: async (cid, qg, nextRow) => {
      const r = store.rows[cid];
      if (r && r.state === "conflict" && (Number(r.mutation_generation) || 1) === qg) { store.rows[cid] = nextRow; return 1; }
      return 0;
    },
  }, overrides);
}
// mimic withTransactionAsync: snapshot, run applyResolutionInTx, restore-on-throw (all-or-nothing).
async function runTx(store, choice, reviewed, { failAt, overrides } = {}) {
  const snap = JSON.parse(JSON.stringify(store));
  const failpoint = (name) => { if (name === failAt) throw new Error("injected@" + name); };
  try {
    const decision = await C.applyResolutionInTx(mkExecutor(store, overrides), choice, reviewed, failpoint);
    return { committed: true, decision };
  } catch (e) {
    store.rows = snap.rows; store.cache = snap.cache;   // ROLLBACK
    return { committed: false, reason: e.__stale || e.message };
  }
}
const CID = sketchUpdateMutationId(REV, HOUSE), DK = sketchDraftKey(REV, HOUSE), TK = sketchDetailKey(REV, HOUSE);

// ---- 14. Use Office transaction COMMITS together (exact conflict) ----
{
  const store = mkStore(REV, HOUSE, 5, 2);
  const r = await runTx(store, "use_office", reviewedFor(REV, HOUSE, 5, 2));
  assert.strictEqual(r.committed, true);
  assert.strictEqual(store.cache[TK].document, OFFICE, "Office sketch cached");
  assert.strictEqual(store.cache[DK], null, "local draft retired");
  assert.ok(!store.rows[CID], "exact conflict row deleted");
  ok("Use Office transaction commits all-or-nothing: cache + retire draft + delete row together");
}

// ---- 15. Keep Local transaction COMMITS together (exact conflict) ----
{
  const store = mkStore(REV, HOUSE, 5, 2);
  const r = await runTx(store, "keep_local", reviewedFor(REV, HOUSE, 5, 2));
  assert.strictEqual(r.committed, true);
  assert.strictEqual(store.cache[DK].base_server_document, OFFICE, "draft rebased to Office base");
  assert.strictEqual(store.rows[CID].state, "pending", "conflict row transitioned to pending");
  assert.strictEqual(store.rows[CID].mutation_generation, 3, "mutation_generation advanced 2 -> 3");
  assert.strictEqual(store.rows[CID].body.expected_version, 7);
  ok("Keep Local transaction commits all-or-nothing: draft rebase + conflict->pending together");
}

// ---- 16. Use Office INTERRUPTED after first write -> full rollback, no partial state ----
{
  const store = mkStore(REV, HOUSE, 5, 2);
  const r = await runTx(store, "use_office", reviewedFor(REV, HOUSE, 5, 2), { failAt: "use_office:after_cache" });
  assert.strictEqual(r.committed, false);
  assert.ok(!(TK in store.cache), "no Office sketch cached (rolled back)");
  assert.deepStrictEqual(store.cache[DK].document, LOCAL, "local draft still = Local B");
  assert.strictEqual(store.rows[CID].state, "conflict", "conflict row still exists");
  assert.strictEqual(store.rows[CID].mutation_generation, 2);
  ok("Use Office interrupted (after cache write): rolls back every durable change — no partial Use-Office state");
}

// ---- 17. Keep Local INTERRUPTED after draft rebase, before conflict->pending -> full rollback ----
{
  const store = mkStore(REV, HOUSE, 5, 2);
  const r = await runTx(store, "keep_local", reviewedFor(REV, HOUSE, 5, 2), { failAt: "keep_local:after_draft" });
  assert.strictEqual(r.committed, false);
  assert.deepStrictEqual(store.cache[DK].base_server_document, BASE, "draft base still original (rebase rolled back)");
  assert.strictEqual(store.cache[DK].document_version, 6, "draft version still original");
  assert.strictEqual(store.rows[CID].state, "conflict", "original conflict row still exists (no fresh pending)");
  assert.strictEqual(store.rows[CID].mutation_generation, 2, "mutation_generation did NOT advance");
  ok("Keep Local interrupted (after draft rebase): rolls back the rebase too — no partial Keep-Local state");
}

// ---- 18. Guarded DELETE/UPDATE miss cannot leave partial cache/draft writes ----
{
  // Use Office: the DELETE hits 0 rows (concurrent change between read and delete) -> abort + rollback,
  // even though cache + draft writes already ran inside the transaction.
  const store = mkStore(REV, HOUSE, 5, 2);
  const r = await runTx(store, "use_office", reviewedFor(REV, HOUSE, 5, 2), { overrides: { deleteConflictRow: async () => 0 } });
  assert.strictEqual(r.committed, false);
  assert.strictEqual(r.reason, "delete_missed");
  assert.ok(!(TK in store.cache), "cache write rolled back after the guarded DELETE missed");
  assert.deepStrictEqual(store.cache[DK].document, LOCAL, "draft retire rolled back");
  // Keep Local: the UPDATE hits 0 rows -> abort + rollback the draft rebase.
  const store2 = mkStore(REV, HOUSE, 5, 2);
  const r2 = await runTx(store2, "keep_local", reviewedFor(REV, HOUSE, 5, 2), { overrides: { transitionConflictToPending: async () => 0 } });
  assert.strictEqual(r2.committed, false);
  assert.strictEqual(r2.reason, "update_missed");
  assert.deepStrictEqual(store2.cache[DK].base_server_document, BASE, "draft rebase rolled back after the guarded UPDATE missed");
  ok("a guarded DELETE/UPDATE that misses its row rolls back all earlier writes — never a partial commit");
}

// ---- 19. restart AFTER a failed resolution still reconstructs the original conflict review ----
{
  const store = mkStore(REV, HOUSE, 5, 2);
  await runTx(store, "use_office", reviewedFor(REV, HOUSE, 5, 2), { failAt: "use_office:after_cache" });   // fails + rolls back
  const m = store.rows[CID];   // durable conflict row survived
  const rev = C.conflictReview(m, store.cache[DK]);
  assert.deepStrictEqual(rev.base, BASE); assert.deepStrictEqual(rev.local, LOCAL); assert.deepStrictEqual(rev.office, OFFICE);
  assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: m, running: false, currentGeneration: 5 }), "Conflict — review required");
  ok("restart after a failed resolution: the original conflict reopens with Base/Local/Office review");
}

// ---- 20. Undo is blocked BEFORE it mutates the controller (real editingLocked + real controller) ----
{
  let persists = 0;
  const ed = createFieldEditor({ revisionId: REV, structureId: HOUSE, initial: resolveInitialSketch({ structureId: HOUSE }), persist: async () => { persists++; } });
  ed.commit({ ...ed.document, vertices: [{ id: "v1", x: 1, y: 1 }] });   // create undo history
  const genBefore = ed.editGeneration, docBefore = JSON.stringify(ed.document), canUndoBefore = ed.canUndo(), pBefore = persists;
  const locked = WIRE.editingLocked({ readOnly: false, conflict: C.conflictReview(conflictRow(REV, HOUSE, 5, 2), localDraft(REV, HOUSE, 5)) });
  if (!locked) ed.undo();   // the screen's doUndo guard: skipped while locked
  assert.strictEqual(locked, true, "conflict locks editing");
  assert.strictEqual(ed.editGeneration, genBefore, "blocked Undo did not increment edit generation");
  assert.strictEqual(JSON.stringify(ed.document), docBefore, "blocked Undo did not change the document");
  assert.strictEqual(ed.canUndo(), canUndoBefore, "undo history not consumed");
  assert.strictEqual(persists, pBefore, "blocked Undo did not persist");
  ok("Undo blocked before controller mutation: no doc change, no generation bump, no persist");
}

// ---- 21. Redo is blocked BEFORE it mutates the controller ----
{
  let persists = 0;
  const ed = createFieldEditor({ revisionId: REV, structureId: HOUSE, initial: resolveInitialSketch({ structureId: HOUSE }), persist: async () => { persists++; } });
  ed.commit({ ...ed.document, vertices: [{ id: "v1", x: 1, y: 1 }] });
  ed.undo();   // now a redo is available (done while unlocked)
  const genBefore = ed.editGeneration, docBefore = JSON.stringify(ed.document), canRedoBefore = ed.canRedo(), pBefore = persists;
  const locked = WIRE.editingLocked({ readOnly: false, conflict: C.conflictReview(conflictRow(REV, HOUSE, 5, 2), localDraft(REV, HOUSE, 5)) });
  if (!locked) ed.redo();
  assert.strictEqual(ed.editGeneration, genBefore, "blocked Redo did not increment edit generation");
  assert.strictEqual(JSON.stringify(ed.document), docBefore, "blocked Redo did not change the document");
  assert.strictEqual(ed.canRedo(), canRedoBefore, "redo history not consumed");
  assert.strictEqual(persists, pBefore, "blocked Redo did not persist");
  ok("Redo blocked before controller mutation: no doc change, no generation bump, no persist");
}

// ---- 22. Concurrency isolation: Structure A resolution rollback does NOT roll back Structure B's ack ----
{
  const store = mkStore(REV, HOUSE, 5, 2);                       // A = HOUSE conflict
  const bDetailKey = sketchDetailKey(REV, GARAGE);               // B = GARAGE authoritative ack cache
  store.cache[bDetailKey] = { document_version: 9, document: OFFICE, edit_mode: "connected_graph" };
  const rA = await runTx(store, "use_office", reviewedFor(REV, HOUSE, 5, 2), { failAt: "use_office:after_cache" });
  assert.strictEqual(rA.committed, false, "A rolled back");
  assert.strictEqual(store.rows[CID].state, "conflict", "A conflict preserved after A rollback");
  assert.ok(!(TK in store.cache), "A's own tx writes rolled back");
  assert.strictEqual(store.cache[bDetailKey].document_version, 9, "B's acknowledgement cache NOT rolled back with A");
  ok("concurrency: Structure A resolution rollback leaves Structure B's authoritative ack cache intact (A cannot alter B)");
}

// ---- 23. Reverse order: B ack first, then A resolution commits — neither absorbs the other ----
{
  const store = mkStore(REV, HOUSE, 5, 2);
  const bDetailKey = sketchDetailKey(REV, GARAGE);
  store.cache[bDetailKey] = { document_version: 9, document: OFFICE, edit_mode: "connected_graph" };   // B ack ran first
  const rA = await runTx(store, "use_office", reviewedFor(REV, HOUSE, 5, 2));                          // A commits after B
  assert.strictEqual(rA.committed, true);
  assert.ok(!store.rows[CID], "A conflict resolved (exact row deleted)");
  assert.strictEqual(store.cache[TK].document, OFFICE, "A's Office cache committed");
  assert.strictEqual(store.cache[bDetailKey].document_version, 9, "B's earlier ack cache preserved (B cannot alter A)");
  ok("concurrency (reverse): B acknowledgement then A resolution — both persist, neither absorbed into the other");
}

console.log("\nROOF SKETCH B3C ATOMIC CONFLICT RESOLUTION + LOCK: all " + n + " assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
