// Wires the pure queue core to device storage + network. Server acknowledgement is the ONLY thing
// that flips a mutation to 'synced'. Pending data is never deleted until acknowledged.
// Auto-sync fires on: connectivity return, app foreground, dashboard load, manual "Sync Now", and
// whenever a new mutation is queued. Concurrent runs are prevented (single in-flight guard).
import NetInfo from "@react-native-community/netinfo";
import { AppState } from "react-native";
import queue from "./queue";
import { send } from "./api";
import { enqueue, saveMutation, loadPending, loadAllMutations, putCache, getCache, getScope, removeMutation as _removeMutation } from "./storage";

const LAST_SYNC = "last_sync_at";
const _listeners = new Set();

export function onSyncChange(cb) { _listeners.add(cb); return () => _listeners.delete(cb); }
function _emit(evt) { for (const cb of _listeners) { try { cb(evt); } catch (e) {} } }

// Create + durably persist a field mutation (tagged with the active scope), then attempt sync.
export async function queueMutation(spec) {
  const m = queue.makeMutation({ ...spec, scope: getScope() });
  await enqueue(m);
  _emit({ type: "queued" });
  runSync().catch(() => {});
  return m;
}

let _running = false;

export async function runSync() {
  if (_running) return;              // never run two syncs at once (no duplicate submissions)
  _running = true;
  _emit({ type: "sync_start" });
  try {
    const net = await NetInfo.fetch();
    if (net && net.isConnected === false) return; // offline; pending items stay safely stored
    const pending = await loadPending();           // active scope only
    if (pending.length === 0) { await _markSynced(); return; }
    const processed = await queue.processQueue(pending, send);
    for (const m of processed) await saveMutation(m); // persist synced/conflict/failed/pending
    const stillPending = processed.some((m) => m.state === "pending");
    if (!stillPending) await _markSynced();
  } finally {
    _running = false;
    _emit({ type: "sync_end" });
  }
}

async function _markSynced() { await putCache(LAST_SYNC, new Date().toISOString()); }
export async function lastSyncAt() { return getCache(LAST_SYNC); }
export async function syncNow() { return runSync(); }

// Recovery control: remove a single failed mutation (e.g. a photo whose local file is gone). Only the
// selected item is removed; all other offline work is preserved. Then refresh listeners.
export async function removeMutation(client_id) {
  await _removeMutation(client_id);
  _emit({ type: "queued" });
}

// Recovery control: swap the local file on an existing (failed/pending) photo mutation WITHOUT losing
// its category/note/record or its idempotency key, then re-queue for upload.
export async function replacePhoto(client_id, photo) {
  const all = await loadAllMutations();
  const m = all.find((x) => x.client_id === client_id);
  if (!m) return null;
  const updated = { ...m, photo, state: "pending", error: null, errorCode: null, attempts: 0 };
  await saveMutation(updated);
  _emit({ type: "queued" });
  runSync().catch(() => {});
  return updated;
}

// Simple salesperson-facing status derived from the durable queue.
export async function pendingSummary() {
  const all = await loadAllMutations();
  const by = { pending: 0, failed: 0, conflict: 0, synced: 0 };
  for (const m of all) by[m.state] = (by[m.state] || 0) + 1;
  const last = await getCache(LAST_SYNC);
  const waiting = by.pending + by.failed;
  let label = "All changes synced";
  if (by.conflict > 0) label = `${by.conflict} sync issue${by.conflict > 1 ? "s" : ""} to review`;
  else if (_running) label = "Synchronizing…";
  else if (waiting > 0) label = `${waiting} change${waiting > 1 ? "s" : ""} waiting to sync`;
  return { items: all, counts: by, waiting, lastSyncAt: last, label, syncing: _running };
}

// Auto-sync triggers. A device having internet does NOT guarantee Office is reachable, so a failed
// attempt simply leaves work pending (the queue never drops it) and we retry on the next trigger.
export function startAutoSync() {
  const unsubNet = NetInfo.addEventListener((state) => { if (state.isConnected) runSync().catch(() => {}); });
  const appSub = AppState.addEventListener("change", (s) => { if (s === "active") runSync().catch(() => {}); });
  runSync().catch(() => {});
  return () => {
    try { unsubNet && unsubNet(); } catch (e) {}
    try { appSub && appSub.remove && appSub.remove(); } catch (e) {}
  };
}
