"use strict";
// Pure Field wiring adapters (Node-testable; NO React/RN). These are the SAME helpers the RoofSketch
// screen + canvas call in production, so contracts exercise real integration paths (not idealized
// inputs). All topology/geometry stays in @roofspan/roof-sketch-core.
const RS = require("@roofspan/roof-sketch-core");
const VIEW = require("./roofSketchView");
const { resolveInitialSketch } = require("./roofSketchFieldController");

const DRAG_THRESHOLD_PX = 8;

// Resolve the read-through cache envelope { data, stale, cachedAt, error } into the pure resolver's
// `server` shape, keeping the local draft authoritative. Returns { initial, statusMeta }.
function resolveFieldSketchLoad({ draft, sketchResult, structureId, hasActiveMutation = false } = {}) {
  const server = sketchResult && sketchResult.data ? sketchResult.data : null;
  const initial = resolveInitialSketch({ draft, server, structureId, hasActiveMutation });
  const statusMeta = {
    stale: !!(sketchResult && sketchResult.stale),
    cachedAt: (sketchResult && sketchResult.cachedAt) || null,
    error: (sketchResult && sketchResult.error) || null,
  };
  return { initial, statusMeta };
}

// P0 locked-viewer open resolution (pure). Decides whether the Field Roof Sketch screen can present a
// usable read/edit model, must show the retryable error state, or (locked + no saved sketch) the honest
// "no sketch" state. OPTIONAL dependencies are fault-isolated by the caller and passed in explicitly:
//   mutationError : truthy when currentSketchMutation() threw (queue lookup) — MUST NOT strand the viewer
//   sketchResult  : read-through envelope { data, stale, cachedAt, error } from cache.sketch() (or null)
//   draft         : loadSketchDraft() result (already null-on-error) or null
// Returns { phase, initial?, statusMeta, hasActiveMutation, diagnostics, reason? }.
//   phase "ready"          → a usable viewer/editor model was created (initial present)
//   phase "empty_readonly" → locked revision with NO real saved sketch (never fabricate a blank sketch)
//   phase "error"          → the sketch could not be loaded and there is no cached/local copy (retryable)
function _statusMeta(sketchResult) {
  return {
    stale: !!(sketchResult && sketchResult.stale),
    cachedAt: (sketchResult && sketchResult.cachedAt) || null,
    error: (sketchResult && sketchResult.error) || null,
  };
}
function resolveFieldSketchViewerOpen({ draft, sketchResult, mutation, mutationError, structureId, readOnly } = {}) {
  // A queue-lookup failure is OPTIONAL for viewing: default to no active mutation and keep opening.
  const hasActiveMutation = !mutationError && !!(mutation && (mutation.state === "pending" || mutation.state === "failed" || mutation.state === "conflict"));
  const server = sketchResult && sketchResult.data ? sketchResult.data : null;
  // AUTHORITATIVE "no sketch yet" (HTTP 404) is a legitimate empty state, NOT a load failure.
  const notFound = !!(sketchResult && sketchResult.notFound);
  // A HARD sketch-load failure = the read-through errored, produced no cached/server copy, AND is not an
  // authoritative not-found. A 404 must never be misread as a failure (it would block first-sketch creation).
  const sketchLoadFailed = !!(sketchResult && sketchResult.error) && !server && !notFound;
  const diagnostics = { mutationLookupFailed: !!mutationError, sketchLoadFailed, notFound };
  const statusMeta = _statusMeta(sketchResult);

  // No local draft to fall back on and the sketch genuinely could not be loaded → explicit retryable
  // error. Never mark the screen ready with incomplete data. (An authoritative 404 is NOT this case.)
  if ((!draft || !draft.document) && sketchLoadFailed) {
    return { phase: "error", reason: "sketch_load_failed", statusMeta, hasActiveMutation, diagnostics };
  }

  const initial = resolveInitialSketch({ draft, server, structureId, hasActiveMutation });

  // Locked/read-only revision with no draft and no server/cached copy: the resolver would return a fresh
  // "new" document — that must NOT be presented as a real roof sketch on a locked revision.
  if (readOnly && initial.source === "new") {
    return { phase: "empty_readonly", statusMeta, hasActiveMutation, diagnostics };
  }

  return { phase: "ready", initial, statusMeta, hasActiveMutation, diagnostics };
}

