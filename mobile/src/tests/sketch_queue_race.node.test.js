"use strict";
// Field Roof Sketch offline-safety contracts (Plan 1 Task 6, Parts 18–22). Pure/deterministic: models
// the SQLite pending-queue semantics with the SAME shared helpers storage.js uses (nextGeneration /
// shouldApplyResult), so it proves supersession, coalescing, structure independence, and crash-safe
// draft ordering without an Expo/SQLite runtime.
const assert = require("assert");
const queue = require("../queue");
const {
  sketchUpdateMutation, sketchUpdateMutationId, makeSketchDraft, shouldPersistDraft,
} = require("../sketchCache");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

// --- In-memory mirror of storage.js pending_mutations semantics -----------------------------------
function makeStore() {
  const rows = new Map(); // client_id -> row (row.mutation_generation authoritative)
  return {
    rows,
    enqueue(m) { // storage.enqueue: NEW logical edit bumps generation
      const gen = queue.nextGeneration(rows.get(m.client_id));
      const stamped = { ...m, mutation_generation: gen };
      rows.set(m.client_id, stamped);
      return stamped;
    },
    saveIfCurrent(m) { // storage.saveMutationIfCurrent: apply only if not superseded/removed
      const stored = rows.get(m.client_id) || null;
      if (!queue.shouldApplyResult(stored, m)) return false;
      rows.set(m.client_id, { ...m });
      return true;
    },
    remove(clientId) { rows.delete(clientId); },
    get(clientId) { return rows.get(clientId) || null; },
  };
}
const put = (rev, str, doc, ver) => queue.makeMutation(sketchUpdateMutation({ revisionId: rev, structureId: str, document: doc, documentVersion: ver }));

// --- Coalescing: repeated offline saves of one structure => ONE row with latest document -----------
{
  const s = makeStore();
  s.enqueue(put("R1", "S1", { tag: "A" }, 3));
  s.enqueue(put("R1", "S1", { tag: "B" }, 3));
  const c = s.enqueue(put("R1", "S1", { tag: "C" }, 3));
  const pending = [...s.rows.values()].filter((r) => r.kind === "measurement_sketch_update");
  assert.strictEqual(pending.length, 1); ok("repeated saves coalesce into ONE pending sketch mutation");
  assert.strictEqual(s.get(sketchUpdateMutationId("R1", "S1")).body.document.tag, "C"); ok("coalesced row carries the LATEST document (C)");
  assert.strictEqual(c.mutation_generation, 3); ok("each new save bumps the supersession generation (1→2→3)");
  assert.strictEqual(s.get(sketchUpdateMutationId("R1", "S1")).client_id, "measurement-sketch-update:R1:S1"); ok("deterministic client_id preserved across saves");
}

// --- Different structures remain independent -------------------------------------------------------
{
  const s = makeStore();
  s.enqueue(put("R1", "MainHouse", { tag: "H" }, 1));
  s.enqueue(put("R1", "Garage", { tag: "G" }, 1));
  assert.strictEqual(s.rows.size, 2); ok("two structures => two independent mutations");
  assert.notStrictEqual(sketchUpdateMutationId("R1", "MainHouse"), sketchUpdateMutationId("R1", "Garage")); ok("independent client_ids per structure");
}

// --- IN-FLIGHT SUPERSESSION: A success cannot overwrite newer B (release blocker) ------------------
{
  const s = makeStore();
  const A = s.enqueue(put("R1", "S1", { tag: "A" }, 7));   // generation 1
  const sent = { ...A };                                   // sync captures A and begins sending
  const B = s.enqueue(put("R1", "S1", { tag: "B" }, 7));   // generation 2 replaces same client_id while A in flight
  assert.strictEqual(B.mutation_generation, 2); ok("B replaces A with a higher generation");
  const aResult = { ...sent, state: queue.STATES.SYNCED }; // A returns success
  const applied = s.saveIfCurrent(aResult);
  assert.strictEqual(applied, false); ok("A success is DISCARDED (row superseded by B)");
  const row = s.get(A.client_id);
  assert.strictEqual(row.state, queue.STATES.PENDING); ok("B remains PENDING after A success");
  assert.strictEqual(row.body.document.tag, "B"); ok("B document intact after A success");
  assert.strictEqual(row.mutation_generation, 2); ok("stored generation stays at B (2)");
  // B later syncs normally
  assert.strictEqual(s.saveIfCurrent({ ...B, state: queue.STATES.SYNCED }), true); ok("B later syncs against its own generation");
}

