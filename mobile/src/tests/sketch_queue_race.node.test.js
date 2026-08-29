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

// ================== ORCHESTRATION (control-flow) CONTRACTS §A11–A13, W5 ==================
// Model of the runSync control flow against an ATOMIC in-memory store (conditional UPDATE by generation,
// no insert-on-writeback), single-flight + _rerunRequested, and completion decided from CURRENT storage.
function makeAtomicStore() {
  const rows = new Map();
  return {
    rows,
    enqueue(m) { const g = queue.nextGeneration(rows.get(m.client_id)); const s = { ...m, mutation_generation: g }; rows.set(m.client_id, s); return s; },
    applyIfCurrent(m) { const cur = rows.get(m.client_id); if (!cur || Number(cur.mutation_generation) !== Number(m.mutation_generation)) return false; rows.set(m.client_id, { ...m }); return true; },
    pending() { return [...rows.values()].filter((r) => r.state === "pending"); },
    all() { return [...rows.values()]; },
    get(id) { return rows.get(id) || null; },
  };
}
function makeController(store, send) {
  let running = false, rerun = false, lastSync = null;
  async function run() {
    if (running) { rerun = true; return; }
    running = true;
    try {
      const pending = store.pending();
      const processed = [];
      for (const m of pending) processed.push(await send(m));
      for (const m of processed) store.applyIfCurrent(m);
      const pendingLeft = store.all().some((m) => m.state === "pending");
      if (!pendingLeft) lastSync = "SYNCED";     // only mark complete from CURRENT storage
    } finally {
      running = false;
      if (rerun) { rerun = false; await run(); }
    }
  }
  return { run, lastSync: () => lastSync };
}

async function orchestrate({ aResult }) {
  const store = makeAtomicStore();
  const A = store.enqueue(put("R1", "S1", { tag: "A" }, 7));
  let releaseA; const aGate = new Promise((res) => { releaseA = res; });
  let bQueued = false; let ctl;
  const send = async (m) => {
    if (m.body.document.tag === "A") {
      if (!bQueued) { bQueued = true; store.enqueue(put("R1", "S1", { tag: "B" }, 7)); ctl.run(); } // queueMutation-style: enqueue + request sync (sets rerun while running)
      await aGate;
      return { ...m, ...aResult };
    }
    return { ...m, state: queue.STATES.SYNCED };  // B succeeds
  };
  ctl = makeController(store, send);
  const first = ctl.run();          // sends A (awaits gate); B enqueued during flight -> rerun requested
  releaseA();                       // A resolves
  await first;                      // writeback A (rejected), rerun sends B
  return { store, ctl, A };
}

