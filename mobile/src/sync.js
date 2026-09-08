// Wires the pure queue core to device storage + network. Server acknowledgement is the ONLY thing
// that flips a mutation to 'synced'. Pending data is never deleted until acknowledged.
// Auto-sync fires on: connectivity return, app foreground, dashboard load, manual "Sync Now", and
// whenever a new mutation is queued. Concurrent runs are prevented (single in-flight guard).
import NetInfo from "@react-native-community/netinfo";
import { AppState } from "react-native";
import queue from "./queue";
import { send } from "./api";
import { enqueue, saveMutation, saveMutationIfCurrent, markCleanIfNoPending, markConvergedIfClean, loadPending, loadAllMutations, putCache, putCacheSerialized, getCache, mutateCache, listCacheNames, floorPendingSketchExpectedVersion, resolveSketchConflictTransition, resolveMeasurementConflictTransition, getScope, removeMutation as _removeMutation, removeFailedMutations as _removeFailed, rebasePendingMeasurementIfMatch, convertSupersededCreateToUpdate } from "./storage";
import { applySketchAck } from "./roofSketchAck";
import { reconcilePropertyDetail, reconcileCanvassFeatures, propertyIdForMutation, resolveConflictPlan, mergeConflictResolution } from "./fieldReconcile";
import { noteVersion as noteCasFloor } from "./roofSketchCasFloor";
import { conflictReview, buildReviewedContext } from "./roofSketchConflict";
import { sketchDraftKey, sketchDetailKey, sketchUpdateMutationId } from "./sketchCache";
import { detailKey as measDetailKey, scopeKey as measScopeKey, draftKey as measDraftKey, workingKey as measWorkingKey } from "./measurementCache";
import { upsertRevision, retireCreateDraft, planMeasurementWorkingAck, measScopeFromBody, isSupersededAck, rebaseWorkingDraftToRevision, measurementDocumentFromRevision } from "./measurementReconcile";
import { buildMeasurementUseOfficeReview, isFullOfficeRevision } from "./measurementConflict";
import { classifyOrphanWorkingDraft, recoveryAttentionItem, parseWorkingScope, planStartupRecovery } from "./measurementRecovery";
import { createMeasurementSyncCoordinator } from "./measurementSyncCoordinator";
import { createDiagnostics } from "./syncDiagnostics";
import { countStates, deriveSyncStatus } from "./syncStatus";
import { sketchRefreshDecision } from "./sketchRefreshDecision";
import { cache } from "./cache";
import { api } from "./api";
import { setRelayEventHandler } from "./transport";

const LAST_SYNC = "last_sync_at";
// Separate, honest sync-status timestamps (spec): a push ATTEMPT vs a successful PUSH vs a successful
// PULL vs FULL convergence. Only last_fully_converged_at requires an empty-of-issues queue.
const LAST_PUSH_ATTEMPT = "last_push_attempt_at";
const LAST_PUSH_OK = "last_successful_push_at";
const LAST_PULL_OK = "last_successful_pull_at";
const LAST_CONVERGED = "last_fully_converged_at";
const DIAG_KEY = "sync_diag";           // persisted, scoped diagnostics ring + timestamps (survive restart)
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
      await putCache(LAST_PUSH_ATTEMPT, new Date().toISOString());  // a Field→Office push cycle is starting
      _diag.recordPushAttempt();
      const processed = await queue.processQueue(pending, send);
      // Generation-guarded writeback: a result is applied only if its row wasn't superseded by a newer
      // edit while it was in flight (spec §A6/§A7). Superseded/removed rows are preserved untouched.
      for (const m of processed) await saveMutationIfCurrent(m);
      for (const m of processed) _recordMutationDiag(m);
      await _reconcileSketchAcks(processed);
      await _reconcileFieldAcks(processed);
      await _reconcileMeasurementAcks(processed);
      // A successful PUSH = at least one mutation acknowledged (reached 'synced') this cycle.
      if (processed.some((m) => m.state === "synced")) {
        await putCache(LAST_PUSH_OK, new Date().toISOString());
        _diag.recordPushSuccess();
      }
      await _persistDiag();
    }
    // Decide completion from AUTHORITATIVE CURRENT storage, NOT the stale processed[] (spec §A2/§A5).
    // A superseded newer mutation (e.g. B replacing an acknowledged A) must keep the queue non-synced.
    const all = await loadAllMutations();
    const pendingLeft = all.some((m) => m.state === "pending");
    const retryablePhotoLeft = all.some(
      (m) => m.state === "failed" && !queue.isPermanentFailure(m) && (m.attempts || 0) < MAX_AUTO_PHOTO_ATTEMPTS
    );
    if (pendingLeft || retryablePhotoLeft) _scheduleRetry();
    else _resetBackoff();
    // last_fully_converged_at advances ONLY when NO pending/failed/conflict/locked mutation remains
    // (never with unresolved issues — no more "Last synced just now / 1 failed" confusion).
    await _markConverged();
  } finally {
    _running = false;
    _emit({ type: "sync_end" });
    if (_rerunRequested) { _rerunRequested = false; runSync().catch(() => {}); }  // superseded B sends automatically (§A4)
  }
}

