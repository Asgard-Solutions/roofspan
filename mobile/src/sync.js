// Wires the pure queue core to device storage + network. Server acknowledgement is the ONLY thing
// that flips a mutation to 'synced'. Pending data is never deleted until acknowledged.
// Auto-sync fires on: connectivity return, app foreground, dashboard load, manual "Sync Now", and
// whenever a new mutation is queued. Concurrent runs are prevented (single in-flight guard).
import NetInfo from "@react-native-community/netinfo";
import { AppState } from "react-native";
import queue from "./queue";
import { send } from "./api";
import { enqueue, saveMutation, saveMutationIfCurrent, markCleanIfNoPending, loadPending, loadAllMutations, putCache, getCache, mutateCache, listCacheNames, floorPendingSketchExpectedVersion, resolveSketchConflictTransition, getScope, removeMutation as _removeMutation, removeFailedMutations as _removeFailed } from "./storage";
import { applySketchAck } from "./roofSketchAck";
import { reconcilePropertyDetail, reconcileCanvassFeatures, propertyIdForMutation, resolveConflictPlan, mergeConflictResolution } from "./fieldReconcile";
import { noteVersion as noteCasFloor } from "./roofSketchCasFloor";
import { conflictReview, buildReviewedContext } from "./roofSketchConflict";
import { sketchDraftKey, sketchDetailKey, sketchUpdateMutationId } from "./sketchCache";

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
      await _reconcileFieldAcks(processed);
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

// B3B1 (atomic): generation-safe application of successful sketch acknowledgements. All three writes are
// concurrency-safe against a newer local edit (C) landing mid-reconciliation:
//  a. the acknowledged sketch is cached in the NORMAL raw shape (the same shape read-through/GET store),
//  b. the draft is retired/preserved ATOMICALLY via mutateCache — the decision runs against the FRESHLY
//     re-read draft inside the serialized boundary (shared with the editor's putCacheSerialized draft
//     write), so a concurrent newer generation C is preserved (never deleted, never clobbered by A),
//  c. the still-pending row's expected_version is floored DURABLY on the live stored row (never a stale
//     snapshot), so B->C supersession keeps C's document/generation while raising its CAS floor,
//  d. the authoritative version is recorded in the shared CAS floor for the open screen's live staging.
async function _reconcileSketchAcks(processed) {
  for (const m of processed) {
    if (m.kind !== "measurement_sketch_update" || m.state !== "synced" || !m.serverValue) continue;
    const [, revisionId, structureId] = String(m.client_id).split(":");
    const serverVersion = Number(m.serverValue.document_version) || 0;
    // a. raw authoritative sketch cache (NO { data, stale, cachedAt } read-through envelope)
    await putCache(sketchDetailKey(revisionId, structureId), m.serverValue);
    // b. atomic draft acknowledgement decided against the current (possibly newer) draft
    await mutateCache(sketchDraftKey(revisionId, structureId), (cur) => {
      const d = applySketchAck({ draft: cur, ackGeneration: m.local_edit_generation, serverValue: m.serverValue });
      if (d.retireDraft) return null;      // matched: retire exactly the acked generation
      if (d.nextDraft) return d.nextDraft; // superseded: preserve newer draft, advance only its CAS base
      return cur;
    });
    // c. durable, generation-safe rebase of the still-pending row (no stale read/write retry loop)
    await floorPendingSketchExpectedVersion(m.client_id, serverVersion);
    // d. live coordinator floor (in-memory convenience; durable storage above remains authoritative)
    noteCasFloor(revisionId, structureId, serverVersion);
  }
}

// Field convergence: after a Property/Visit/DNK/Lead mutation is ACKNOWLEDGED, apply the authoritative
// server state into BOTH the Property detail cache and every cached canvass/Map Property list, so no
// cache disagrees with Postgres. Optimistic local values are not permanently authoritative. Only synced
// rows are reconciled — pending/failed/conflict work is left untouched (no data loss).
async function _reconcileFieldAcks(processed) {
  const KINDS = new Set(["visit", "property_patch", "lead_create"]);
  for (const m of processed) {
    if (m.state !== "synced" || !KINDS.has(m.kind)) continue;
    const sv = m.serverValue || null;
    const propertyId = propertyIdForMutation(m);
    if (!propertyId) continue;
    // 1. Property/Visit detail cache — authoritative server state back into the saved copy.
    await mutateCache(`property:${propertyId}`, (cur) => reconcilePropertyDetail(m.kind, sv, cur));
    // 2. Map/canvass caches — patch the matching feature in any cached section Property list.
    const names = await listCacheNames("section:");
    for (const name of names) {
      if (!name.endsWith(":props")) continue;
      await mutateCache(name, (cur) => reconcileCanvassFeatures(m.kind, sv, propertyId, cur));
    }
  }
}
// B3C-style Property conflict surfacing: the durable Property/Visit/DNK mutation for ONE property that
// is currently in `conflict` state (or null). Drives the Use-Server / Keep-Local banner on Property.js.
export async function conflictMutationForProperty(propertyId) {
  const all = await loadAllMutations();
  return all.find((m) =>
    m.state === "conflict"
    && (m.kind === "visit" || m.kind === "property_patch" || m.kind === "lead_create")
    && propertyIdForMutation(m) === String(propertyId)
  ) || null;
}

