// Wires the pure queue core to device storage + network. Server acknowledgement is the ONLY thing
// that flips a mutation to 'synced'. Pending data is never deleted until acknowledged.
// Auto-sync fires on: connectivity return, app foreground, dashboard load, manual "Sync Now", and
// whenever a new mutation is queued. Concurrent runs are prevented (single in-flight guard).
import NetInfo from "@react-native-community/netinfo";
import { AppState } from "react-native";
import queue from "./queue";
import { send } from "./api";
import { enqueue, saveMutation, saveMutationIfCurrent, markCleanIfNoPending, loadPending, loadAllMutations, putCache, getCache, getScope, removeMutation as _removeMutation, removeFailedMutations as _removeFailed } from "./storage";
import { applySketchAck } from "./roofSketchAck";
import { sketchDraftKey, sketchDetailKey } from "./sketchCache";

const LAST_SYNC = "last_sync_at";
const _listeners = new Set();

export function onSyncChange(cb) { _listeners.add(cb); return () => _listeners.delete(cb); }
function _emit(evt) { for (const cb of _listeners) { try { cb(evt); } catch (e) {} } }

// Create + durably persist a field mutation (tagged with the active scope), then attempt sync.
export async function queueMutation(spec) {
  const m = queue.makeMutation({ ...spec, scope: getScope() });
  const stored = await enqueue(m);          // durable stamped generation (spec §A10)
  _emit({ type: "queued" });
  _resetBackoff();
  runSync().catch(() => {});
  return stored;
}

let _running = false;
let _rerunRequested = false;                 // a mutation queued during an active run requests one more pass (§A3)

// --- Gentle auto-retry with backoff -----------------------------------------
// While transient work remains (pending items, or failed PHOTOS that are safe to retry), we re-run
// sync on an increasing delay so reps rarely need to tap Retry. Backoff resets on success and on
// fresh triggers (reconnect, foreground, new mutation, manual Sync). Permanent failures (missing
// file, unsupported/too-large) are never auto-retried — they wait for user action.
const RETRY_BACKOFF_MS = [15000, 30000, 60000, 120000, 300000]; // 15s → 5m, capped
const MAX_AUTO_PHOTO_ATTEMPTS = 6;
let _retryTimer = null;
let _backoffStep = 0;

function _clearRetryTimer() { if (_retryTimer) { clearTimeout(_retryTimer); _retryTimer = null; } }
function _resetBackoff() { _clearRetryTimer(); _backoffStep = 0; }
function _scheduleRetry() {
  _clearRetryTimer();
  const delay = RETRY_BACKOFF_MS[Math.min(_backoffStep, RETRY_BACKOFF_MS.length - 1)];
  _backoffStep += 1;
  _retryTimer = setTimeout(() => { _retryTimer = null; runSync().catch(() => {}); }, delay);
}

// Bring retryable (non-permanent) failed photos back to pending so a background pass can retry them.
async function _reviveRetryablePhotos() {
  const all = await loadAllMutations();
  for (const m of all) {
    if (m.state === "failed" && !queue.isPermanentFailure(m) && (m.attempts || 0) < MAX_AUTO_PHOTO_ATTEMPTS) {
      await saveMutation({ ...m, state: "pending", error: null, errorCode: null });
    }
  }
}

export async function runSync() {
  if (_running) { _rerunRequested = true; return; }   // never concurrent; remember another pass is needed (§A3)
  _running = true;
  _emit({ type: "sync_start" });
  try {
    const net = await NetInfo.fetch();
    if (net && net.isConnected === false) {         // offline; pending items stay safely stored
      if ((await loadPending()).length > 0) _scheduleRetry();
      return;
    }
    await _reviveRetryablePhotos();                 // let transiently-failed photos rejoin the queue
    const pending = await loadPending();            // active scope only
    if (pending.length > 0) {
      const processed = await queue.processQueue(pending, send);
      // Generation-guarded writeback: a result is applied only if its row wasn't superseded by a newer
      // edit while it was in flight (spec §A6/§A7). Superseded/removed rows are preserved untouched.
      for (const m of processed) await saveMutationIfCurrent(m);
      await _reconcileSketchAcks(processed);
    }
    // Decide completion from AUTHORITATIVE CURRENT storage, NOT the stale processed[] (spec §A2/§A5).
    // A superseded newer mutation (e.g. B replacing an acknowledged A) must keep the queue non-synced.
    const all = await loadAllMutations();
    const pendingLeft = all.some((m) => m.state === "pending");
    const retryablePhotoLeft = all.some(
      (m) => m.state === "failed" && !queue.isPermanentFailure(m) && (m.attempts || 0) < MAX_AUTO_PHOTO_ATTEMPTS
    );
    if (pendingLeft || retryablePhotoLeft) _scheduleRetry();
    else { _resetBackoff(); await _markSynced(); }  // last_sync_at only when no current work remains
  } finally {
    _running = false;
    _emit({ type: "sync_end" });
    if (_rerunRequested) { _rerunRequested = false; runSync().catch(() => {}); }  // superseded B sends automatically (§A4)
  }
}

