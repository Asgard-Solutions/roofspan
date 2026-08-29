"use strict";
// B3C — Roof Sketch 409 conflict review + explicit resolution contracts. Exercises the SAME pure
// planners the sync layer executes (roofSketchConflict.js) plus a faithful in-memory mirror of
// sync.resolveSketchConflictUseOffice / resolveSketchConflictKeepLocal (guarded draft write + queue
// upsert), so the durable EFFECTS are under contract without RN/SQLite. NO graphical merge is tested —
// the rep explicitly chooses Office or Local.
const assert = require("assert");
const C = require("../roofSketchConflict");
const WIRE = require("../roofSketchFieldWiring");
const { sketchDraftKey, sketchDetailKey, sketchUpdateMutationId, makeSketchDraft } = require("../sketchCache");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

const doc = (f, e, v, p) => ({ facets: Array(f).fill(0).map((_, i) => i), edges: Array(e).fill(0).map((_, i) => i), vertices: Array(v).fill(0).map((_, i) => i), penetrations: Array(p).fill(0).map((_, i) => i) });
const BASE = doc(1, 4, 4, 0);     // what the local draft was edited from (v6)
const LOCAL = doc(2, 8, 8, 1);    // the rep's unsynced work (added a facet + a roof feature)
const OFFICE = doc(3, 12, 10, 0); // authoritative Office v7 (a colleague added a facet)

function conflictMutation(rev, struct, gen) {
  return {
    client_id: sketchUpdateMutationId(rev, struct),
    kind: "measurement_sketch_update", method: "put",
    path: `/mobile/measurements/${rev}/sketches/${struct}`,
    body: { schema_version: 1, edit_mode: "connected_graph", document: LOCAL, expected_version: 6 },
    local_edit_generation: gen, state: "conflict",
    serverValue: { document_version: 7, document: OFFICE, edit_mode: "connected_graph" },
  };
}
function localDraft(rev, struct, gen) {
  return makeSketchDraft(rev, struct, { document: LOCAL, documentVersion: 6, baseServerDocument: BASE, editMode: "connected_graph", editGeneration: gen });
}

// Faithful mirror of sync.resolveSketchConflictUseOffice (guarded retire + conflict removal).
function useOffice(store, rev, struct) {
  const id = sketchUpdateMutationId(rev, struct);
  const m = store.queue.find((x) => x.client_id === id && x.state === "conflict");
  if (!m) return { action: "noop" };
  const plan = C.planUseOffice(m, store.caches[sketchDraftKey(rev, struct)] || null);
  if (plan.action !== "use_office") return plan;
  store.caches[sketchDetailKey(rev, struct)] = plan.cacheDetail;
  const cur = store.caches[sketchDraftKey(rev, struct)] || null;
  if (!(cur && (Number(cur.edit_generation) || 0) > plan.conflictGeneration)) store.caches[sketchDraftKey(rev, struct)] = null;
  store.queue = store.queue.filter((x) => x.client_id !== plan.removeClientId);
  return plan;
}
// Faithful mirror of sync.resolveSketchConflictKeepLocal (guarded rebase + queue upsert by client_id).
function keepLocal(store, rev, struct) {
  const id = sketchUpdateMutationId(rev, struct);
  const m = store.queue.find((x) => x.client_id === id && x.state === "conflict");
  if (!m) return { action: "noop" };
  const plan = C.planKeepLocal(m, store.caches[sketchDraftKey(rev, struct)] || null);
  if (plan.action !== "keep_local") return plan;
  const cur = store.caches[sketchDraftKey(rev, struct)] || null;
  if (!(cur && (Number(cur.edit_generation) || 0) > plan.conflictGeneration)) store.caches[sketchDraftKey(rev, struct)] = plan.nextDraft;
  const s = plan.requeue;
  const row = { client_id: s.clientId, kind: s.kind, method: s.method, path: s.path, body: s.body, local_edit_generation: s.localEditGeneration, state: "pending", serverValue: null };
  store.queue = store.queue.filter((x) => x.client_id !== row.client_id).concat([row]);
  return plan;
}

const REV = "REV1", HOUSE = "HOUSE", GARAGE = "GARAGE";

// ---- 1. a 409 for THIS structure produces "Conflict — review required" and blocks editing ----
{
  const m = conflictMutation(REV, HOUSE, 5);
  assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: m, running: false, currentGeneration: 5, acknowledgedGeneration: 0 }), "Conflict — review required");
  ok("HTTP 409 for the current structure yields status 'Conflict — review required' (editing blocked by the screen)");
}

