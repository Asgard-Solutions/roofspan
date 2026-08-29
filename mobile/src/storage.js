// Local device persistence (expo-sqlite). NOT authoritative — cache + durable pending queue only.
// All cache reads/writes and pending-queue reads are scoped to the active installation + user so
// one account's data can never surface for another on the same device (spec §29).
import * as SQLite from "expo-sqlite";
import { makeScope, scopedKey } from "./scope";
import queue from "./queue";

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

// ---- Pending mutation queue (survives app restart; carries its owning scope) ----
// A NEW logical enqueue bumps the supersession generation for this client_id (so a later edit's row
// replaces an in-flight older one and the older network result can be safely discarded).
export async function enqueue(m) {
  const d = await db();
  const scope = m.scope || getScope();
  const existing = await _rawRow(d, m.client_id);
  const existingRow = existing ? { mutation_generation: existing.mutation_generation } : null;
  const gen = queue.nextGeneration(existingRow);
  const stamped = { ...m, mutation_generation: gen };
  await d.runAsync(
    "INSERT OR REPLACE INTO pending_mutations (client_id, json, state, scope, mutation_generation) VALUES (?, ?, ?, ?, ?)",
    stamped.client_id, JSON.stringify(stamped), stamped.state, scope, gen
  );
  return stamped;
}

// Plain writeback preserving the row's existing generation (revive/replace/restore paths). Never bumps.
export async function saveMutation(m) {
  const d = await db();
  const scope = m.scope || getScope();
  const existing = await _rawRow(d, m.client_id);
  const gen = Number(m.mutation_generation) || (existing && Number(existing.mutation_generation)) || 1;
  const stamped = { ...m, mutation_generation: gen };
  await d.runAsync(
    "INSERT OR REPLACE INTO pending_mutations (client_id, json, state, scope, mutation_generation) VALUES (?, ?, ?, ?, ?)",
    stamped.client_id, JSON.stringify(stamped), stamped.state, scope, gen
  );
}

// Generation-guarded writeback for network results (spec §20). Applies the processed row ONLY if the
// stored row is still the same generation that was sent; otherwise the (older) result is discarded and
// the newer queued row is preserved untouched. Returns whether the result was applied.
export async function saveMutationIfCurrent(m) {
  const d = await db();
  const existing = await _rawRow(d, m.client_id);
  const storedRow = existing ? { mutation_generation: existing.mutation_generation == null ? 1 : existing.mutation_generation } : null;
  const sentRow = { mutation_generation: m.mutation_generation == null ? 1 : m.mutation_generation };
  if (!queue.shouldApplyResult(storedRow, sentRow)) return false;
  const scope = m.scope || getScope();
  await d.runAsync(
    "INSERT OR REPLACE INTO pending_mutations (client_id, json, state, scope, mutation_generation) VALUES (?, ?, ?, ?, ?)",
    m.client_id, JSON.stringify(m), m.state, scope, sentRow.mutation_generation
  );
  return true;
}

// Remove exactly ONE mutation (used by the "Remove failed photo" recovery control). Scoped so a
// device can only delete its own account's row; never touches other Leads/Jobs/Visits/Inspections.
export async function removeMutation(client_id) {
  const d = await db();
  const scope = getScope();
  await d.runAsync(
    "DELETE FROM pending_mutations WHERE client_id = ? AND (scope = ? OR scope IS NULL)",
    client_id, scope
  );
}

// Remove ALL failed mutations for the active scope (Sync Center "Remove all failed"). Never touches
// pending/synced/conflict rows, and never other scopes.
export async function removeFailedMutations() {
  const d = await db();
  const scope = getScope();
  await d.runAsync(
    "DELETE FROM pending_mutations WHERE state = 'failed' AND (scope = ? OR scope IS NULL)",
    scope
  );
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

export async function getCacheMeta(name) {
  const d = await db();
  const row = await d.getFirstAsync("SELECT updated_at FROM cache WHERE key = ?", scopedKey(getScope(), name));
  return row ? { updated_at: row.updated_at } : null;
}
