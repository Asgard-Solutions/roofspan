// Local device persistence (expo-sqlite). NOT authoritative — cache + durable pending queue only.
// All cache reads/writes and pending-queue reads are scoped to the active installation + user so
// one account's data can never surface for another on the same device (spec §29).
import * as SQLite from "expo-sqlite";
import { makeScope, scopedKey } from "./scope";
import queue from "./queue";
import { planExpectedVersionFloor, reconcileDraftWrite } from "./roofSketchAck";
import { applyResolutionInTx } from "./roofSketchConflict";

let _db = null;
let _inst = "none";
let _user = "anon";

export function setInstallationScope(id) { _inst = id || "none"; }
export function setUserScope(id) { _user = id || "anon"; }
export function getScope() { return makeScope(_inst === "none" ? null : _inst, _user === "anon" ? null : _user); }

async function db() {
  if (_db) return _db;
  _db = await SQLite.openDatabaseAsync("roofspan.db");
  await _db.execAsync(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS pending_mutations (client_id TEXT PRIMARY KEY, json TEXT NOT NULL, state TEXT NOT NULL, scope TEXT);
    CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, json TEXT NOT NULL, updated_at TEXT);
  `);
  // Additive migration for installs created before scoping existed.
  try { await _db.execAsync("ALTER TABLE pending_mutations ADD COLUMN scope TEXT"); } catch (e) { /* already present */ }
  // Additive migration: supersession token (spec §20). Safe for existing installs — existing queued
  // work (photos/leads/jobs/visits/measurements) keeps syncing; NULL is treated as generation 1.
  try { await _db.execAsync("ALTER TABLE pending_mutations ADD COLUMN mutation_generation INTEGER"); } catch (e) { /* already present */ }
  return _db;
}

async function _rawRow(d, client_id) {
  return d.getFirstAsync("SELECT json, mutation_generation FROM pending_mutations WHERE client_id = ?", client_id);
}

// Serialize all pending-queue writes so same-client enqueues/writebacks cannot interleave at the JS
// boundary (spec §A9) — no external locking library needed.
let _writeChain = Promise.resolve();
function _serialize(fn) { const run = _writeChain.then(fn, fn); _writeChain = run.then(() => {}, () => {}); return run; }

// ---- Pending mutation queue (survives app restart; carries its owning scope) ----
// A NEW logical enqueue bumps the supersession generation ATOMICALLY via SQL UPSERT (spec §A9), so two
// overlapping same-client enqueues can never receive the same generation. Returns the durable stamped row.
export async function enqueue(m) {
  return _serialize(async () => {
    const d = await db();
    const scope = m.scope || getScope();
    await d.runAsync(
      `INSERT INTO pending_mutations (client_id, json, state, scope, mutation_generation)
       VALUES (?, ?, ?, ?, 1)
       ON CONFLICT(client_id) DO UPDATE SET
         json = excluded.json, state = excluded.state, scope = excluded.scope,
         mutation_generation = COALESCE(pending_mutations.mutation_generation, 1) + 1`,
      m.client_id, JSON.stringify(m), m.state, scope
    );
    const row = await d.getFirstAsync("SELECT mutation_generation FROM pending_mutations WHERE client_id = ?", m.client_id);
    const gen = row && row.mutation_generation != null ? row.mutation_generation : 1;
    const stamped = { ...m, mutation_generation: gen };
    await d.runAsync("UPDATE pending_mutations SET json = ? WHERE client_id = ?", JSON.stringify(stamped), m.client_id);
    return stamped;
  });
}

// Plain writeback preserving the row's existing generation (revive/replace/restore paths). Never bumps.
export async function saveMutation(m) {
  return _serialize(async () => {
    const d = await db();
    const scope = m.scope || getScope();
    const existing = await _rawRow(d, m.client_id);
    const gen = Number(m.mutation_generation) || (existing && Number(existing.mutation_generation)) || 1;
    const stamped = { ...m, mutation_generation: gen };
    await d.runAsync(
      "INSERT OR REPLACE INTO pending_mutations (client_id, json, state, scope, mutation_generation) VALUES (?, ?, ?, ?, ?)",
      stamped.client_id, JSON.stringify(stamped), stamped.state, scope, gen
    );
  });
}

// Generation-guarded writeback for network results (spec §A6/§A7). ATOMIC conditional UPDATE at the SQL
// boundary — applies the processed row ONLY if the stored row still carries the same generation that was
// sent (COALESCE handles legacy NULL as 1, §A8). It NEVER inserts a missing row, so a late result can
// never resurrect a removed mutation. Returns whether the result was applied.
export async function saveMutationIfCurrent(m) {
  return _serialize(async () => {
    const d = await db();
    const scope = m.scope || getScope();
    const gen = m.mutation_generation == null ? 1 : m.mutation_generation;
    const stamped = { ...m, mutation_generation: gen };
    const res = await d.runAsync(
      `UPDATE pending_mutations SET json = ?, state = ?, scope = ?, mutation_generation = ?
       WHERE client_id = ? AND COALESCE(mutation_generation, 1) = ?`,
      JSON.stringify(stamped), stamped.state, scope, gen, m.client_id, gen
    );
    return (res && (res.changes || res.rowsAffected || 0)) > 0;
  });
}

// Atomically mark the scoped queue "clean" (advance last_sync) ONLY if no pending work exists — the
// count check and the marker write run inside the SAME serialized critical section as enqueue (spec §0),
// so a mutation B enqueued concurrently can never slip between the clean check and the marker write.
export async function markCleanIfNoPending(cacheKey, value) {
  return _serialize(async () => {
    const d = await db();
    const scope = getScope();
    const row = await d.getFirstAsync(
      "SELECT COUNT(*) AS c FROM pending_mutations WHERE state = 'pending' AND (scope = ? OR scope IS NULL)",
      scope
    );
    if (row && Number(row.c) > 0) return false;   // current work exists -> do NOT advance last_sync
    await putCache(cacheKey, value);
    return true;
  });
}

// B3B1 (durable, generation-safe): floor a still-pending Roof Sketch mutation's expected_version to at
// least the acknowledged server version, operating on the CURRENT stored row INSIDE the serialization
// boundary. Preserves the row's document, local_edit_generation and mutation_generation; NEVER
// resurrects a missing row; scoped so it can only touch this account's own row. This closes B->C
// supersession without a stale read/write retry loop (the write reads the live row, not a snapshot).
export async function floorPendingSketchExpectedVersion(client_id, serverVersion) {
  return _serialize(async () => {
    const d = await db();
    const scope = getScope();
    const row = await d.getFirstAsync(
      "SELECT json FROM pending_mutations WHERE client_id = ? AND (scope = ? OR scope IS NULL)",
      client_id, scope
    );
    if (!row) return { updated: false, reason: "missing" };   // never resurrect a removed/synced row
    const m = JSON.parse(row.json);
    const plan = planExpectedVersionFloor(m, serverVersion);
    if (!plan.updated) return { updated: false, reason: m.state !== "pending" ? "not_pending" : "already_floored" };
    await d.runAsync(
      "UPDATE pending_mutations SET json = ? WHERE client_id = ? AND (scope = ? OR scope IS NULL)",
      JSON.stringify(plan.next), client_id, scope
    );
    return { updated: true, expected_version: plan.expected_version };
  });
}

// Remove exactly ONE mutation (used by the "Remove failed photo" recovery control). Scoped so a
// device can only delete its own account's row; never touches other Leads/Jobs/Visits/Inspections.
export async function removeMutation(client_id) {
  return _serialize(async () => {
    const d = await db();
    const scope = getScope();
    await d.runAsync(
      "DELETE FROM pending_mutations WHERE client_id = ? AND (scope = ? OR scope IS NULL)",
      client_id, scope
    );
  });
}

// Remove ALL failed mutations for the active scope (Sync Center "Remove all failed"). Never touches
// pending/synced/conflict rows, and never other scopes.
export async function removeFailedMutations() {
  return _serialize(async () => {
    const d = await db();
    const scope = getScope();
    await d.runAsync(
      "DELETE FROM pending_mutations WHERE state = 'failed' AND (scope = ? OR scope IS NULL)",
      scope
    );
  });
}

// Pending (not-yet-synced) mutations for the ACTIVE scope only.
export async function loadPending() {
  const d = await db();
  const scope = getScope();
  const rows = await d.getAllAsync(
    "SELECT json, mutation_generation FROM pending_mutations WHERE state != 'synced' AND (scope = ? OR scope IS NULL) ORDER BY rowid ASC",
    scope
  );
  return rows.map((r) => ({ ...JSON.parse(r.json), mutation_generation: r.mutation_generation == null ? 1 : r.mutation_generation }));
}

// All mutations (any state) for the ACTIVE scope — used by the sync-status UI.
export async function loadAllMutations() {
  const d = await db();
  const scope = getScope();
  const rows = await d.getAllAsync(
    "SELECT json, mutation_generation FROM pending_mutations WHERE (scope = ? OR scope IS NULL) ORDER BY rowid ASC",
    scope
  );
  return rows.map((r) => ({ ...JSON.parse(r.json), mutation_generation: r.mutation_generation == null ? 1 : r.mutation_generation }));
}

// Count unsynced work belonging to OTHER accounts on this device — never silently discarded (§29).
export async function countPendingOtherScopes() {
  const d = await db();
  const scope = getScope();
  const row = await d.getFirstAsync(
    "SELECT COUNT(*) AS n FROM pending_mutations WHERE state != 'synced' AND scope IS NOT NULL AND scope != ?",
    scope
  );
  return (row && row.n) || 0;
}

export async function purgeSynced() {
  const d = await db();
  await d.runAsync("DELETE FROM pending_mutations WHERE state = 'synced'");
}

// ---- Read-through cache (server wins), namespaced by the active scope ----
export async function putCache(name, value) {
  const d = await db();
  await d.runAsync(
    "INSERT OR REPLACE INTO cache (key, json, updated_at) VALUES (?, ?, ?)",
    scopedKey(getScope(), name), JSON.stringify(value), new Date().toISOString()
  );
}

export async function getCache(name) {
  const d = await db();
  const row = await d.getFirstAsync("SELECT json FROM cache WHERE key = ?", scopedKey(getScope(), name));
  return row ? JSON.parse(row.json) : null;
}

// List cached NAMES (scope stripped) whose name starts with `prefix`, for the active scope. Used to
// reconcile every canvass-section Property list that may contain a changed home.
export async function listCacheNames(prefix) {
  const d = await db();
  const scope = getScope();
  const strip = `${scope || "none::anon"}::`;
  const rows = await d.getAllAsync("SELECT key FROM cache WHERE key LIKE ?", `${strip}${prefix}%`);
  return (rows || []).map((r) => (r.key.startsWith(strip) ? r.key.slice(strip.length) : r.key));
}

// Serialized cache write — runs inside the SAME critical section (`_serialize`) as `mutateCache` and the
// pending-queue writes. Used for Roof Sketch DRAFT writes so an editor draft write (generation C) and an
// acknowledgement reconciliation can never interleave on the same scoped draft key (B3B1 atomicity).
export async function putCacheSerialized(name, value) {
  return _serialize(async () => {
    const d = await db();
    await d.runAsync(
      "INSERT OR REPLACE INTO cache (key, json, updated_at) VALUES (?, ?, ?)",
      scopedKey(getScope(), name), JSON.stringify(value), new Date().toISOString()
    );
  });
}

// Serialized read-modify-write of a single scoped cache row. The reducer `fn(current)` runs against the
// FRESHLY re-read value inside the critical section, so a concurrent editor draft write (C) that landed
// after the ack was computed is still seen here — the generation-safe reducer then preserves it rather
// than deleting/overwriting newer work. Returns the written value.
export async function mutateCache(name, fn) {
  return _serialize(async () => {
    const d = await db();
    const key = scopedKey(getScope(), name);
    const row = await d.getFirstAsync("SELECT json FROM cache WHERE key = ?", key);
    const cur = row ? JSON.parse(row.json) : null;
    const next = fn(cur);
    await d.runAsync(
      "INSERT OR REPLACE INTO cache (key, json, updated_at) VALUES (?, ?, ?)",
      key, JSON.stringify(next), new Date().toISOString()
    );
    return next;
  });
}

// B3B1 (CAS-monotonic strict draft write): the ONLY path the editor uses to persist a Roof Sketch draft.
// Runs the read-modify-write in ONE serialized critical section (shared with mutateCache/putCacheSerialized
// and the pending-queue writes) and applies the shared reconcileDraftWrite rule so that: (1) a late OLDER
// edit-generation can never clobber a newer durable draft, and (2) document_version never regresses below
// the highest known authoritative server version (the cached server sketch OR the current draft's own
// base). A storage failure PROPAGATES (durability contract); a stale-generation REJECTION is a no-op
// (not an error) because newer work is already durable. `draftKey`/`detailKey` are passed by the caller
// so this stays generic and never changes cache behavior for unrelated features.
export async function saveSketchDraftIfCurrent(draftKey, detailKey, incoming) {
  return _serialize(async () => {
    const d = await db();
    const scope = getScope();
    const draftRow = await d.getFirstAsync("SELECT json FROM cache WHERE key = ?", scopedKey(scope, draftKey));
    const existing = draftRow ? JSON.parse(draftRow.json) : null;
    const detailRow = await d.getFirstAsync("SELECT json FROM cache WHERE key = ?", scopedKey(scope, detailKey));
    const server = detailRow ? JSON.parse(detailRow.json) : null;
    // Highest known authoritative CAS version: the acknowledged server sketch AND the draft's own base
    // (which may already have been advanced to v6 by a prior ack reconciliation).
    const knownServerVersion = Math.max(
      Number(existing && existing.document_version) || 0,
      Number(server && server.document_version) || 0
    );
    const res = reconcileDraftWrite(existing, incoming, knownServerVersion, server);
    if (!res.write) return { written: false, reason: "stale_generation", draft: existing };
    await d.runAsync(
      "INSERT OR REPLACE INTO cache (key, json, updated_at) VALUES (?, ?, ?)",
      scopedKey(scope, draftKey), JSON.stringify(res.draft), new Date().toISOString()
    );
    return { written: true, draft: res.draft };
  });
}

export async function getCacheMeta(name) {
  const d = await db();
  const row = await d.getFirstAsync("SELECT updated_at FROM cache WHERE key = ?", scopedKey(getScope(), name));
  return row ? { updated_at: row.updated_at } : null;
}

// B3C (atomic + EXCLUSIVE transaction): resolve a Roof Sketch 409 conflict in ONE serialized critical
// section whose durable writes run inside an EXCLUSIVE expo-sqlite transaction. Exclusive (not the
// non-exclusive withTransactionAsync) so unrelated async cache/ack queries can NEVER be absorbed into the
// conflict transaction. The conflict row AND the durable draft are re-read FRESH inside the transaction
// via the callback's `txn` and handed to the SAME pure body the contracts use (applyResolutionInTx). If
// ANY invariant drifted, a guarded DELETE/UPDATE misses its row, or a write throws, the transaction rolls
// back and NOTHING is committed. Use Office and Keep Local are each all-or-nothing.
function _resolutionTxExecutor(txn, scope, now) {
  return {
    readConflictRow: async (clientId) => {
      const raw = await txn.getFirstAsync(
        "SELECT json, mutation_generation FROM pending_mutations WHERE client_id = ? AND (scope = ? OR scope IS NULL)", clientId, scope);
      return raw ? { ...JSON.parse(raw.json), mutation_generation: raw.mutation_generation == null ? 1 : raw.mutation_generation } : null;
    },
    readDraft: async (draftKey) => {
      const row = await txn.getFirstAsync("SELECT json FROM cache WHERE key = ?", scopedKey(scope, draftKey));
      return row ? JSON.parse(row.json) : null;
    },
    writeCache: async (key, value) => {
      await txn.runAsync("INSERT OR REPLACE INTO cache (key, json, updated_at) VALUES (?, ?, ?)", scopedKey(scope, key), JSON.stringify(value), now);
    },
    deleteConflictRow: async (clientId, queueGen) => {
      const r = await txn.runAsync(
        "DELETE FROM pending_mutations WHERE client_id = ? AND COALESCE(mutation_generation, 1) = ? AND state = 'conflict' AND (scope = ? OR scope IS NULL)",
        clientId, queueGen, scope);
      return (r && (r.changes != null ? r.changes : r.rowsAffected)) || 0;
    },
    transitionConflictToPending: async (clientId, queueGen, nextRow) => {
      const r = await txn.runAsync(
        "UPDATE pending_mutations SET json = ?, state = 'pending', mutation_generation = ? WHERE client_id = ? AND COALESCE(mutation_generation, 1) = ? AND state = 'conflict' AND (scope = ? OR scope IS NULL)",
        JSON.stringify(nextRow), nextRow.mutation_generation, clientId, queueGen, scope);
      return (r && (r.changes != null ? r.changes : r.rowsAffected)) || 0;
    },
  };
}

export async function resolveSketchConflictTransition(choice, reviewed) {
  return _serialize(async () => {
    const d = await db();
    const scope = getScope();
    const now = new Date().toISOString();
    let decision = null;
    try {
      // EXCLUSIVE all-or-nothing SQLite transaction: every read/write runs through the callback's `txn`
      // (never the outer `d`), so no unrelated query is absorbed. applyResolutionInTx throws to abort.
      await d.withExclusiveTransactionAsync(async (txn) => {
        decision = await applyResolutionInTx(_resolutionTxExecutor(txn, scope, now), choice, reviewed);
      });
    } catch (e) {
      if (e && e.__stale) return { action: "stale", reason: e.__stale };   // rolled back -> nothing changed
      throw e;   // real SQL failure: transaction rolled back; caller keeps the conflict, records nothing
    }
    return decision;   // committed
  });
}