// Atomic convergence marker: advances last_fully_converged_at ONLY if the queue holds no pending, failed,
// conflict, or locked mutation at write time (spec). Never advances while any issue remains.
async function _markConverged() { return markConvergedIfClean(LAST_CONVERGED, new Date().toISOString()); }

// Device sync diagnostics: last PULL and last PUSH (attempt vs success) tracked separately + a bounded
// per-mutation ring. Persisted to scoped SQLite so it SURVIVES the app kill/restart it diagnoses.
const _diag = createDiagnostics();
export function syncDiagnostics() { return _diag.snapshot(); }
async function _persistDiag() { try { await putCache(DIAG_KEY, _diag.snapshot()); } catch (e) { /* best effort */ } }

function _pathCategoryFor(m) {
  const k = String(m.kind || ""); const cid = String(m.client_id || "");
  if (k.startsWith("measurement") || cid.startsWith("measurement")) {
    return cid.includes("sketch") || k.includes("sketch") ? "/api/measurements/sketches" : "/api/measurements";
  }
  if (k.includes("sketch") || cid.includes("sketch")) return "/api/measurements/sketches";
  if (k.startsWith("photo")) return "/api/photos";
  if (k.startsWith("lead")) return "/api/mobile/leads";
  if (k.startsWith("visit")) return "/api/visits";
  if (k.startsWith("inspection")) return "/api/inspections";
  return "/api";
}
function _recoveryActionFor(m) {
  if (m.state === "conflict") return "conflict";
  if (m.state === "synced") return "retire";
  if (m.state === "failed") return "none";
  return null;
}
function _recordMutationDiag(m) {
  if (!m) return;
  const sv = m.serverValue || null;
  const revisionId = sv && sv.id != null ? sv.id
    : (String(m.client_id || "").startsWith("measurement-update:") ? String(m.client_id).split(":")[1] : (sv && sv.revision_id) || null);
  const serverToken = sv ? (sv.updated_at != null ? sv.updated_at : sv.document_version) : null;
  _diag.recordMutation({
    clientId: m.client_id, kind: m.kind, state: m.state,
    httpResult: m.errorCode != null ? m.errorCode : (m.state === "synced" ? "ok" : m.state),
    httpStatus: m.status != null ? m.status : (m.httpStatus != null ? m.httpStatus : null),
    relayErrorCode: m.errorCode != null ? m.errorCode : null,
    pathCategory: _pathCategoryFor(m),
    mutationGeneration: m.mutation_generation != null ? m.mutation_generation : m.local_edit_generation,
    revisionId, serverToken, cacheSource: sv ? "server_ack" : null,
    recoveryAction: _recoveryActionFor(m), error: m.error || null,
  });
}

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
    // a. raw authoritative sketch cache (NO { data, stale, cachedAt } read-through envelope). Written via
    //    the SERIALIZED cache helper so it waits its turn on the shared _serialize chain alongside the
    //    exclusive B3C conflict transaction + the draft ack below — never absorbed into / lost to it.
    await putCacheSerialized(sketchDetailKey(revisionId, structureId), m.serverValue);
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
// Measurement convergence (mirrors _reconcileSketchAcks): after a `measurement` create or a
// `measurement_update` is ACKNOWLEDGED, apply the authoritative Office revision so no cache disagrees with
// Postgres, retire the exact acknowledged local drafts, and notify the open screen immediately (no 15s
// wait). Every write runs through the SERIALIZED storage boundary shared with the editor's working-draft
// writes, so a NEWER local edit (higher generation) that landed mid-reconciliation is never deleted — its
// authoritative token is merely advanced so it re-applies cleanly.
async function _reconcileMeasurementAcks(processed) {
  const acks = processed.filter(
    (m) => (m.kind === "measurement" || m.kind === "measurement_update") && m.state === "synced" && m.serverValue && m.serverValue.id != null
  );
  if (!acks.length) return;
  // Freshly re-read the durable queue (post generation-guarded writeback) to detect supersession safely.
  const current = await loadAllMutations();
  const byId = new Map(current.map((r) => [r.client_id, r]));
  let touched = false;
  for (const m of acks) {
    const rev = m.serverValue;                 // validated: authoritative revision detail (has id + updated_at)
    const revisionId = String(rev.id);
    _coordinator.noteRevisionWatermark(revisionId, rev.updated_at);
    const stored = byId.get(m.client_id) || null;
    const superseded = isSupersededAck(stored, m);
    const measScope = measScopeFromBody(m.body);
    // a. authoritative detail cache in the RAW read-through/GET shape (serialized alongside the draft acks).
    await putCacheSerialized(measDetailKey(revisionId), rev);
    // b. scoped measurement-list cache: insert/update this revision, preserving all others.
    if (measScope) await mutateCache(measScopeKey(measScope), (cur) => upsertRevision(cur, rev));
    if (superseded) {
      // A newer local edit is still pending — NEVER retire its drafts.
      if (stored.kind === "measurement_update") {
        // Rebase the newer update onto the fresh authoritative token so it applies cleanly.
        await rebasePendingMeasurementIfMatch(m.client_id, rev.updated_at, rev);
      } else if (stored.kind === "measurement") {
        // P0 data-loss fix: a newer CREATE generation superseded this acknowledged create. Convert it into
        // an UPDATE of the just-created revision so the newer body is actually applied (an idempotent
        // create replay would otherwise silently return the original record and the second edit would be
        // lost). Draft is rebased onto the new revision and retired only after the update's OWN ack.
        const res = await convertSupersededCreateToUpdate(m.client_id, revisionId, rev.updated_at, rev);
        if (res && res.converted) {
          if (measScope) await mutateCache(measWorkingKey(measScope), (cur) => rebaseWorkingDraftToRevision(cur, { oldClientId: m.client_id, revisionId, ifMatch: rev.updated_at }));
          _rerunRequested = true;   // automatically run the converted update on the next pass
        }
      }
      touched = true;
      continue;
    }
    // c. matched: retire ONLY the local drafts tied to exactly this acknowledged mutation.
    if (measScope) {
      if (m.kind === "measurement") await mutateCache(measDraftKey(measScope), (cur) => retireCreateDraft(cur, m.client_id));
      await mutateCache(measWorkingKey(measScope), (cur) => planMeasurementWorkingAck(cur, { kind: m.kind, clientId: m.client_id, revisionId }));
    }
    touched = true;
  }
  // d. notify the open screen immediately so it adopts the authoritative revision without a poll.
  if (touched) _emit({ type: "measurement_reconciled" });
}