// Resolve a Property conflict per the rep's choice (never loses work without an explicit choice):
//   "use_server" -> drop the local mutation and adopt the server snapshot into detail + canvass caches
//   "keep_local" -> re-queue the same local body and re-attempt sync
export async function resolveFieldConflict(client_id, choice) {
  const all = await loadAllMutations();
  const m = all.find((x) => x.client_id === client_id);
  if (!m) return { action: "noop" };
  const plan = resolveConflictPlan(m, choice);
  if (plan.action === "use_server") {
    if (plan.propertyId && plan.serverValue) {
      await mutateCache(`property:${plan.propertyId}`, (cur) => reconcilePropertyDetail("property_patch", plan.serverValue, cur));
      const names = await listCacheNames("section:");
      for (const name of names) {
        if (name.endsWith(":props")) await mutateCache(name, (cur) => reconcileCanvassFeatures("property_patch", plan.serverValue, plan.propertyId, cur));
      }
    }
    await _removeMutation(plan.removeClientId);
    _emit({ type: "queued" });
  } else if (plan.action === "keep_local") {
    await saveMutation(plan.requeue);
    _emit({ type: "queued" });
    runSync().catch(() => {});
  }
  return plan;
}

// Diff-aware per-field merge: adopt the server base into caches, drop the conflicted mutation, then
// re-queue ONLY the fields the rep chose to keep (with the server's fresh concurrency token).
export async function resolveFieldConflictMerge(client_id, choices) {
  const all = await loadAllMutations();
  const m = all.find((x) => x.client_id === client_id);
  if (!m) return { action: "noop" };
  const plan = mergeConflictResolution(m, choices);
  if (plan.action !== "merge") return plan;
  if (plan.propertyId && plan.adoptServer) {
    await mutateCache(`property:${plan.propertyId}`, (cur) => reconcilePropertyDetail("property_patch", plan.adoptServer, cur));
    const names = await listCacheNames("section:");
    for (const name of names) {
      if (name.endsWith(":props")) await mutateCache(name, (cur) => reconcileCanvassFeatures("property_patch", plan.adoptServer, plan.propertyId, cur));
    }
  }
  await _removeMutation(plan.removeClientId);
  if (plan.requeue) {
    await mutateCache(`property:${plan.propertyId}`, (cur) => ({ ...(cur || {}), ...plan.optimistic }));
    await queueMutation(plan.requeue);
  } else {
    _emit({ type: "queued" });
  }
  return plan;
}

export async function lastSyncAt() { return getCache(LAST_SYNC); }
export async function syncNow() { _resetBackoff(); return runSync(); }

// B3B2: whether the sync engine is actively processing right now (drives the "Synchronizing…" status).
export function isSyncing() { return _running; }

// B3B2: the durable mutation for exactly ONE structure's Roof Sketch (deterministic client_id). Returns
// null when there is no pending/failed/conflict/synced row for this structure. Never the global queue.
export async function currentSketchMutation(revisionId, structureId) {
  const id = sketchUpdateMutationId(revisionId, structureId);
  const all = await loadAllMutations();
  return all.find((x) => x.client_id === id) || null;
}

// B3C: the CONFLICT (409) Roof Sketch mutation for exactly ONE structure, or null. Never the global queue.
export async function conflictSketchMutation(revisionId, structureId) {
  const id = sketchUpdateMutationId(revisionId, structureId);
  const all = await loadAllMutations();
  return all.find((x) => x.client_id === id && x.state === "conflict") || null;
}

// B3C: Base / Your Draft / Office Version review payload for the current sketch conflict (or null).
export async function sketchConflictReview(revisionId, structureId) {
  const m = await conflictSketchMutation(revisionId, structureId);
  if (!m) return null;
  const draft = await getCache(sketchDraftKey(revisionId, structureId));
  return { mutation: m, ...conflictReview(m, draft) };
}

// B3C — resolve a Roof Sketch conflict by adopting the authoritative OFFICE version (local unsynced work
// is intentionally discarded). The verify+apply is ONE atomic generation-checked storage transition
// (storage.resolveSketchConflictTransition): if durable local work advanced beyond the reviewed conflict
// generation, or a newer queue row landed, the transition is `stale` and NOTHING is changed. Returns the
// decision (with `.editor` for the open screen to adopt Office).
export async function resolveSketchConflictUseOffice(revisionId, structureId) {
  const m = await conflictSketchMutation(revisionId, structureId);
  if (!m) return { action: "noop" };
  const draft = await getCache(sketchDraftKey(revisionId, structureId));
  const reviewed = buildReviewedContext(m, draft, {
    draftKey: sketchDraftKey(revisionId, structureId), detailKey: sketchDetailKey(revisionId, structureId),
  });
  const decision = await resolveSketchConflictTransition("use_office", reviewed);
  _emit({ type: "queued" });
  if (decision.action !== "use_office") return decision;   // stale/noop -> nothing changed
  noteCasFloor(revisionId, structureId, decision.casFloorVersion);
  return decision;
}

// B3C — resolve a Roof Sketch conflict by KEEPING the LOCAL draft as the desired next version, rebased
// onto the Office base/version. The draft rebase AND the exact conflict->pending queue transition succeed
// or fail together from the same freshly-read state (storage.resolveSketchConflictTransition). Never
// reports Synced before Office acknowledges; sync is triggered only AFTER a successful transition.
export async function resolveSketchConflictKeepLocal(revisionId, structureId) {
  const m = await conflictSketchMutation(revisionId, structureId);
  if (!m) return { action: "noop" };
  const draft = await getCache(sketchDraftKey(revisionId, structureId));
  const reviewed = buildReviewedContext(m, draft, {
    draftKey: sketchDraftKey(revisionId, structureId), detailKey: sketchDetailKey(revisionId, structureId),
  });
  const decision = await resolveSketchConflictTransition("keep_local", reviewed);
  if (decision.action !== "keep_local") { _emit({ type: "queued" }); return decision; }
  noteCasFloor(revisionId, structureId, decision.casFloorVersion);
  _emit({ type: "queued" });
  runSync().catch(() => {});   // re-attempt sync only after the durable transition succeeded
  return decision;
}

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