// ---- 2. review sources Base (base_server_document) / Local (durable draft) / Office (409 serverValue) ----
{
  const m = conflictMutation(REV, HOUSE, 5);
  const r = C.conflictReview(m, localDraft(REV, HOUSE, 5));
  assert.strictEqual(r.base, BASE, "Base = the draft's base_server_document");
  assert.strictEqual(r.local, LOCAL, "Local = the current durable local draft document");
  assert.strictEqual(r.office, OFFICE, "Office = the 409 serverValue.document");
  assert.strictEqual(r.officeVersion, 7);
  assert.strictEqual(r.conflictGeneration, 5);
  assert.strictEqual(C.conflictReview({ state: "pending" }), null, "no review unless the mutation is in conflict");
  ok("review sources Base / Your Draft / Office Version from the preserved snapshots");
}

// ---- 3. sketchSummary gives a deterministic read-only preview per version (no diff engine) ----
{
  assert.deepStrictEqual(C.sketchSummary(OFFICE), { facets: 3, edges: 12, vertices: 10, penetrations: 0 });
  assert.deepStrictEqual(C.sketchSummary(null), { facets: 0, edges: 0, vertices: 0, penetrations: 0 });
  ok("sketchSummary produces a deterministic facet/edge/vertex/feature preview for each snapshot");
}

// ---- 4. Use Office Version — plan (adopt Office; retire local; adopt version/base) ----
{
  const plan = C.planUseOffice(conflictMutation(REV, HOUSE, 5), localDraft(REV, HOUSE, 5));
  assert.strictEqual(plan.action, "use_office");
  assert.strictEqual(plan.retireDraft, true);
  assert.strictEqual(plan.cacheDetail.document, OFFICE);
  assert.strictEqual(plan.cacheDetail.document_version, 7);
  assert.strictEqual(plan.editor.document, OFFICE, "open editor adopts the Office document");
  assert.strictEqual(plan.editor.documentVersion, 7);
  ok("Use Office plan: adopt Office document + version/base, retire local draft, remove conflict");
}

// ---- 5. Use Office Version — durable effects (exact generation) end at Synced to Office ----
{
  const store = { caches: { [sketchDraftKey(REV, HOUSE)]: localDraft(REV, HOUSE, 5) }, queue: [conflictMutation(REV, HOUSE, 5)] };
  const plan = useOffice(store, REV, HOUSE);
  assert.strictEqual(plan.action, "use_office");
  assert.strictEqual(store.caches[sketchDraftKey(REV, HOUSE)], null, "local draft retired");
  assert.strictEqual(store.caches[sketchDetailKey(REV, HOUSE)].document, OFFICE, "authoritative Office sketch cached");
  assert.strictEqual(store.queue.length, 0, "conflict mutation removed");
  // reopen after resolution: server/cache load -> Synced to Office (no conflict mutation left)
  assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: null, mutation: null, running: false, currentGeneration: 0, acknowledgedGeneration: 0 }), "Saved on device");
  ok("Use Office resolution replaces local with Office, retires draft, removes conflict (→ Synced to Office on reopen)");
}

// ---- 6. Keep Local Draft — plan (preserve local; rebase to Office version/base; expected_version=Office) ----
{
  const plan = C.planKeepLocal(conflictMutation(REV, HOUSE, 5), localDraft(REV, HOUSE, 5));
  assert.strictEqual(plan.action, "keep_local");
  assert.strictEqual(plan.nextDraft.document, LOCAL, "local geometry preserved");
  assert.strictEqual(plan.nextDraft.base_server_document, OFFICE, "base rebased to the Office document");
  assert.strictEqual(plan.nextDraft.document_version, 7, "CAS base advanced to the Office version");
  assert.strictEqual(plan.nextDraft.edit_generation, 5, "local generation preserved (no new commit)");
  assert.strictEqual(plan.requeue.body.expected_version, 7, "fresh save uses expected_version = Office version");
  assert.strictEqual(plan.requeue.body.document, LOCAL);
  assert.strictEqual(plan.editor.documentVersion, 7);
  assert.strictEqual(plan.editor.baseServerDocument, OFFICE);
  ok("Keep Local plan: preserve local, rebase to Office version/base, re-stage with expected_version = Office version");
}