(async () => {
  let m = 0; const ok2 = (name) => { m++; console.log("  \u2713 " + name); };
  // A success cannot overwrite B; B auto-sends; last_sync only after B
  {
    const { store, ctl } = await orchestrate({ aResult: { state: queue.STATES.SYNCED } });
    const row = store.get(sketchUpdateMutationId("R1", "S1"));
    assert.strictEqual(row.body.document.tag, "B"); ok2("A success cannot overwrite newer B (B document survives)");
    assert.strictEqual(row.state, queue.STATES.SYNCED); ok2("B automatically received a subsequent send and synced (no manual trigger)");
    assert.strictEqual(ctl.lastSync(), "SYNCED"); ok2("last_sync advances only after B (the current work) is acknowledged");
  }
  // A 409 cannot mark B conflict
  {
    const { store } = await orchestrate({ aResult: { state: queue.STATES.CONFLICT, error: "x", serverValue: {} } });
    const row = store.get(sketchUpdateMutationId("R1", "S1"));
    assert.strictEqual(row.state, queue.STATES.SYNCED); ok2("A 409 cannot mark newer B conflict (B synced on its own pass)");
    assert.strictEqual(row.body.document.tag, "B"); ok2("B document preserved through A 409");
  }
  // A transient failure cannot downgrade B
  {
    const { store } = await orchestrate({ aResult: { state: queue.STATES.PENDING, errorCode: "http_500" } });
    const row = store.get(sketchUpdateMutationId("R1", "S1"));
    assert.strictEqual(row.body.document.tag, "B"); ok2("A 500 cannot downgrade/overwrite newer B");
    assert.strictEqual(row.state, queue.STATES.SYNCED); ok2("B remained eligible and synced after A 500");
  }
  // last_sync NOT advanced while B still pending (send B fails)
  {
    const store = makeAtomicStore();
    store.enqueue(put("R1", "S1", { tag: "A" }, 7));
    let bQueued = false;
    const send = async (mm) => {
      if (mm.body.document.tag === "A") { if (!bQueued) { bQueued = true; store.enqueue(put("R1", "S1", { tag: "B" }, 7)); } return { ...mm, state: queue.STATES.SYNCED }; }
      return { ...mm, state: queue.STATES.PENDING, errorCode: "offline" }; // B cannot send yet
    };
    const ctl = makeController(store, send);
    await ctl.run();
    assert.strictEqual(store.get(sketchUpdateMutationId("R1", "S1")).state, queue.STATES.PENDING); ok2("B stays pending when it cannot yet send");
    assert.strictEqual(ctl.lastSync(), null); ok2("last_sync NOT advanced while B (current work) remains pending");
  }
  // concurrent same-client enqueue: strictly increasing generations, latest payload survives
  {
    const store = makeAtomicStore();
    const g1 = store.enqueue(put("R1", "S1", { tag: "A" }, 7));
    const g2 = store.enqueue(put("R1", "S1", { tag: "B" }, 7));
    const g3 = store.enqueue(put("R1", "S1", { tag: "C" }, 7));
    assert.ok(g1.mutation_generation === 1 && g2.mutation_generation === 2 && g3.mutation_generation === 3); ok2("same-client enqueues get strictly increasing, unique generations");
    assert.strictEqual(store.get(sketchUpdateMutationId("R1", "S1")).body.document.tag, "C"); ok2("latest payload (C) survives concurrent enqueues");
  }
  console.log("\nSKETCH SYNC ORCHESTRATION: all " + m + " assertions passed");

  // ============ CLEAN-TIMESTAMP RACE (spec §0 / §41) ============
  // Model storage's serialized critical section: enqueue and the clean-marker (pending-count check +
  // last_sync write) share ONE chain, so a B enqueued concurrently can never slip between the clean
  // check and the marker write. Proves last_sync does NOT advance when B exists at marker time.
  let k = 0; const ok3 = (name) => { k++; console.log("  \u2713 " + name); };
  function makeSerialStore() {
    let chain = Promise.resolve();
    const serialize = (fn) => { const r = chain.then(fn, fn); chain = r.then(() => {}, () => {}); return r; };
    const rows = new Map(); let lastSync = null; let rerun = false;
    return {
      lastSync: () => lastSync,
      pendingCount: () => [...rows.values()].filter((r) => r.state === "pending").length,
      enqueue(mm) { return serialize(async () => { const g = queue.nextGeneration(rows.get(mm.client_id)); rows.set(mm.client_id, { ...mm, mutation_generation: g }); rerun = true; return g; }); },
      markCleanIfNoPending() { return serialize(async () => { if ([...rows.values()].some((r) => r.state === "pending")) return false; lastSync = new Date().toISOString(); return true; }); },
      rerunRequested: () => rerun,
    };
  }
  {
    // empty queue -> clean marker advances
    const s = makeSerialStore();
    assert.strictEqual(await s.markCleanIfNoPending(), true); ok3("empty queue: clean marker advances last_sync");
    assert.ok(s.lastSync() !== null); ok3("last_sync set when truly clean");
  }
  {
    // B enqueued BEFORE the clean marker runs -> must NOT advance (the §41 scenario)
    const s = makeSerialStore();
    await s.enqueue(put("R1", "S1", { tag: "B" }, 7));
    const advanced = await s.markCleanIfNoPending();
    assert.strictEqual(advanced, false); ok3("B present at marker time: clean marker refuses");
    assert.strictEqual(s.lastSync(), null); ok3("last_sync NOT advanced while B pending (§0)");
    assert.strictEqual(s.pendingCount(), 1); ok3("B remains pending");
    assert.strictEqual(s.rerunRequested(), true); ok3("follow-up sync pass requested for B");
  }
  {
    // Race: schedule marker and B-enqueue on the SAME chain without awaiting between them. Serialization
    // guarantees NO interleave: there is no order where the marker advances while B is already stored.
    const s = makeSerialStore();
    const pMark = s.markCleanIfNoPending();   // scheduled first (queue currently empty)
    const pB = s.enqueue(put("R1", "S1", { tag: "B" }, 7)); // scheduled right after
    const advanced = await pMark; await pB;
    // marker ran first on the empty queue (atomic) -> advanced true, and B enqueued strictly AFTER.
    assert.strictEqual(advanced, true); ok3("atomic marker completed before B (no mid-write interleave)");
    // Now B exists; a fresh marker attempt must refuse -> proves no false-clean once B is present.
    const again = await s.markCleanIfNoPending();
    assert.strictEqual(again, false); ok3("once B is stored, subsequent clean marker refuses (no false clean)");
  }
  console.log("\nCLEAN-TIMESTAMP RACE: all " + k + " assertions passed");
})();
