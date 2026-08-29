"use strict";
// B3B2 contracts: truthful structure-specific live sync status + acknowledged CAS-metadata adoption in
// the OPEN Field Roof Sketch editor. Exercises the SAME pure helpers the screen uses in production
// (WIRE.fieldSketchSyncStatus + controller.adoptServerVersion) and the deterministic mutation identity.
const assert = require("assert");
const WIRE = require("../roofSketchFieldWiring");
const { createFieldEditor } = require("../roofSketchFieldController");
const { sketchUpdateMutationId } = require("../sketchCache");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };
const S = (id) => ({ vertices: [{ id }] });
const mut = (rev, str, state, gen, extra = {}) => ({ client_id: sketchUpdateMutationId(rev, str), kind: "measurement_sketch_update", state, local_edit_generation: gen, body: { expected_version: 5 }, ...extra });
// Mirrors sync.currentSketchMutation: strictly the deterministic row for THIS structure (never global).
const pick = (all, rev, str) => all.find((x) => x.client_id === sketchUpdateMutationId(rev, str)) || null;

// ---- 1. pending current sketch -> Waiting to sync ----
{
  const s = WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: mut("R", "S", "pending", 2), running: false, currentGeneration: 2, acknowledgedGeneration: 0 });
  assert.strictEqual(s, "Waiting to sync");
  ok("pending current sketch (not processing) -> Waiting to sync");
}

// ---- 2. current sketch during active sync -> Synchronizing… ----
{
  const s = WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: mut("R", "S", "pending", 2), running: true, currentGeneration: 2, acknowledgedGeneration: 0 });
  assert.strictEqual(s, "Synchronizing\u2026");
  ok("pending current sketch while sync is running -> Synchronizing\u2026");
}

// ---- 3. acknowledged current generation -> Synced to Office ----
{
  const s = WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: mut("R", "S", "synced", 3), running: false, currentGeneration: 3, acknowledgedGeneration: 3 });
  assert.strictEqual(s, "Synced to Office");
  ok("acknowledged CURRENT generation with no newer work -> Synced to Office");
}

// ---- 4. A acknowledged while newer B exists -> NOT synced ----
{
  // The row is B pending (A's success was a no-op supersession); current gen is B(3), acked is A(2).
  const s = WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: mut("R", "S", "pending", 3), running: false, currentGeneration: 3, acknowledgedGeneration: 2 });
  assert.strictEqual(s, "Waiting to sync");
  assert.notStrictEqual(s, "Synced to Office");
  ok("A acknowledged while newer B exists -> NOT Synced to Office");
}
// even with no active mutation, an ack for an OLDER generation than the current committed one is not synced
{
  const s = WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: null, running: false, currentGeneration: 3, acknowledgedGeneration: 2 });
  assert.strictEqual(s, "Saved on device");
  ok("older-generation ack with newer local work -> Saved on device (not Synced)");
}

// ---- 9. conflict -> Conflict — review required ----
{
  const s = WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: mut("R", "S", "conflict", 2), running: false, currentGeneration: 2, acknowledgedGeneration: 0 });
  assert.strictEqual(s, "Conflict \u2014 review required");
  ok("current sketch conflict -> Conflict \u2014 review required");
}

// ---- 10. durable failed -> Sync issue — retry needed (NOT "Waiting to sync") ----
{
  const s = WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: mut("R", "S", "failed", 2), running: false, currentGeneration: 2, acknowledgedGeneration: 0 });
  assert.strictEqual(s, "Sync issue \u2014 retry needed");
  ok("durable failed sketch mutation -> Sync issue \u2014 retry needed (not Waiting to sync)");
}

// ---- 11. device-durability precedence ----
{
  assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Could not save on device", mutation: mut("R", "S", "synced", 2), running: false, currentGeneration: 2, acknowledgedGeneration: 2 }), "Could not save on device");
  assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Saving on device\u2026", mutation: mut("R", "S", "pending", 2), running: true, currentGeneration: 2, acknowledgedGeneration: 0 }), "Saving on device\u2026");
  ok("device-durability status wins: Could-not-save / Saving-on-device precede queue status");
}

// ---- 7 & 8. structure isolation via the deterministic mutation id ----
{
  const queue = [
    { client_id: "photo-upload:abc", kind: "photo", state: "pending" },
    mut("R", "GARAGE", "pending", 4),          // another structure waiting
    mut("R", "HOUSE", "synced", 3),            // this structure acknowledged
  ];
  const house = pick(queue, "R", "HOUSE");
  const garage = pick(queue, "R", "GARAGE");
  assert.strictEqual(house.state, "synced"); assert.strictEqual(garage.state, "pending");
  // House status ignores the pending Garage + the pending photo entirely.
  assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: house, running: true, currentGeneration: 3, acknowledgedGeneration: 3 }), "Synced to Office");
  ok("an unrelated pending photo does NOT make this sketch look unsynced");
  ok("a pending Garage sketch does NOT change Main House status (deterministic per-structure lookup)");
}

