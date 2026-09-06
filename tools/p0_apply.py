#!/usr/bin/env python3
"""Apply and verify P0-5: generation-safe, atomic Use Office resolution."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one replacement, found {count}: {old[:140]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def run(*cmd: str, cwd: str | None = None) -> None:
    subprocess.run(cmd, cwd=ROOT / cwd if cwd else ROOT, check=True)


def run_expected_failure(*cmd: str) -> None:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    print(proc.stdout, flush=True)
    print(proc.stderr, flush=True)
    if proc.returncode == 0:
        raise RuntimeError("Regression test unexpectedly passed before the P0-5 production change")


# ---------------------------------------------------------------------------
# RED: prove exact-generation success, stale rejection, full-document adoption,
# rollback on write failure, seal-without-clear, and runtime wiring contracts.
# ---------------------------------------------------------------------------
write(
    "mobile/src/tests/measurement_conflict_transition.node.test.js",
    r'''"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const C = require("../measurementConflict");
const K = require("../measurementCache");
const { createMeasurementWorkingDraftStore } = require("../measurementWorkingDraft");

function clone(value) { return value == null ? value : JSON.parse(JSON.stringify(value)); }
function officeDetail(token = "office-v7") {
  return {
    id: "R1", set_id: "SET1", revision_number: 4, status: "draft", editable: true,
    source: "office", updated_at: token, created_at: "2026-09-06T10:00:00Z",
    lead_id: "L1", property_id: "P1", inspection_id: "I1",
    provider: "eagleview", report_id: "EV-1", reported_area_sqft: 1800, notes: "Office wins",
    structures: [{ id: "S1", name: "House", structure_type: "main_house" }],
    facets: [{ id: "F1", structure_id: "S1", facet_label: "F1", area_sqft: 1800 }],
    edges: [{ id: "E1", facet_id: "F1", edge_type: "ridge", length_ft: 52 }],
    penetrations: [], summary: null, totals: { total_area_sqft: 1800 },
  };
}
function mutation({ generation = 2, state = "conflict" } = {}) {
  return {
    client_id: "measurement-update:R1", kind: "measurement_update", state,
    mutation_generation: generation, ifMatch: "field-v1",
    body: { lead_id: "L1", structures: [], facets: [], edges: [], penetrations: [], summary: {} },
  };
}
function initialState(row = mutation()) {
  const scope = { lead_id: "L1" };
  return {
    mutations: { [row.client_id]: clone(row) },
    caches: {
      [K.detailKey("R1")]: { id: "R1", updated_at: "field-v1", facets: [{ area_sqft: 1000 }] },
      [K.draftKey(scope)]: { local_draft: true },
      [K.workingKey(scope)]: { working: true, facets: [{ area_sqft: 1000 }] },
      [K.scopeKey(scope)]: [{ id: "R0", revision_number: 3 }, { id: "R1", revision_number: 4, total_area_sqft: 1000 }],
    },
  };
}
function makeExecutor(scratch, failKey = null) {
  return {
    readMutation: async (clientId) => clone(scratch.mutations[clientId] || null),
    readCache: async (key) => clone(Object.prototype.hasOwnProperty.call(scratch.caches, key) ? scratch.caches[key] : null),
    writeCache: async (key, value) => {
      if (key === failKey) throw new Error("injected cache failure");
      scratch.caches[key] = clone(value);
    },
    deleteMutation: async (clientId, generation, expectedState) => {
      const row = scratch.mutations[clientId];
      if (!row || Number(row.mutation_generation || 1) !== Number(generation) || row.state !== expectedState) return 0;
      delete scratch.mutations[clientId];
      return 1;
    },
  };
}
async function atomic(state, callback, failKey = null) {
  const scratch = clone(state);
  const result = await callback(makeExecutor(scratch, failKey));
  state.mutations = scratch.mutations;
  state.caches = scratch.caches;
  return result;
}

async function main() {
  const scope = { lead_id: "L1" };

  // Exact reviewed generation: remove only that row and adopt the complete Office document everywhere.
  {
    const state = initialState();
    const built = C.buildMeasurementUseOfficeReview(mutation(), scope, officeDetail());
    assert.strictEqual(built.ok, true);
    const result = await atomic(state, (tx) => C.applyMeasurementResolutionInTx(tx, built.reviewed));
    assert.strictEqual(result.action, "use_office");
    assert.deepStrictEqual(state.mutations, {});
    assert.deepStrictEqual(state.caches[K.detailKey("R1")], officeDetail());
    assert.strictEqual(state.caches[K.draftKey(scope)], null);
    assert.strictEqual(state.caches[K.workingKey(scope)], null);
    const list = state.caches[K.scopeKey(scope)];
    assert.strictEqual(list.length, 2);
    assert.deepStrictEqual(list.find((x) => x.id === "R1"), officeDetail());
  }

  // A newer local generation landed after review: the old choice is stale and NOTHING changes.
  {
    const reviewed = C.buildMeasurementUseOfficeReview(mutation({ generation: 2 }), scope, officeDetail()).reviewed;
    const state = initialState(mutation({ generation: 3 }));
    const before = clone(state);
    await assert.rejects(
      () => atomic(state, (tx) => C.applyMeasurementResolutionInTx(tx, reviewed)),
      (e) => e && e.__stale === "mutation_generation_changed",
    );
    assert.deepStrictEqual(state, before);
  }

  // State/revision drift is stale rather than a broad delete.
  {
    const reviewed = C.buildMeasurementUseOfficeReview(mutation({ state: "conflict" }), scope, officeDetail()).reviewed;
    const state = initialState(mutation({ state: "pending" }));
    const before = clone(state);
    await assert.rejects(
      () => atomic(state, (tx) => C.applyMeasurementResolutionInTx(tx, reviewed)),
      (e) => e && e.__stale === "mutation_state_changed",
    );
    assert.deepStrictEqual(state, before);
  }

  // Any cache failure aborts the entire logical transaction, including mutation deletion.
  {
    const state = initialState();
    const before = clone(state);
    const reviewed = C.buildMeasurementUseOfficeReview(mutation(), scope, officeDetail()).reviewed;
    await assert.rejects(
      () => atomic(state, (tx) => C.applyMeasurementResolutionInTx(tx, reviewed), K.workingKey(scope)),
      /injected cache failure/,
    );
    assert.deepStrictEqual(state, before);
  }

  // A partial screen model is never accepted as the authoritative Office revision.
  {
    const partial = { id: "R1", updated_at: "office-v7", status: "draft", editable: true };
    const result = C.buildMeasurementUseOfficeReview(mutation(), scope, partial);
    assert.strictEqual(result.ok, false);
    assert.strictEqual(result.reason, "office_revision_incomplete");
  }

  // Failed updates use the same exact-state transition once a full Office revision is fetched.
  {
    const failed = mutation({ state: "failed", generation: 9 });
    const built = C.buildMeasurementUseOfficeReview(failed, scope, officeDetail("office-v9"));
    assert.strictEqual(built.ok, true);
    const state = initialState(failed);
    const result = await atomic(state, (tx) => C.applyMeasurementResolutionInTx(tx, built.reviewed));
    assert.strictEqual(result.action, "use_office");
    assert.deepStrictEqual(state.caches[K.detailKey("R1")], officeDetail("office-v9"));
  }

  // Use Office seals/drains autosaves without clearing outside the atomic storage transaction.
  {
    let slot = { working: true };
    let clears = 0;
    const store = createMeasurementWorkingDraftStore({
      put: async (v) => { slot = v; return true; },
      clear: async () => { clears += 1; slot = null; },
    });
    await store.seal();
    assert.strictEqual(store.isSealed(), true);
    assert.deepStrictEqual(slot, { working: true });
    assert.strictEqual(clears, 0);
    assert.strictEqual(await store.persist({ working: true, newer: true }), false);
  }

  // Static wiring guard: real storage is exclusive/generation-guarded; UI fetches full Office data and
  // carries the reviewed mutation generation instead of passing its partial `existing` object.
  {
    const storage = fs.readFileSync(path.join(__dirname, "..", "storage.js"), "utf8");
    const sync = fs.readFileSync(path.join(__dirname, "..", "sync.js"), "utf8");
    const screen = fs.readFileSync(path.join(__dirname, "..", "screens", "Measurements.js"), "utf8");
    assert(storage.includes("withExclusiveTransactionAsync"));
    assert(storage.includes("applyMeasurementResolutionInTx"));
    assert(storage.includes("COALESCE(mutation_generation, 1) = ? AND state = ?"));
    assert(sync.includes("fetchOfficeMeasurementRevision"));
    assert(sync.includes("prepareMeasurementUseOfficeReview"));
    assert(screen.includes("mutationGeneration"));
    assert(screen.includes("wdStoreRef.current.seal()"));
    assert(!screen.includes("resolveMeasurementConflictUseOffice(existing.id, scope, existing)"));
  }

  console.log("measurement conflict transition tests passed");
}
main().catch((e) => { console.error(e); process.exit(1); });
''',
)
replace_once(
    "mobile/package.json",
    "node src/tests/measurement_durable_merge_base.node.test.js && node src/tests/sync_status.node.test.js",
    "node src/tests/measurement_durable_merge_base.node.test.js && node src/tests/measurement_conflict_transition.node.test.js && node src/tests/sync_status.node.test.js",
)
run_expected_failure("node", "mobile/src/tests/measurement_conflict_transition.node.test.js")

# ---------------------------------------------------------------------------
# GREEN: pure reviewed-transition contract, exclusive SQLite implementation,
# full Office fetch, exact generation/state stamps in the screen, and seal-only
# autosave protection before the transaction owns draft clearing.
# ---------------------------------------------------------------------------
write(
    "mobile/src/measurementConflict.js",
    r'''"use strict";
/* Pure decision layer for atomic Field measurement Use-Office resolution. */
const K = require("./measurementCache");
const { measScopeFromBody, upsertRevision } = require("./measurementReconcile");

const RESOLVABLE_STATES = new Set(["pending", "conflict", "failed"]);
function clone(value) { return value == null ? value : JSON.parse(JSON.stringify(value)); }
function revisionIdFromClientId(clientId) {
  const value = String(clientId || "");
  return value.startsWith("measurement-update:") ? value.slice("measurement-update:".length) : null;
}
function isFullOfficeRevision(value, expectedRevisionId = null) {
  if (!value || typeof value !== "object") return false;
  const id = value.id == null ? null : String(value.id);
  if (!id || (expectedRevisionId != null && id !== String(expectedRevisionId))) return false;
  if (value.updated_at == null || value.updated_at === "") return false;
  for (const key of ["structures", "facets", "edges", "penetrations"]) {
    if (!Object.prototype.hasOwnProperty.call(value, key) || !Array.isArray(value[key])) return false;
  }
  if (!Object.prototype.hasOwnProperty.call(value, "summary")) return false;
  if (value.summary !== null && (typeof value.summary !== "object" || Array.isArray(value.summary))) return false;
  return true;
}
function buildMeasurementUseOfficeReview(mutation, scope, serverDetail) {
  if (!mutation || mutation.kind !== "measurement_update") return { ok: false, reason: "not_measurement_update" };
  if (!RESOLVABLE_STATES.has(mutation.state)) return { ok: false, reason: "mutation_not_resolvable" };
  const revisionId = revisionIdFromClientId(mutation.client_id);
  if (!revisionId) return { ok: false, reason: "revision_missing" };
  const generation = Number(mutation.mutation_generation == null ? 1 : mutation.mutation_generation);
  if (!Number.isFinite(generation) || generation < 1) return { ok: false, reason: "generation_invalid" };
  if (!isFullOfficeRevision(serverDetail, revisionId)) return { ok: false, reason: "office_revision_incomplete" };
  let listKey;
  try {
    listKey = K.scopeKey(scope);
    const mutationScope = measScopeFromBody(mutation.body);
    if (!mutationScope || K.scopeKey(mutationScope) !== listKey) return { ok: false, reason: "scope_mismatch" };
  } catch (e) {
    return { ok: false, reason: "scope_missing" };
  }
  return {
    ok: true,
    reviewed: {
      clientId: String(mutation.client_id), revisionId,
      mutationGeneration: generation, expectedState: mutation.state,
      detailKey: K.detailKey(revisionId), draftKey: K.draftKey(scope),
      workingKey: K.workingKey(scope), listKey,
      serverDetail: clone(serverDetail),
    },
  };
}
function stale(reason) {
  const error = new Error(reason);
  error.__stale = reason;
  throw error;
}
function validateLiveMutation(reviewed, live) {
  if (!live) stale("mutation_missing");
  if (String(live.client_id || "") !== reviewed.clientId) stale("mutation_client_changed");
  if (live.kind !== "measurement_update") stale("mutation_kind_changed");
  if (revisionIdFromClientId(live.client_id) !== reviewed.revisionId) stale("mutation_revision_changed");
  if (Number(live.mutation_generation == null ? 1 : live.mutation_generation) !== Number(reviewed.mutationGeneration)) {
    stale("mutation_generation_changed");
  }
  if (live.state !== reviewed.expectedState) stale("mutation_state_changed");
  try {
    const liveScope = measScopeFromBody(live.body);
    if (!liveScope || K.scopeKey(liveScope) !== reviewed.listKey) stale("mutation_scope_changed");
  } catch (e) {
    if (e && e.__stale) throw e;
    stale("mutation_scope_changed");
  }
}
async function applyMeasurementResolutionInTx(tx, reviewed) {
  if (!tx || !reviewed || !isFullOfficeRevision(reviewed.serverDetail, reviewed.revisionId)) {
    throw new Error("invalid_measurement_resolution");
  }
  const live = await tx.readMutation(reviewed.clientId);
  validateLiveMutation(reviewed, live);
  const removed = await tx.deleteMutation(
    reviewed.clientId, reviewed.mutationGeneration, reviewed.expectedState,
  );
  if (removed !== 1) stale("mutation_guard_missed");

  const currentList = await tx.readCache(reviewed.listKey);
  await tx.writeCache(reviewed.detailKey, reviewed.serverDetail);
  await tx.writeCache(reviewed.draftKey, null);
  await tx.writeCache(reviewed.workingKey, null);
  await tx.writeCache(reviewed.listKey, upsertRevision(currentList, reviewed.serverDetail));
  return { action: "use_office", revisionId: reviewed.revisionId, serverDetail: clone(reviewed.serverDetail) };
}

module.exports = {
  revisionIdFromClientId,
  isFullOfficeRevision,
  buildMeasurementUseOfficeReview,
  validateLiveMutation,
  applyMeasurementResolutionInTx,
};
''',
)

replace_once(
    "mobile/src/measurementWorkingDraft.js",
    '''    // Save path: seal first (blocks every concurrent/late autosave), then clear the draft slot.\n    sealAndClear() {''',
    '''    // Conflict-resolution preflight: seal synchronously and drain any already-queued persist, but DO\n    // NOT clear. The exclusive SQLite transition owns mutation deletion + both draft clears atomically.\n    seal() {\n      sealed = true;\n      return run(async () => true);\n    },\n    // Save path: seal first (blocks every concurrent/late autosave), then clear the draft slot.\n    sealAndClear() {''',
)

replace_once(
    "mobile/src/storage.js",
    '''import { applyResolutionInTx } from "./roofSketchConflict";''',
    '''import { applyResolutionInTx } from "./roofSketchConflict";\nimport { applyMeasurementResolutionInTx } from "./measurementConflict";''',
)
append_storage = r'''

// P0-5: measurement Use-Office uses one EXCLUSIVE transaction, mirroring the proven Roof Sketch path.
// Every row is freshly read inside the transaction; the guarded delete must match the exact reviewed
// generation AND state. Any stale decision or cache write failure rolls back mutation + all cache writes.
function _measurementResolutionTxExecutor(txn, scope, now) {
  return {
    readMutation: async (clientId) => {
      const raw = await txn.getFirstAsync(
        "SELECT json, mutation_generation FROM pending_mutations WHERE client_id = ? AND (scope = ? OR scope IS NULL)",
        clientId, scope,
      );
      return raw ? { ...JSON.parse(raw.json), mutation_generation: raw.mutation_generation == null ? 1 : raw.mutation_generation } : null;
    },
    readCache: async (key) => {
      const row = await txn.getFirstAsync("SELECT json FROM cache WHERE key = ?", scopedKey(scope, key));
      return row ? JSON.parse(row.json) : null;
    },
    writeCache: async (key, value) => {
      await txn.runAsync(
        "INSERT OR REPLACE INTO cache (key, json, updated_at) VALUES (?, ?, ?)",
        scopedKey(scope, key), JSON.stringify(value), now,
      );
    },
    deleteMutation: async (clientId, generation, expectedState) => {
      const result = await txn.runAsync(
        "DELETE FROM pending_mutations WHERE client_id = ? AND COALESCE(mutation_generation, 1) = ? AND state = ? AND (scope = ? OR scope IS NULL)",
        clientId, generation, expectedState, scope,
      );
      return (result && (result.changes != null ? result.changes : result.rowsAffected)) || 0;
    },
  };
}

export async function resolveMeasurementConflictTransition(reviewed) {
  return _serialize(async () => {
    const d = await db();
    const scope = getScope();
    const now = new Date().toISOString();
    let decision = null;
    try {
      await d.withExclusiveTransactionAsync(async (txn) => {
        decision = await applyMeasurementResolutionInTx(
          _measurementResolutionTxExecutor(txn, scope, now), reviewed,
        );
      });
    } catch (e) {
      if (e && e.__stale) return { action: "stale", reason: e.__stale };
      throw e;
    }
    return decision;
  });
}
'''
storage_path = ROOT / "mobile/src/storage.js"
storage_path.write_text(storage_path.read_text(encoding="utf-8") + append_storage, encoding="utf-8")

replace_once(
    "mobile/src/sync.js",
    '''floorPendingSketchExpectedVersion, resolveSketchConflictTransition, getScope,''',
    '''floorPendingSketchExpectedVersion, resolveSketchConflictTransition, resolveMeasurementConflictTransition, getScope,''',
)
replace_once(
    "mobile/src/sync.js",
    '''import { upsertRevision, retireCreateDraft, planMeasurementWorkingAck, measScopeFromBody, isSupersededAck, rebaseWorkingDraftToRevision, measurementDocumentFromRevision } from "./measurementReconcile";''',
    '''import { upsertRevision, retireCreateDraft, planMeasurementWorkingAck, measScopeFromBody, isSupersededAck, rebaseWorkingDraftToRevision, measurementDocumentFromRevision } from "./measurementReconcile";\nimport { buildMeasurementUseOfficeReview, isFullOfficeRevision } from "./measurementConflict";''',
)
replace_once(
    "mobile/src/sync.js",
    r'''// Atomic, generation-checked USE-OFFICE conflict transition (mirrors the roof-sketch conflict transaction).
// Serialized so all actions land together: confirm the pending update still matches, remove that exact
// mutation, clear the saved draft AND the content-bearing WORKING draft (the P0 leak: otherwise load()
// re-prioritizes the local values the rep just discarded), clear/replace the optimistic detail with the
// authoritative Office revision, and update the scoped list.
export async function resolveMeasurementConflictUseOffice(revisionId, scope, serverDetail) {
  const id = `measurement-update:${String(revisionId)}`;
  await _removeMutation(id);                                   // remove the reviewed conflict mutation
  if (serverDetail && serverDetail.id != null) {
    await putCacheSerialized(measDetailKey(String(serverDetail.id)), serverDetail);  // cache authoritative Office
  }
  if (scope) {
    await mutateCache(measDraftKey(scope), () => null);        // clear saved draft
    await mutateCache(measWorkingKey(scope), () => null);      // clear content-bearing working draft (the fix)
    if (serverDetail && serverDetail.id != null) await mutateCache(measScopeKey(scope), (cur) => upsertRevision(cur, serverDetail));
  }
  _emit({ type: "queued" });
  _emit({ type: "measurement_reconciled" });
  return { action: "use_office" };
}''',
    r'''// Fetch the full authoritative revision WITHOUT mutating caches before the atomic Use-Office transition.
export async function fetchOfficeMeasurementRevision(revisionId) {
  try {
    const response = await api.get(`/mobile/measurements/${String(revisionId)}`);
    const detail = response && response.data;
    if (!isFullOfficeRevision(detail, revisionId)) return { ok: false, reason: "office_revision_incomplete" };
    return { ok: true, detail };
  } catch (e) {
    return { ok: false, reason: "office_fetch_failed" };
  }
}

// Freeze the exact mutation generation/state the rep reviewed. A newer save or sync state transition
// between rendering and tapping Use Office returns stale before storage is touched.
export async function prepareMeasurementUseOfficeReview(revisionId, scope, serverDetail, observed = null) {
  const mutation = await currentMeasurementMutation(revisionId);
  if (!mutation) return { ok: false, reason: "mutation_missing" };
  if (observed) {
    const generation = Number(mutation.mutation_generation == null ? 1 : mutation.mutation_generation);
    if (String(mutation.client_id || "") !== String(observed.clientId || "")
        || generation !== Number(observed.mutationGeneration)
        || mutation.state !== observed.expectedState) {
      return { ok: false, reason: "review_stale" };
    }
  }
  return buildMeasurementUseOfficeReview(mutation, scope, serverDetail);
}

// Apply the reviewed choice as ONE exclusive, generation-checked SQLite transaction.
export async function resolveMeasurementConflictUseOffice(reviewed) {
  const decision = await resolveMeasurementConflictTransition(reviewed);
  _emit({ type: "queued" });
  if (decision.action === "use_office") _emit({ type: "measurement_reconciled" });
  return decision;
}''',
)

replace_once(
    "mobile/src/screens/Measurements.js",
    '''queueMutation, isSyncing, syncNow, currentMeasurementMutation, currentMeasurementCreate, discardMeasurementUpdate, rebaseMeasurementUpdate, resolveMeasurementConflictUseOffice, onSyncChange, removeMutation, refreshLead, registerActiveLead''',
    '''queueMutation, isSyncing, syncNow, currentMeasurementMutation, currentMeasurementCreate, discardMeasurementUpdate, rebaseMeasurementUpdate, fetchOfficeMeasurementRevision, prepareMeasurementUseOfficeReview, resolveMeasurementConflictUseOffice, onSyncChange, removeMutation, refreshLead, registerActiveLead''',
)
replace_once(
    "mobile/src/screens/Measurements.js",
    '''function penForEdit(row) {\n  const ref = row.ref || row.id || row._k || uid();\n  return { ...row, ref, _k: row._k || row.id || ref, facet_ref: row.facet_ref || row.facet_id || "" };\n}\n''',
    '''function penForEdit(row) {\n  const ref = row.ref || row.id || row._k || uid();\n  return { ...row, ref, _k: row._k || row.id || ref, facet_ref: row.facet_ref || row.facet_id || "" };\n}\n\nfunction conflictDescriptor(mutation, revisionId, serverDetail) {\n  if (!mutation) return null;\n  return {\n    serverDetail, revisionId: String(revisionId), clientId: mutation.client_id,\n    mutationGeneration: Number(mutation.mutation_generation == null ? 1 : mutation.mutation_generation),\n    expectedState: mutation.state,\n  };\n}\n''',
)
replace_once(
    "mobile/src/screens/Measurements.js",
    '''  const autosaveTimer = useRef(null);''',
    '''  const autosaveTimer = useRef(null);\n  const resolvingOfficeRef = useRef(false);''',
)
replace_once(
    "mobile/src/screens/Measurements.js",
    '''setConflict(pend && pend.state === "conflict" && wd.base ? { serverDetail: pend.serverValue, revisionId: wd.base.id } : null);''',
    '''setConflict(pend && pend.state === "conflict" && wd.base ? conflictDescriptor(pend, wd.base.id, pend.serverValue) : null);''',
)
replace_once(
    "mobile/src/screens/Measurements.js",
    '''setConflict(view.conflict ? { serverDetail: view.serverDetail, revisionId: head.id } : null);''',
    '''setConflict(view.conflict ? conflictDescriptor(pendingUpdate, head.id, view.serverDetail) : null);''',
)
old_handlers = r'''  const onUseOffice = useCallback(async () => {
    if (!conflict) return;
    // Atomic Use-Office: seal the store so no late autosave resurrects the local draft, then run the
    // generation-checked transition that clears the saved + working drafts and adopts Office.
    await wdStoreRef.current.sealAndClear();
    await resolveMeasurementConflictUseOffice(conflict.revisionId, scope, conflict.serverDetail);
    setConflict(null);
    setWdEpoch((e) => e + 1);   // fresh, unsealed store for future edits on the adopted Office copy
    await load();
  }, [conflict, scope, load]);
'''
new_handlers = r'''  const adoptOfficeVersion = useCallback(async (revisionId, observed) => {
    if (!revisionId || resolvingOfficeRef.current) return { action: "noop" };
    resolvingOfficeRef.current = true;
    if (autosaveTimer.current) { clearTimeout(autosaveTimer.current); autosaveTimer.current = null; }
    // Seal immediately and drain any in-flight autosave. Do NOT clear here: the exclusive SQLite
    // transaction owns mutation deletion, both draft clears, detail replacement, and list replacement.
    await wdStoreRef.current.seal();
    let decision = { action: "noop" };
    try {
      const fetched = await fetchOfficeMeasurementRevision(revisionId);
      if (!fetched.ok) {
        Alert.alert("Office version unavailable", "RoofSpan could not retrieve the complete Office measurement. Your local work was preserved.");
        return { action: "preserved", reason: fetched.reason };
      }
      const prepared = await prepareMeasurementUseOfficeReview(revisionId, scope, fetched.detail, observed);
      if (!prepared.ok) {
        Alert.alert("Measurement changed again", "Your local measurement changed after this review opened. Nothing was discarded; review the latest version again.");
        return { action: "stale", reason: prepared.reason };
      }
      decision = await resolveMeasurementConflictUseOffice(prepared.reviewed);
      if (decision.action === "use_office") {
        setConflict(null);
        setFailure(null);
      } else if (decision.action === "stale") {
        Alert.alert("Measurement changed again", "A newer local edit was preserved. Review the latest version before choosing again.");
      }
      return decision;
    } catch (e) {
      Alert.alert("Could not use Office version", "The local change was preserved because the atomic update did not complete.");
      return { action: "preserved", reason: "transition_failed" };
    } finally {
      // The old store remains sealed; create a fresh store for whatever the latest persisted state contains.
      resolvingOfficeRef.current = false;
      setWdEpoch((e) => e + 1);
      await load();
    }
  }, [scope, load]);

  const onUseOffice = useCallback(async () => {
    if (!conflict) return;
    await adoptOfficeVersion(conflict.revisionId, {
      clientId: conflict.clientId,
      mutationGeneration: conflict.mutationGeneration,
      expectedState: conflict.expectedState,
    });
  }, [conflict, adoptOfficeVersion]);
'''
replace_once("mobile/src/screens/Measurements.js", old_handlers, new_handlers)
replace_once(
    "mobile/src/screens/Measurements.js",
    r'''  // Failed EXISTING revision → adopt the authoritative Office copy (drop the local update).
  const onFailedUseOffice = useCallback(async () => {
    if (!existing) return;
    await wdStoreRef.current.sealAndClear();
    await resolveMeasurementConflictUseOffice(existing.id, scope, existing);
    setFailure(null);
    setWdEpoch((e) => e + 1);
    await load();
  }, [existing, scope, load]);''',
    r'''  // Failed EXISTING revision → fetch the complete Office document, then use the same atomic,
  // exact-generation transition as a 409 conflict. The partial screen model is never authoritative.
  const onFailedUseOffice = useCallback(async () => {
    if (!existing) return;
    const mutation = await currentMeasurementMutation(existing.id);
    if (!mutation) { await load(); return; }
    await adoptOfficeVersion(existing.id, {
      clientId: mutation.client_id,
      mutationGeneration: Number(mutation.mutation_generation == null ? 1 : mutation.mutation_generation),
      expectedState: mutation.state,
    });
  }, [existing, adoptOfficeVersion, load]);''',
)

run("npm", "--prefix", "mobile", "run", "test:measurements")
run(
    "node", "-e",
    "const b=require('@babel/core'); for (const f of ['mobile/src/measurementConflict.js','mobile/src/measurementWorkingDraft.js','mobile/src/storage.js','mobile/src/sync.js','mobile/src/screens/Measurements.js']) b.transformFileSync(f,{presets:['babel-preset-expo']}); console.log('P0-5 Babel parse passed');",
)
run(
    "npx", "expo", "export", "--platform", "android", "--output-dir", "/tmp/roofspan-p0-5-export",
    cwd="mobile",
)

Path("/tmp/p0_commit_message").write_text(
    "fix: make measurement use-office atomic\n",
    encoding="utf-8",
)