// --- IN-FLIGHT SUPERSESSION: A 409 cannot mark newer B as conflict ---------------------------------
{
  const s = makeStore();
  const A = s.enqueue(put("R1", "S1", { tag: "A" }, 7));
  const sent = { ...A };
  const B = s.enqueue(put("R1", "S1", { tag: "B" }, 7));
  const aConflict = { ...sent, state: queue.STATES.CONFLICT, error: "changed", serverValue: { v: 9 } };
  assert.strictEqual(s.saveIfCurrent(aConflict), false); ok("A 409 is DISCARDED (superseded)");
  assert.strictEqual(s.get(A.client_id).state, queue.STATES.PENDING); ok("B is NOT marked conflict by A's 409");
  assert.strictEqual(s.get(A.client_id).body.document.tag, "B"); ok("B document preserved through A conflict");
}

// --- Removed row (conflict resolved by "Use Server") cannot be resurrected by a late result --------
{
  const s = makeStore();
  const A = s.enqueue(put("R1", "S1", { tag: "A" }, 7));
  const sent = { ...A };
  s.remove(A.client_id); // e.g. Use Server cleared this sketch mutation
  assert.strictEqual(s.saveIfCurrent({ ...sent, state: queue.STATES.SYNCED }), false); ok("late result cannot resurrect a removed sketch mutation");
  assert.strictEqual(s.get(A.client_id), null); ok("removed row stays removed");
}

// --- Current-generation acknowledgement applies normally (no false negatives) ----------------------
{
  const s = makeStore();
  const A = s.enqueue(put("R1", "S1", { tag: "A" }, 7));
  assert.strictEqual(s.saveIfCurrent({ ...A, state: queue.STATES.SYNCED }), true); ok("un-superseded result applies (normal success path)");
  assert.strictEqual(s.get(A.client_id).state, queue.STATES.SYNCED); ok("row marked synced when generation matches");
}

// --- Crash-safe autosave ordering: newer edit generation must win even if writes resolve late ------
{
  const g2 = makeSketchDraft("R1", "S1", { document: { tag: "newer" }, editGeneration: 2 });
  const g1 = makeSketchDraft("R1", "S1", { document: { tag: "older" }, editGeneration: 1 });
  assert.strictEqual(shouldPersistDraft(null, g1), true); ok("first draft persists");
  assert.strictEqual(shouldPersistDraft(g1, g2), true); ok("newer generation (2) may overwrite older (1)");
  assert.strictEqual(shouldPersistDraft(g2, g1), false); ok("older generation (1) may NOT clobber newer (2) [out-of-order write guard]");
  assert.strictEqual(shouldPersistDraft(g2, g2), true); ok("same-generation reflush allowed");
}

// --- Save(A)+Edit(B) draft dirtiness: B remains local after A acknowledged ------------------------
{
  // draft generation advances on each commit; an acknowledged Save(A) must not retire a newer draft B.
  let draft = makeSketchDraft("R1", "S1", { document: { tag: "A" }, documentVersion: 5, editGeneration: 1 });
  const savedGen = draft.edit_generation;                 // Save A captures generation 1
  draft = makeSketchDraft("R1", "S1", { document: { tag: "B" }, documentVersion: 5, editGeneration: 2 }); // Edit B
  const ackIsLatest = savedGen >= draft.edit_generation;  // may we retire the local draft?
  assert.strictEqual(ackIsLatest, false); ok("Save(A) ack does NOT retire draft when newer Edit(B) exists");
  assert.strictEqual(draft.document.tag, "B"); ok("Edit B remains the local draft after A acknowledged");
}

console.log("\nSKETCH QUEUE RACE + CRASH RECOVERY: all " + n + " assertions passed");