// ---- Central, LEAD-AWARE measurement sync (screen-independent) --------------------------------------
const _coordinator = createMeasurementSyncCoordinator();
export function registerActiveLead(scope) { return _coordinator.registerActiveLead(scope); }

// Refresh ONE lead's measurements + sketch watermarks from Office (canonical copy), coalesced by trigger.
// Uses the lightweight watermark endpoint to decide currency, then read-throughs only the stale revisions
// that have NO active local mutation (never clobbers unsynced optimistic work). Emits change events so any
// open screen reloads — synchronization no longer depends on which screen is mounted.
export async function refreshLead(scope, trigger = "manual") {
  if (!scope) return { refreshed: false };
  _coordinator.registerActiveLead(scope);
  if (!_coordinator.shouldRefresh(trigger, scope)) return { refreshed: false, skipped: true };
  let wm = null;
  try { const r = await api.get("/mobile/measurements/watermark", { params: scope }); wm = r && r.data; }
  catch (e) { return { refreshed: false, offline: true }; }   // offline → cached copy stays; retry next trigger
  _coordinator.markRefreshed(scope);
  _diag.recordPull();   // a successful Office→Field read completed for this lead
  try { await putCache(LAST_PULL_OK, new Date().toISOString()); } catch (e) { /* best effort */ }
  await _persistDiag();
  const all = await loadAllMutations();
  let changed = false;
  for (const rev of (wm && wm.revisions) || []) {
    _coordinator.noteRevisionWatermark(rev.revision_id, rev.updated_at);
    for (const sk of rev.sketches || []) _coordinator.noteSketchWatermark(rev.revision_id, sk.structure_id, sk.document_version);
    let cached = null; try { cached = await getCache(measDetailKey(rev.revision_id)); } catch (e) { /* best effort */ }
    const cachedTok = cached && cached.updated_at != null ? String(cached.updated_at) : null;
    const activeMut = all.find((m) => m.client_id === `measurement-update:${rev.revision_id}` && (m.state === "pending" || m.state === "failed" || m.state === "conflict"));
    if (!activeMut && cachedTok !== String(rev.updated_at)) {
      try { const d = await cache.measurement(rev.revision_id); if (d && d.data) changed = true; } catch (e) { /* offline */ }
    }
    for (const sk of rev.sketches || []) {
      const structureId = sk.structure_id;
      let skCached = null; try { skCached = await getCache(sketchDetailKey(rev.revision_id, structureId)); } catch (e) {}
      const localVersion = skCached && skCached.document_version != null ? Number(skCached.document_version) : null;
      const officeVersion = Number(sk.document_version) || 0;
      const hasActiveMutation = !!all.find((m) => m.client_id === sketchUpdateMutationId(rev.revision_id, structureId) && (m.state === "pending" || m.state === "failed" || m.state === "conflict"));
      let localDraft = null; try { localDraft = await getCache(sketchDraftKey(rev.revision_id, structureId)); } catch (e) {}
      const hasDraft = !!(localDraft && localDraft.document);
      const contentDiffers = hasDraft && skCached && skCached.document
        && JSON.stringify(localDraft.document) !== JSON.stringify(skCached.document);
      const decision = sketchRefreshDecision({ officeVersion, localVersion, hasDraft, hasActiveMutation, contentDiffers });
      if (decision === "pull") {
        // Office CREATED the first sketch — pull + cache so the row flips to "Edit Roof Sketch" now.
        try { const d = await cache.sketch(rev.revision_id, structureId); if (d && d.data) changed = true; } catch (e) { /* offline → retry next trigger */ }
      } else if (decision === "floor_and_pull") {
        noteCasFloor(rev.revision_id, structureId, officeVersion);   // never let a stale local CAS overwrite Office
        try { const d = await cache.sketch(rev.revision_id, structureId); if (d && d.data) changed = true; } catch (e) { /* offline */ }
        changed = true;
      } else if (decision === "review") {
        // Same version, divergent local draft, no active mutation → explicit review (editor-open resolves).
        _emit({ type: "sketch_review", revisionId: rev.revision_id, structureId, documentVersion: officeVersion });
      }
    }
  }
  if (changed) _emit({ type: "measurement_reconciled" });
  _emit({ type: "measurement_changed", scope });
  return { refreshed: true, changed };
}

