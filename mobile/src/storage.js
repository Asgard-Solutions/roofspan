// Local device persistence (expo-sqlite). NOT authoritative — cache + durable pending queue only.
import * as SQLite from "expo-sqlite";

let _db = null;

async function db() {
  if (_db) return _db;
  _db = await SQLite.openDatabaseAsync("roofspan.db");
  await _db.execAsync(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS pending_mutations (client_id TEXT PRIMARY KEY, json TEXT NOT NULL, state TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, json TEXT NOT NULL, updated_at TEXT);
  `);
  return _db;
}

// ---- Pending mutation queue (survives app restart) ----
export async function enqueue(m) {
  const d = await db();
  await d.runAsync("INSERT OR REPLACE INTO pending_mutations (client_id, json, state) VALUES (?, ?, ?)", m.client_id, JSON.stringify(m), m.state);
}

export async function saveMutation(m) {
  return enqueue(m);
}

export async function loadPending() {
  const d = await db();
  const rows = await d.getAllAsync("SELECT json FROM pending_mutations WHERE state != 'synced' ORDER BY rowid ASC");
  return rows.map((r) => JSON.parse(r.json));
}

export async function loadAllMutations() {
  const d = await db();
  const rows = await d.getAllAsync("SELECT json FROM pending_mutations ORDER BY rowid ASC");
  return rows.map((r) => JSON.parse(r.json));
}

export async function purgeSynced() {
  const d = await db();
  await d.runAsync("DELETE FROM pending_mutations WHERE state = 'synced'");
}

// ---- Read-through cache for lists (server wins) ----
export async function putCache(key, value) {
  const d = await db();
  await d.runAsync("INSERT OR REPLACE INTO cache (key, json, updated_at) VALUES (?, ?, ?)", key, JSON.stringify(value), new Date().toISOString());
}

export async function getCache(key) {
  const d = await db();
  const row = await d.getFirstAsync("SELECT json FROM cache WHERE key = ?", key);
  return row ? JSON.parse(row.json) : null;
}
