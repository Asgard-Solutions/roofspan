// Local device persistence (expo-sqlite). NOT authoritative — cache + durable pending queue only.
// All cache reads/writes and pending-queue reads are scoped to the active installation + user so
// one account's data can never surface for another on the same device (spec §29).
import * as SQLite from "expo-sqlite";
import { makeScope, scopedKey } from "./scope";

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
  return _db;
}

// ---- Pending mutation queue (survives app restart; carries its owning scope) ----
export async function enqueue(m) {
  const d = await db();
  const scope = m.scope || getScope();
  await d.runAsync(
    "INSERT OR REPLACE INTO pending_mutations (client_id, json, state, scope) VALUES (?, ?, ?, ?)",
    m.client_id, JSON.stringify(m), m.state, scope
  );
}

export async function saveMutation(m) { return enqueue(m); }

// Pending (not-yet-synced) mutations for the ACTIVE scope only.
export async function loadPending() {
  const d = await db();
  const scope = getScope();
  const rows = await d.getAllAsync(
    "SELECT json FROM pending_mutations WHERE state != 'synced' AND (scope = ? OR scope IS NULL) ORDER BY rowid ASC",
    scope
  );
  return rows.map((r) => JSON.parse(r.json));
}

// All mutations (any state) for the ACTIVE scope — used by the sync-status UI.
export async function loadAllMutations() {
  const d = await db();
  const scope = getScope();
  const rows = await d.getAllAsync(
    "SELECT json FROM pending_mutations WHERE (scope = ? OR scope IS NULL) ORDER BY rowid ASC",
    scope
  );
  return rows.map((r) => JSON.parse(r.json));
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