export async function refreshActiveLeads(trigger = "manual") {
  for (const scope of _coordinator.activeLeads()) { try { await refreshLead(scope, trigger); } catch (e) { /* per-lead best effort */ } }
}

// Office reported a measurement/sketch changed (relay `measurement_changed`): adopt the watermark, mark the
// lead dirty, and pull the canonical copy immediately (the event carries no business document by design).
export async function handleOfficeInvalidation(evt) {
  const parsed = _coordinator.invalidate(evt);
  if (parsed && parsed.leadScope) { try { await refreshLead(parsed.leadScope, "office_invalidation"); } catch (e) {} }
  return parsed;
}

// One-time (idempotent) STARTUP RECOVERY for phones already stuck in the pre-fix bad state. Runs the same
// serialized, generation-safe reconciliation over ALREADY-STORED rows/drafts. It NEVER wipes app data and
// NEVER silently deletes unsynced work: it settles synced creates/updates whose drafts lingered, preserves
// failed/conflict work and lists it for routing, and heals orphaned working drafts only when provably safe.
let _measurementAttention = { conflicts: [], failures: [], recovered: 0, ranAt: null };
export function measurementAttention() { return _measurementAttention; }

export async function recoverMeasurementsOnStartup() {
  const summary = { recovered: 0, conflicts: [], failures: [], ranAt: new Date().toISOString() };
  let all;
  try { all = await loadAllMutations(); } catch (e) { return summary; }

  // 1) Settle every SYNCED measurement create/update whose local draft was never retired (the bad state),
  //    and collect failed/conflict rows for explicit resolution (never auto-resolved, never deleted).
  const plan = planStartupRecovery(all);
  summary.conflicts.push(...plan.conflicts);
  summary.failures.push(...plan.failures);
  for (const m of plan.settle) {
    // Use serverValue, else locate the authoritative revision by server_id (read-through; skip if offline).
    let rev = (m.serverValue && m.serverValue.id) ? m.serverValue : null;
    if (!rev && m.server_id) {
      try { const r = await cache.measurement(m.server_id); if (r && r.data && r.data.id) rev = r.data; } catch (e) { /* offline */ }
    }
    if (!rev) continue;                      // cannot locate authoritative revision → PRESERVE, do nothing
    const revisionId = String(rev.id);
    const measScope = measScopeFromBody(m.body);
    await putCacheSerialized(measDetailKey(revisionId), rev);
    if (measScope) await mutateCache(measScopeKey(measScope), (cur) => upsertRevision(cur, rev));
    if (measScope) {
      if (m.kind === "measurement") await mutateCache(measDraftKey(measScope), (cur) => retireCreateDraft(cur, m.client_id));
      await mutateCache(measWorkingKey(measScope), (cur) => planMeasurementWorkingAck(cur, { kind: m.kind, clientId: m.client_id, revisionId }));
    }
    await _removeMutation(m.client_id);      // retire the settled mutation
    summary.recovered += 1;
  }

  // 2) Orphaned working drafts: clear only when provably safe; surface a conflict when Office advanced.
  let workingNames = [];
  try { workingNames = await listCacheNames("measurement_working:"); } catch (e) { workingNames = []; }
  for (const name of workingNames) {
    let wd = null;
    try { wd = await getCache(name); } catch (e) { continue; }
    if (!wd || !wd.working) continue;
    const scope = parseWorkingScope(name);
    let activeMutation = null, baseRevision = null;
    if (wd.base && wd.base.id) {
      activeMutation = all.find((x) => x.client_id === `measurement-update:${wd.base.id}` && (x.state === "pending" || x.state === "failed" || x.state === "conflict")) || null;
      try { baseRevision = await getCache(measDetailKey(wd.base.id)); } catch (e) { baseRevision = null; }
    } else if (wd.local_client_id) {
      activeMutation = all.find((x) => x.client_id === wd.local_client_id && (x.state === "pending" || x.state === "failed" || x.state === "conflict")) || null;
    }
    const decision = classifyOrphanWorkingDraft({ wd, hasActiveMutation: !!activeMutation, baseRevision });
    if (decision.action === "clear") {
      await mutateCache(name, () => null);   // safe: empty or identical-to-base (no real edit)
      summary.recovered += 1;
    } else if (decision.action === "conflict" && wd.base && wd.base.id) {
      summary.conflicts.push({ kind: "conflict", mutationKind: "working_draft", revisionId: String(wd.base.id), scope, error: "Measurement changed in Office", serverDetail: decision.serverDetail });
    }
    // "keep" → never silently delete
  }

  _measurementAttention = summary;
  if (summary.recovered) _emit({ type: "measurement_reconciled" });
  _emit({ type: "measurement_recovery_done" });
  return summary;
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

// Back-compat: the "last synced" chip must reflect FULL convergence (advances only when no pending/failed/
// conflict/locked remain) — never a push that left failures behind.
export async function lastSyncAt() { return getCache(LAST_CONVERGED); }
export async function syncNow() { _resetBackoff(); refreshActiveLeads("manual").catch(() => {}); return runSync(); }

// B3B2: whether the sync engine is actively processing right now (drives the "Synchronizing…" status).
export function isSyncing() { return _running; }

// P0 locked-viewer: record (never swallow) a Roof Sketch viewer-open dependency failure. Called when
// the OPTIONAL queue lookup throws while opening a (possibly locked) sketch — the viewer still opens, but
// the failure is captured in the durable diagnostics ring so a stuck device can be explained.
export function recordSketchViewerDiagnostic({ revisionId, structureId, error } = {}) {
  try {
    _diag.recordMutation({
      clientId: sketchUpdateMutationId(revisionId, structureId),
      kind: "sketch_viewer_open", state: "failed", httpResult: "queue_lookup_failed",
      pathCategory: "/api/measurements/sketches", revisionId,
      recoveryAction: "none", error: error ? String(error.message || error) : "mutation_lookup_failed",
    });
    _persistDiag();
  } catch (e) { /* best effort — diagnostics must never block the viewer */ }
}

// B3B2: the durable mutation for exactly ONE structure's Roof Sketch (deterministic client_id). Returns
// null when there is no pending/failed/conflict/synced row for this structure. Never the global queue.
export async function currentSketchMutation(revisionId, structureId) {
  const id = sketchUpdateMutationId(revisionId, structureId);
  const all = await loadAllMutations();
  return all.find((x) => x.client_id === id) || null;
}

// Phase C: the durable measurement_update mutation for ONE revision (or null). Drives the truthful
// Accept-Proposed status (Pending sync vs settled) on the Field Roof Sketch reconciliation panel.
export async function currentMeasurementMutation(revisionId) {
  const id = `measurement-update:${String(revisionId)}`;
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

// The pending measurement CREATE mutation for a new (not-yet-acked) revision, matched by its draft
// client_id (or null). Lets the Field screen keep showing the local draft until Office acknowledges it.
export async function currentMeasurementCreate(clientId) {
  if (!clientId) return null;
  const all = await loadAllMutations();
  return all.find((x) => x.client_id === clientId && x.kind === "measurement") || null;
}

// Measurement conflict resolution — USE OFFICE: drop the salesperson's pending measurement_update and
// its optimistic detail so the authoritative Office revision becomes the working copy. Explicit only.
export async function discardMeasurementUpdate(revisionId) {
  const id = `measurement-update:${String(revisionId)}`;
  await _removeMutation(id);
  _emit({ type: "queued" });
  return { action: "use_office" };
}

// Fetch the full authoritative revision WITHOUT mutating caches before the atomic Use-Office transition.
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
}

// Measurement conflict resolution — KEEP MINE: rebase the pending measurement_update onto the newer Office
// version (adopt its updated_at as If-Match). When a 3-way-merged body is supplied, apply it so Office-only
// changes are preserved and only Field-changed fields override. Re-triggers sync after the durable rebase.
export async function rebaseMeasurementUpdate(revisionId, newIfMatch, mergedBody, newBaseDetail) {
  const id = `measurement-update:${String(revisionId)}`;
  const all = await loadAllMutations();
  const m = all.find((x) => x.client_id === id);
  if (!m) return { action: "noop" };
  const base = measurementDocumentFromRevision(newBaseDetail);
  if (!mergedBody || !base || newIfMatch == null || newIfMatch === "") {
    return { action: "review_required", reason: "missing_or_untrusted_base" };
  }
  await saveMutation({
    ...m, body: mergedBody, ifMatch: newIfMatch,
    base_body: base, base_token: String(newIfMatch),
    state: "pending", error: null, errorCode: null, serverValue: null,
  });
  _emit({ type: "queued" });
  runSync().catch(() => {});
  return { action: "keep_local" };
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

// Salesperson-facing GLOBAL sync status. Reports each mutation state SEPARATELY (never lumps failed into
// "waiting to sync") and surfaces the four honest timestamps. `waiting` now means ONLY pending (in-flight)
// work; failed / conflict / locked are their own counts with their own messaging.
export async function pendingSummary() {
  const all = await loadAllMutations();
  const counts = countStates(all);
  const status = deriveSyncStatus(counts, { syncing: _running });

  const [pushAttempt, pushOk, pullOk, converged] = await Promise.all([
    getCache(LAST_PUSH_ATTEMPT), getCache(LAST_PUSH_OK), getCache(LAST_PULL_OK), getCache(LAST_CONVERGED),
  ]);

  return {
    items: all, counts,
    pending_count: status.pending_count,
    failed_count: status.failed_count,
    conflict_count: status.conflict_count,
    locked_count: status.locked_count,
    waiting: status.waiting,       // back-compat: now == pending_count (never includes failed)
    fully_converged: status.fully_converged,
    last_push_attempt_at: pushAttempt || null,
    last_successful_push_at: pushOk || null,
    last_successful_pull_at: pullOk || null,
    last_fully_converged_at: converged || null,
    lastSyncAt: converged || null, // back-compat alias — only advances on FULL convergence
    label: status.label, syncing: _running,
  };
}

// Auto-sync triggers. A device having internet does NOT guarantee Office is reachable, so a failed
// attempt simply leaves work pending (the queue never drops it) and we retry on the next trigger.
export function startAutoSync() {
  // Restore persisted diagnostics FIRST so the record of what happened before an app kill/restart is
  // available even before the first new sync pass writes anything.
  getCache(DIAG_KEY).then((s) => _diag.hydrate(s)).catch(() => {});
  // One-time startup recovery for phones stuck in the pre-fix state, BEFORE the first sync pass. Best-effort;
  // never blocks sync. Heals synced-but-undrained creates/updates + orphaned drafts; preserves conflicts/failures.
  recoverMeasurementsOnStartup().catch(() => {}).finally(() => { runSync().catch(() => {}); });
  // Office-to-Field near-real-time convergence: a relay `measurement_changed` invalidation pulls the
  // canonical copy for the affected lead immediately (screen-independent).
  setRelayEventHandler((evt) => { if (evt && evt.type === "measurement_changed") handleOfficeInvalidation(evt).catch(() => {}); });
  const unsubNet = NetInfo.addEventListener((state) => { if (state.isConnected) { _resetBackoff(); refreshActiveLeads("connectivity").catch(() => {}); runSync().catch(() => {}); } });
  const appSub = AppState.addEventListener("change", (s) => { if (s === "active") { _resetBackoff(); refreshActiveLeads("foreground").catch(() => {}); runSync().catch(() => {}); } });
  return () => {
    _clearRetryTimer();
    try { setRelayEventHandler(null); } catch (e) {}
    try { unsubNet && unsubNet(); } catch (e) {}
    try { appSub && appSub.remove && appSub.remove(); } catch (e) {}
  };
}