// Atomic clean-marker: only advances last_sync_at if no pending work exists at write time (spec §0).
async function _markSynced() { return markCleanIfNoPending(LAST_SYNC, new Date().toISOString()); }

// B3B1: generation-safe application of successful sketch acknowledgements. Matched generation retires
// its draft + caches the server sketch; a superseded newer draft (B) is preserved and only its CAS
// base/expected_version is advanced (B stays pending for the existing rerun). Never resurrects A.
async function _reconcileSketchAcks(processed) {
  for (const m of processed) {
    if (m.kind !== "measurement_sketch_update" || m.state !== "synced" || !m.serverValue) continue;
    const [, revisionId, structureId] = String(m.client_id).split(":");
    const draftKey = sketchDraftKey(revisionId, structureId);
    const draft = await getCache(draftKey);
    const d = applySketchAck({ draft, ackGeneration: m.local_edit_generation, serverValue: m.serverValue });
    if (d.cacheServer) await putCache(sketchDetailKey(revisionId, structureId), { data: d.cacheServer, stale: false, cachedAt: new Date().toISOString() });
    if (d.retireDraft) await putCache(draftKey, null);
    else if (d.nextDraft) await putCache(draftKey, d.nextDraft);
    if (d.requeue) {
      const cur = (await loadAllMutations()).find((x) => x.client_id === m.client_id && x.state === "pending");
      if (cur) await saveMutation({ ...cur, body: { ...(cur.body || {}), expected_version: d.requeue.expected_version } });
    }
  }
}
export async function lastSyncAt() { return getCache(LAST_SYNC); }
export async function syncNow() { _resetBackoff(); return runSync(); }

// Recovery control: remove a single failed mutation (e.g. a photo whose local file is gone). Only the
// selected item is removed; all other offline work is preserved. Then refresh listeners.
export async function removeMutation(client_id) {
  const all = await loadAllMutations();
  const removed = all.find((x) => x.client_id === client_id) || null;
  await _removeMutation(client_id);
  _emit({ type: "queued" });
  return removed;
}

// Bulk recovery: remove every failed mutation for the active scope in one action. Pending/synced/
// conflict work and other scopes are untouched. Returns the removed rows so the UI can offer Undo.
export async function removeAllFailed() {
  const all = await loadAllMutations();
  const removed = all.filter((x) => x.state === "failed");
  await _removeFailed();
  _emit({ type: "queued" });
  return removed;
}

// Bulk recovery: remove every stuck item (pending OR failed) for the active scope. Use when items
// refuse to sync and the rep wants a clean slate. Conflicts/synced and other scopes are untouched.
export async function removeAllStuck() {
  const all = await loadAllMutations();
  const removed = all.filter((x) => x.state === "pending" || x.state === "failed");
  for (const m of removed) await _removeMutation(m.client_id);
  _emit({ type: "queued" });
  return removed;
}

// Undo support: re-insert previously removed mutation rows exactly as they were.
export async function restoreMutations(list) {
  for (const m of (list || [])) await saveMutation(m);
  if (list && list.length) _emit({ type: "queued" });
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
  const unsubNet = NetInfo.addEventListener((state) => { if (state.isConnected) { _resetBackoff(); runSync().catch(() => {}); } });
  const appSub = AppState.addEventListener("change", (s) => { if (s === "active") { _resetBackoff(); runSync().catch(() => {}); } });
  runSync().catch(() => {});
  return () => {
    _clearRetryTimer();
    try { unsubNet && unsubNet(); } catch (e) {}
    try { appSub && appSub.remove && appSub.remove(); } catch (e) {}
  };
}