// ---- 5 & 6. adoptServerVersion advances CAS metadata WITHOUT touching working state ----
{
  const initial = { document: S("a"), editMode: "connected_graph", documentVersion: 5, editGeneration: 1, baseServerDocument: S("srv5"), source: "server" };
  const ed = createFieldEditor({ revisionId: "R", structureId: "S", initial, persist: async () => {} });
  ed.commit(S("A"));                              // Edit A -> generation 2
  ed.commit(S("B"));                              // Edit B -> generation 3
  const beforeDoc = ed.document;
  const beforeGen = ed.editGeneration;
  const beforeUndo = ed.canUndo();
  // A acknowledged -> v6 / base S6
  ed.adoptServerVersion({ documentVersion: 6, baseServerDocument: S("srv6") });
  assert.strictEqual(ed.documentVersion, 6, "CAS version advanced 5 -> 6");
  assert.deepStrictEqual(ed.baseServerDocument, S("srv6"), "base server document advanced to S6");
  assert.strictEqual(ed.document, beforeDoc, "working document unchanged (same reference)");
  assert.strictEqual(ed.editGeneration, beforeGen, "edit generation unchanged");
  assert.strictEqual(ed.canUndo(), beforeUndo, "undo/redo history unchanged");
  ok("adoptServerVersion advances v5->v6 + base S6 without changing document/generation/history");
  // B acknowledged -> v7
  ed.adoptServerVersion({ documentVersion: 7, baseServerDocument: S("srv7") });
  assert.strictEqual(ed.documentVersion, 7, "CAS version advanced 6 -> 7");
  // monotonic: a stale older adopt cannot regress
  ed.adoptServerVersion({ documentVersion: 5, baseServerDocument: S("srv5") });
  assert.strictEqual(ed.documentVersion, 7, "adopt is monotonic: never regresses to 5");
  ok("B acknowledgement advances the editor to v7; adopt is monotonic");
}

// ---- 12. FULL SEQUENCE: server v5 -> Edit A -> Edit B -> A-ack v6 -> B-ack v7 ----
{
  const initial = { document: S("s5"), editMode: "connected_graph", documentVersion: 5, editGeneration: 1, baseServerDocument: S("s5"), source: "server" };
  const ed = createFieldEditor({ revisionId: "R", structureId: "HOUSE", initial, persist: async () => {} });
  const id = sketchUpdateMutationId("R", "HOUSE");
  const statusOf = (queue, running, acked) => WIRE.fieldSketchSyncStatus({
    localSave: "Saved on device", mutation: queue.find((x) => x.client_id === id) || null,
    running, currentGeneration: ed.editGeneration, acknowledgedGeneration: acked,
  });

  ed.commit(S("A"));                                            // Edit A -> gen 2
  ed.commit(S("B"));                                            // newer Edit B -> gen 3
  const docB = ed.document;

  // A in flight, B pending in the coalesced row (gen 3, expected_version still 5).
  let queue = [mut("R", "HOUSE", "pending", 3)];
  assert.strictEqual(statusOf(queue, true, 0), "Synchronizing\u2026", "while syncing -> Synchronizing…");

  // Office accepts A -> v6. B3B1 preserves B, rebases the durable draft to v6; row stays pending (B).
  // The screen adopts v6 from the durable draft WITHOUT changing B's document/generation.
  ed.adoptServerVersion({ documentVersion: 6, baseServerDocument: S("s6") });
  queue = [mut("R", "HOUSE", "pending", 3)];                    // still B pending
  const sAfterA = statusOf(queue, false, 2 /* acked = A */);
  assert.strictEqual(ed.documentVersion, 6, "editor adopted CAS v6 while B pending");
  assert.strictEqual(ed.document, docB, "B's working document is displayed unchanged");
  assert.strictEqual(ed.editGeneration, 3, "B's edit generation unchanged");
  assert.strictEqual(sAfterA, "Waiting to sync", "A-ack while B pending -> Waiting to sync (NOT Synced)");
  assert.notStrictEqual(sAfterA, "Synced to Office");

  // B succeeds -> v7. Row becomes synced with local_edit_generation = B(3); editor adopts v7.
  ed.adoptServerVersion({ documentVersion: 7, baseServerDocument: S("s7") });
  queue = [mut("R", "HOUSE", "synced", 3, { serverValue: { document_version: 7, document: S("s7") } })];
  const sAfterB = statusOf(queue, false, 3 /* acked = B */);
  assert.strictEqual(sAfterB, "Synced to Office", "only after B is the acknowledged current gen -> Synced to Office");
  assert.strictEqual(ed.documentVersion, 7, "editor now uses v7 for the next edit/save");
  ok("full A->B->A-ack(v6)->B-ack(v7): B shown unchanged, v6 adopted, not Synced until B, then v7 + Synced");
}

console.log("\nFIELD ROOF SKETCH LIVE STATUS (B3B2): all " + n + " assertions passed");
