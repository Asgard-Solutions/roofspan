"use strict";
// RoofSpan Field — Save vs. working-draft autosave RACE regression (#2), deterministic + pure (Node, no RN).
//
// Proves the root-cause guarantee: when a debounced working-draft autosave is in flight / delayed and the
// rep presses Save (which stages the measurement mutation and clears the working draft), a late autosave can
// NEVER resurrect stale working-draft data — in EITHER interleaving order. Also proves: exactly one mutation
// is staged (no duplicate), hidden/system metadata is preserved, and a reopen shows the saved/queued copy.
//
// Uses the REAL production modules: createMeasurementWorkingDraftStore (the seal store the screen wires) and
// resolveMeasurementView (the reopen resolver). A NAIVE guard-at-entry-only implementation would fail the
// "Save first, late autosave second" case; the serialized re-checked seal makes both cases safe.

const assert = require("assert");
const { createMeasurementWorkingDraftStore } = require("../measurementWorkingDraft");
const { resolveMeasurementView } = require("../measurementReconcile");

let n = 0;
const ok = (m) => { n++; console.log("  \u2713 " + m); };
const tick = () => new Promise((r) => setImmediate(r)); // yield so serialized async tasks drain

// In-memory serialized cache slot for ONE scope. `delay` forces an async gap inside put/clear so an
// "in-flight" write is realistic; ordering is still owned by the store's serialized chain.
function makeSlot(delay = 0) {
  let value = undefined; // the working-draft slot; null = explicitly cleared
  const wait = () => (delay ? new Promise((r) => setTimeout(r, delay)) : Promise.resolve());
  return {
    put: async (v) => { await wait(); value = v; return true; },
    clear: async () => { await wait(); value = null; },
    get: () => value,
  };
}

// A durable mutation queue keyed by client_id (mirrors queueMutation coalescing → newest wins, single row).
function makeQueue() {
  const rows = new Map();
  return {
    stage: (m) => { rows.set(m.client_id, { ...(rows.get(m.client_id) || {}), ...m, state: "pending" }); },
    all: () => Array.from(rows.values()),
    get: (id) => rows.get(id),
  };
}

const REV = { id: "REV1", if_match: "v2", source: "field", revision_number: 3, status: "draft", editable: true,
  provider: "eagleview", report_id: "EV-778", notes: "office-only note", reported_area_sqft: 2200 };

// Build the optimistic detail + mutation body the screen's save() produces — carries ALL hidden metadata.
function buildSaved(existing, formFacets) {
  const body = { provider: existing.provider, report_id: existing.report_id, notes: existing.notes,
    reported_area_sqft: existing.reported_area_sqft, facets: formFacets, structures: [], edges: [], penetrations: [], summary: {} };
  const optimistic = { id: existing.id, updated_at: existing.if_match, status: existing.status, editable: true,
    source: existing.source, revision_number: existing.revision_number,
    provider: body.provider, report_id: body.report_id, notes: body.notes, reported_area_sqft: body.reported_area_sqft,
    facets: body.facets, structures: body.structures, edges: body.edges, penetrations: body.penetrations, summary: body.summary };
  return { body, optimistic };
}

// The screen's save() essence: stage mutation (idempotent client_id) + seal-and-clear the working draft.
async function doSave(store, queue, existing, formFacets) {
  const { body, optimistic } = buildSaved(existing, formFacets);
  queue.stage({ client_id: `measurement-update:${existing.id}`, kind: "measurement_update", method: "put",
    path: `/mobile/measurements/${existing.id}`, body, ifMatch: existing.if_match, optimistic });
  await store.sealAndClear();
  return optimistic;
}

const STALE_FACETS = [{ ref: "MF1", facet_label: "F1", area_sqft: 100 }]; // half-typed, superseded value
const SAVED_FACETS = [{ ref: "MF1", facet_label: "F1", area_sqft: 480 }]; // the value the rep actually saved