// Map the screen's snake_case route ids onto the controller's camelCase argument names (the controller
// naming is already contract-tested and must NOT change).
function makeFieldEditorArgs({ revision_id, structure_id, initial, persist } = {}) {
  return { revisionId: revision_id, structureId: structure_id, initial, persist };
}

function movedBeyondThreshold(aScreen, bScreen, thresholdPx = DRAG_THRESHOLD_PX) {
  return Math.hypot(bScreen[0] - aScreen[0], bScreen[1] - aScreen[1]) > thresholdPx;
}

// The authoritative pointer-up candidate is the last SYNCHRONOUSLY stored snap candidate on the gesture
// ref — never React render state (which may not have flushed).
function pickReleaseCandidate(gesture, fallback) {
  return gesture && gesture.snapCandidate ? gesture.snapCandidate : fallback;
}

// Two-finger transform with focal continuity: the model point under the ORIGINAL midpoint stays under
// the NEW midpoint at the new scale (constant separation => pure pan; changing separation => pan+zoom).
function applyTwoTouchView(view, prev, now, opts = {}) {
  const ratio = prev.dist > 0 ? now.dist / prev.dist : 1;
  const ns = VIEW.clampScale(view.scale * ratio, opts.min, opts.max);
  const mx = (prev.mid[0] - view.tx) / view.scale;
  const my = (prev.mid[1] - view.ty) / view.scale;
  return { scale: ns, tx: now.mid[0] - mx * ns, ty: now.mid[1] - my * ns };
}

// Join two edges; report when the caller must supply an explicit result type. Returns
// { ok, doc?, edgeId?, reason?, needsType }.
function attemptJoin(doc, aId, bId, resultType) {
  const r = RS.joinEdges(doc, aId, bId, resultType ? { resultType } : undefined);
  if (r.ok) return { ok: true, doc: r.doc, edgeId: r.edgeId, needsType: false };
  return { ok: false, reason: r.reason, needsType: r.reason === "type_conflict" };
}

// Build a connected facet from selected edges, but only commit if the operation itself introduces no
// NEW hard structural error. Returns { ok, doc?, facetId?, reason? } (original doc preserved on reject).
function commitFacetCreate(doc, edgeIds) {
  if (!edgeIds || edgeIds.length < 3) return { ok: false, reason: "facet_needs_three_edges", doc };
  const r = RS.createFacet(doc, edgeIds);
  if (!RS.validateMutation(doc, r.doc).ok) return { ok: false, reason: "facet_would_be_invalid", doc };
  return { ok: true, doc: r.doc, facetId: r.facetId };
}

function commitManualCreate(doc, vertexIds) {
  if (!vertexIds || vertexIds.length < 3) return { ok: false, reason: "polygon_needs_three_points", doc };
  const r = RS.createManualFacet(doc, vertexIds);
  if (!RS.validateMutation(doc, r.doc).ok) return { ok: false, reason: "facet_would_be_invalid", doc };
  return { ok: true, doc: r.doc, facetId: r.facetId };
}

// Truthful on-device save status from a controller flush()/retry() result. A newer generation still
// draining (ok && pending) must NOT read as "Saved" — only a durable, fully-drained state does.
function localSaveStatus(result) {
  if (!result || !result.ok || result.error) return "Could not save on device";
  if (result.pending) return "Saving on device…";
  return "Saved on device";
}

// B3B2: STRUCTURE-SPECIFIC live sync status for the open Field Roof Sketch. Combines the honest on-device
// save phase with THIS structure's deterministic durable mutation — never the global queue count, so a
// photo or another structure's work can't make this sketch look (un)synced. Inputs:
//   localSave: the current localSaveStatus() string (or null before any local save)
//   mutation:  THIS structure's durable row (measurement-sketch-update:<rev>:<struct>) or null
//   running:   whether the sync engine is actively processing right now
//   currentGeneration:      the editor's current COMMITTED edit generation
//   acknowledgedGeneration: the highest local generation Office has acknowledged for this structure
// "Synced to Office" requires the CURRENT committed generation to be the acknowledged one — an ack for an
// older generation while newer local work remains is NOT synced.
function fieldSketchSyncStatus({ localSave, mutation, running, currentGeneration, acknowledgedGeneration } = {}) {
  // Device durability comes first: a failed or still-draining local write is reported honestly.
  if (localSave === "Could not save on device") return localSave;
  if (localSave === "Saving on device…") return localSave;
  const state = mutation && mutation.state;
  if (state === "locked") return "Measurement revision locked";   // B3D: immutable revision — terminal
  if (state === "conflict") return "Conflict — review required";
  if (state === "failed") return "Sync issue — retry needed";     // durable, will NOT auto-retry
  if (state === "pending") return running ? "Synchronizing…" : "Waiting to sync";
  // No active (non-synced) mutation for this structure.
  const acked = Number(acknowledgedGeneration) || 0;
  const cur = Number(currentGeneration) || 0;
  if (cur > 0 && acked >= cur) return "Synced to Office";
  return "Saved on device";   // durable locally, newer than the acknowledged generation, not yet acked
}

