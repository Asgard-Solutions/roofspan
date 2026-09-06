"use strict";
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
    const listItem = list.find((x) => x.id === "R1");
    assert.strictEqual(listItem.total_area_sqft, 1800);
    assert.strictEqual(listItem.total_squares, 18);
    assert.strictEqual(listItem.notes, undefined, "list cache is a canonical list item, not stale merged detail");
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