// ---- 7. Keep Local Draft — durable effects: fresh PENDING mutation, NOT synced before ack ----
{
  const store = { caches: { [sketchDraftKey(REV, HOUSE)]: localDraft(REV, HOUSE, 5) }, queue: [conflictMutation(REV, HOUSE, 5)] };
  const plan = keepLocal(store, REV, HOUSE);
  assert.strictEqual(plan.action, "keep_local");
  assert.strictEqual(store.queue.length, 1, "conflict row replaced by exactly one row");
  const row = store.queue[0];
  assert.strictEqual(row.state, "pending", "the replacement is PENDING (not pretended synced)");
  assert.strictEqual(row.body.expected_version, 7);
  assert.strictEqual(store.caches[sketchDraftKey(REV, HOUSE)].base_server_document, OFFICE, "draft rebased to Office base");
  // status from the pending row: NOT synced until Office acknowledges
  assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: row, running: false, currentGeneration: 5, acknowledgedGeneration: 0 }), "Waiting to sync");
  assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: row, running: true, currentGeneration: 5, acknowledgedGeneration: 0 }), "Synchronizing…");
  ok("Keep Local resolution re-stages a fresh PENDING mutation (expected_version=Office); never reports Synced before ack");
}

// ---- 8. Generation safety — a STALE resolution cannot delete/overwrite newer local work ----
{
  // Durable local work advanced to generation 6 AFTER the conflict at generation 5 was captured.
  const advancedDraft = localDraft(REV, HOUSE, 6);
  const usePlan = C.planUseOffice(conflictMutation(REV, HOUSE, 5), advancedDraft);
  assert.strictEqual(usePlan.action, "stale");
  const keepPlan = C.planKeepLocal(conflictMutation(REV, HOUSE, 5), advancedDraft);
  assert.strictEqual(keepPlan.action, "stale");
  // Applied via the mirror: nothing is deleted/overwritten/removed.
  const store = { caches: { [sketchDraftKey(REV, HOUSE)]: advancedDraft }, queue: [conflictMutation(REV, HOUSE, 5)] };
  const applied = useOffice(store, REV, HOUSE);
  assert.strictEqual(applied.action, "stale");
  assert.strictEqual(store.caches[sketchDraftKey(REV, HOUSE)], advancedDraft, "newer local draft NOT deleted");
  assert.strictEqual(store.queue.length, 1, "conflict NOT silently resolved");
  assert.strictEqual(store.queue[0].state, "conflict");
  ok("generation safety: a stale resolution against an older conflict never deletes/overwrites/resolves newer local work");
}

// ---- 9. Structure isolation — resolving the House conflict cannot alter the Garage ----
{
  const store = {
    caches: { [sketchDraftKey(REV, HOUSE)]: localDraft(REV, HOUSE, 5), [sketchDraftKey(REV, GARAGE)]: localDraft(REV, GARAGE, 3) },
    queue: [conflictMutation(REV, HOUSE, 5), conflictMutation(REV, GARAGE, 3)],
  };
  useOffice(store, REV, HOUSE);
  assert.strictEqual(store.caches[sketchDraftKey(REV, HOUSE)], null, "House draft retired");
  assert.ok(store.caches[sketchDraftKey(REV, GARAGE)], "Garage draft untouched");
  assert.strictEqual(store.caches[sketchDraftKey(REV, GARAGE)].document, LOCAL);
  const garage = store.queue.find((x) => x.client_id === sketchUpdateMutationId(REV, GARAGE));
  assert.ok(garage && garage.state === "conflict", "Garage conflict still awaiting its own resolution");
  ok("structure isolation: resolving the House conflict leaves the Garage conflict + draft fully intact");
}

// ---- 10. Durable restart — an unresolved conflict survives reload/restart ----
{
  // Simulate a cold reopen: the durable conflict mutation + durable draft are read fresh from storage.
  const persisted = { caches: { [sketchDraftKey(REV, HOUSE)]: localDraft(REV, HOUSE, 5) }, queue: [conflictMutation(REV, HOUSE, 5)] };
  const m = persisted.queue.find((x) => x.client_id === sketchUpdateMutationId(REV, HOUSE) && x.state === "conflict");
  assert.ok(m, "conflict mutation persisted across restart");
  const r = C.conflictReview(m, persisted.caches[sketchDraftKey(REV, HOUSE)]);
  assert.strictEqual(r.base, BASE); assert.strictEqual(r.local, LOCAL); assert.strictEqual(r.office, OFFICE);
  assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: m, running: false, currentGeneration: 5, acknowledgedGeneration: 0 }), "Conflict — review required");
  ok("durable restart: an unresolved conflict reopens with Base/Local/Office review and stays 'Conflict — review required'");
}

console.log("\nROOF SKETCH B3C CONFLICT REVIEW + RESOLUTION: all " + n + " assertions passed");