(async () => {
// ---- 1. Autosave fires FIRST, then Save (P before C) → clear wins; draft not resurrected ----
{
  const slot = makeSlot(5);
  const store = createMeasurementWorkingDraftStore({ put: slot.put, clear: slot.clear });
  const queue = makeQueue();
  const pAuto = store.persist({ working: true, facets: STALE_FACETS });  // in-flight autosave (not awaited)
  const pSave = doSave(store, queue, REV, SAVED_FACETS);                 // Save presses immediately after
  await Promise.all([pAuto, pSave]);
  await tick();
  assert.strictEqual(slot.get(), null, "working draft is cleared, not the stale autosaved value");
  assert.strictEqual(store.isSealed(), true);
  assert.strictEqual(queue.all().length, 1, "exactly one mutation staged");
  ok("autosave-first then Save → working draft cleared (stale value not resurrected), one mutation");
}

// ---- 2. Save FIRST, then a LATE autosave (C before P) → seal makes the late write a no-op ----
{
  const slot = makeSlot(5);
  const store = createMeasurementWorkingDraftStore({ put: slot.put, clear: slot.clear });
  const queue = makeQueue();
  const pSave = doSave(store, queue, REV, SAVED_FACETS);                 // Save stages + seals + clears
  const pLate = store.persist({ working: true, facets: STALE_FACETS }); // a late autosave sneaks in after
  await Promise.all([pSave, pLate]);
  await tick();
  const lateResult = await pLate;
  assert.strictEqual(lateResult, false, "the late autosave persist is a durable no-op (sealed)");
  assert.strictEqual(slot.get(), null, "late autosave did NOT recreate the working draft");
  assert.strictEqual(queue.all().length, 1, "still exactly one mutation (no duplicate)");
  ok("Save-first then late autosave → sealed no-op, no stale draft recreated, no duplicate mutation");
}

// ---- 3. Hidden/system metadata preserved through the staged save (not nulled by the form) ----
{
  const slot = makeSlot();
  const store = createMeasurementWorkingDraftStore({ put: slot.put, clear: slot.clear });
  const queue = makeQueue();
  await doSave(store, queue, REV, SAVED_FACETS);
  const staged = queue.get("measurement-update:REV1");
  assert.strictEqual(staged.body.provider, "eagleview", "provider preserved");
  assert.strictEqual(staged.body.report_id, "EV-778", "report_id preserved");
  assert.strictEqual(staged.body.notes, "office-only note", "office notes preserved");
  assert.strictEqual(staged.body.reported_area_sqft, 2200, "reported area preserved");
  assert.strictEqual(staged.body.facets[0].area_sqft, 480, "the rep's saved facet value is what was staged");
  ok("staged mutation preserves hidden/system metadata + the rep's saved measurement value");
}

// ---- 4. Reopen after the race → shows the SAVED/queued measurement (via real resolveMeasurementView) ----
{
  const slot = makeSlot(3);
  const store = createMeasurementWorkingDraftStore({ put: slot.put, clear: slot.clear });
  const queue = makeQueue();
  const pAuto = store.persist({ working: true, facets: STALE_FACETS });
  const optimistic = await doSave(store, queue, REV, SAVED_FACETS);
  await pAuto; await tick();
  // Reopen: working slot is null → screen resolves from optimistic cache + the pending update row.
  assert.strictEqual(slot.get(), null, "no working draft remains to hydrate on reopen");
  const v = resolveMeasurementView({
    serverDetail: { id: "REV1", updated_at: "v2", facets: [{ id: "MF1", area_sqft: 100 }] },
    serverStale: false, optimistic,
    pendingUpdate: { client_id: "measurement-update:REV1", ifMatch: "v2", state: "pending" },
    pendingCreate: null, isSyncing: false,
  });
  assert.strictEqual(v.kind, "local_update", "reopen shows the queued local save, not the server or a stale draft");
  assert.strictEqual(v.detail.facets[0].area_sqft, 480, "reopen shows the saved value (480), never the stale 100");
  assert.strictEqual(v.conflict, false);
  ok("reopen after the race shows the saved/queued measurement (no stale working draft, no conflict)");
}

// ---- 5. Revert-to-baseline clear is NOT a seal → editing may resume and autosave persists again ----
{
  const slot = makeSlot();
  const store = createMeasurementWorkingDraftStore({ put: slot.put, clear: slot.clear });
  await store.persist({ working: true, facets: STALE_FACETS });
  await store.clearUnsealed();                 // rep reverted all edits back to the baseline
  assert.strictEqual(store.isSealed(), false, "revert clear does not seal the scope");
  const resumed = await store.persist({ working: true, facets: SAVED_FACETS }); // new edits resume
  assert.strictEqual(resumed, true, "a fresh working draft persists after an unsealed revert");
  assert.deepStrictEqual(slot.get().facets, SAVED_FACETS);
  ok("revert-to-baseline clears without sealing; later autosave still persists new edits");
}

console.log("\nFIELD MEASUREMENT SAVE/AUTOSAVE RACE: all " + n + " assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