// B3B2 race guard (latest-wins): apply a completed async status refresh ONLY if it is still the newest.
// `state` is a mutable holder { seq, acked, localSave }. `seq` is the sequence captured when THIS refresh
// began (see nextRefreshSeq). Overlapping onSyncChange() refreshes can finish out of order; a stale one
// must not revert a newer synced result or replace newer CAS metadata. Returns { applied, status }.
function nextRefreshSeq(state) { state.seq = (Number(state.seq) || 0) + 1; return state.seq; }

function applySketchRefresh({ seq, state, editor, mutation, draft, running, setStatus } = {}) {
  if (!editor || !state) return { applied: false, status: null };
  if (seq !== state.seq) return { applied: false, status: null };   // a newer refresh superseded this one
  // adoptServerVersion is itself monotonic; the seq gate additionally discards the WHOLE stale refresh.
  if (draft && draft.document_version != null) {
    editor.adoptServerVersion({ documentVersion: draft.document_version, baseServerDocument: draft.base_server_document });
  } else if (mutation && mutation.state === "synced" && mutation.serverValue) {
    editor.adoptServerVersion({ documentVersion: mutation.serverValue.document_version, baseServerDocument: mutation.serverValue.document });
  }
  if (mutation && mutation.state === "synced") {
    state.acked = Math.max(Number(state.acked) || 0, Number(mutation.local_edit_generation) || 0);
  }
  const status = fieldSketchSyncStatus({
    localSave: state.localSave, mutation, running,
    currentGeneration: editor.editGeneration, acknowledgedGeneration: state.acked,
  });
  if (setStatus) setStatus(status);
  return { applied: true, status };
}

// B3C/B3D: the single predicate for whether document-changing routes are blocked. A locked revision
// (readOnly, OR a live-detected immutable-revision lock), OR an unresolved sync conflict blocks every
// commit/stage/undo/redo/mode/build path. Used by BOTH the screen handlers (defensive guards, not just
// disabled UI) and contracts.
function editingLocked({ readOnly, conflict, locked } = {}) {
  return !!readOnly || !!conflict || !!locked;
}

// B3D: the durable mutation for THIS structure is in the terminal immutable-revision LOCKED state.
function deriveSketchLocked(mutation) {
  return !!(mutation && mutation.state === "locked");
}

module.exports = {
  DRAG_THRESHOLD_PX,
  resolveFieldSketchLoad,
  resolveFieldSketchViewerOpen,
  makeFieldEditorArgs,
  movedBeyondThreshold,
  pickReleaseCandidate,
  applyTwoTouchView,
  attemptJoin,
  commitFacetCreate,
  commitManualCreate,
  localSaveStatus,
  fieldSketchSyncStatus,
  nextRefreshSeq,
  applySketchRefresh,
  editingLocked,
  deriveSketchLocked,
  stageFromController,
};

// Production staging path (used by BOTH RoofSketch.js and contracts): capture the controller's
// AUTHORITATIVE committed snapshot, drain persistence, and stage ONLY if that exact captured
// generation is durable. Never reads mutable UI/visual document state.
async function stageFromController(editor, coordinator, { revisionId, structureId } = {}) {
  if (!editor || !coordinator) return { staged: false, reason: "not_ready" };
  const snap = editor.authoritativeSnapshot();
  await editor.flush();
  const durable = editor.isGenerationDurable(snap.editGeneration);
  if (!durable) return { staged: false, reason: "not_durable", generation: snap.editGeneration };
  return coordinator.stage({
    revisionId, structureId,
    document: snap.document, documentVersion: snap.documentVersion,
    editMode: snap.editMode, editGeneration: snap.editGeneration, durable: true,
  });
}
