"use strict";
// B3C: pure decision layer for REVIEWING and EXPLICITLY resolving a Roof Sketch HTTP 409 conflict.
// NO React/RN/IO and NO automatic graph merge — the salesperson chooses Office or Local. The sync layer
// performs the durable writes by mechanically executing the plans below. Every plan is bound to the
// EXACT conflict generation being reviewed, so a newer local edit is never deleted, overwritten, marked
// synced, or silently resolved (generation safety per B3B1 patterns).
const { sketchUpdateMutation, makeSketchDraft } = require("./sketchCache");

// Parse revision/structure from the deterministic client_id "measurement-sketch-update:<rev>:<struct>".
function _ids(mutation) {
  const parts = String((mutation && mutation.client_id) || "").split(":");
  return { revisionId: parts[1] || null, structureId: parts[2] || null };
}

// A compact, deterministic read-only summary of a sketch document (facet/edge/vertex/feature counts).
// Used by the mobile review UI so each version is understandable without a graphical diff engine.
function sketchSummary(doc) {
  const d = doc || {};
  return {
    facets: Array.isArray(d.facets) ? d.facets.length : 0,
    edges: Array.isArray(d.edges) ? d.edges.length : 0,
    vertices: Array.isArray(d.vertices) ? d.vertices.length : 0,
    penetrations: Array.isArray(d.penetrations) ? d.penetrations.length : 0,
  };
}

// The three preserved review snapshots for the current conflict:
//   Base   = the authoritative document the local draft was originally edited FROM (base_server_document)
//   Local  = the salesperson's current durable unsynced sketch (the local draft document)
//   Office = the authoritative server sketch returned in the 409 (mutation.serverValue.document) + version
function conflictReview(mutation, draft) {
  if (!mutation || mutation.state !== "conflict") return null;
  const server = mutation.serverValue || {};
  const body = mutation.body || {};
  const { revisionId, structureId } = _ids(mutation);
  return {
    revisionId, structureId,
    conflictGeneration: Number(mutation.local_edit_generation) || 0,
    base: (draft && draft.base_server_document) || null,
    local: (draft && draft.document) || body.document || null,
    localEditMode: (draft && draft.edit_mode) || body.edit_mode || "connected_graph",
    office: server.document || null,
    officeVersion: Number(server.document_version) || 0,
    officeEditMode: server.edit_mode || "connected_graph",
  };
}

// Generation guard: if durable local work has advanced BEYOND the captured conflict generation, an older
// resolution is stale and must do nothing.
function _isStale(draft, conflictGeneration) {
  if (!draft) return false;
  return (Number(draft.edit_generation) || 0) > (Number(conflictGeneration) || 0);
}

// Snapshot captured at REVIEW time and carried into the atomic durable transition. It records the exact
// conflict identity (client_id + generations) plus the chosen Office/Local documents, so the transition
// can (a) verify the live durable state still matches this exact reviewed conflict and (b) build the
// resolution writes WITHOUT re-reading (avoids a plan/apply skew).
function buildReviewedContext(mutation, draft, keys = {}) {
  const r = conflictReview(mutation, draft) || {};
  return {
    clientId: mutation ? mutation.client_id : null,
    draftKey: keys.draftKey || null,
    detailKey: keys.detailKey || null,
    conflictGeneration: r.conflictGeneration != null ? r.conflictGeneration : (Number(mutation && mutation.local_edit_generation) || 0),
    queueGeneration: mutation && mutation.mutation_generation != null ? Number(mutation.mutation_generation) : null,
    revisionId: r.revisionId || null, structureId: r.structureId || null,
    base: r.base || null, local: r.local || null, localEditMode: r.localEditMode || "connected_graph",
    office: r.office || null, officeVersion: r.officeVersion || 0, officeEditMode: r.officeEditMode || "connected_graph",
    serverValue: (mutation && mutation.serverValue) || {},
  };
}

// THE single atomic resolution decision. Consumed VERBATIM by the storage transition (production) AND by
// the contracts — there is no separate mirror. `live` = the FRESHLY re-read durable state inside the
// _serialize boundary: { row: current pending_mutations row|null, draft: current durable draft|null }.
// Every invariant is checked against `live`; ANY drift returns `{action:"stale"}` and produces NO writes.
// On success it returns the exact writes to apply (built from the reviewed snapshot, never from a stale plan).
function decideSketchConflictResolution(choice, reviewed, live) {
  const row = live && live.row;
  const draft = live && live.draft;
  // ---- invariants against the LIVE durable state (immediately before making the change permanent) ----
  if (!row) return { action: "stale", reason: "row_missing" };
  if (row.client_id !== reviewed.clientId) return { action: "stale", reason: "client_id_changed" };
  if (row.state !== "conflict") return { action: "stale", reason: "not_conflict" };
  if ((Number(row.local_edit_generation) || 0) !== (Number(reviewed.conflictGeneration) || 0)) return { action: "stale", reason: "conflict_generation_changed" };
  if (reviewed.queueGeneration != null && (Number(row.mutation_generation) || 0) !== (Number(reviewed.queueGeneration) || 0)) return { action: "stale", reason: "queue_generation_changed" };
  if (_isStale(draft, reviewed.conflictGeneration)) return { action: "stale", reason: "draft_advanced" };

  if (choice === "use_office") {
    const cacheDetail = { ...(reviewed.serverValue || {}), document: reviewed.office || {}, document_version: reviewed.officeVersion, edit_mode: reviewed.officeEditMode };
    return {
      action: "use_office", clientId: reviewed.clientId,
      conflictGeneration: reviewed.conflictGeneration, queueGeneration: reviewed.queueGeneration,
      cacheDetail, retireDraft: true, casFloorVersion: reviewed.officeVersion,
      editor: { document: reviewed.office || {}, documentVersion: reviewed.officeVersion, editMode: reviewed.officeEditMode },
    };
  }
  if (choice === "keep_local") {
    const nextDraft = makeSketchDraft(reviewed.revisionId, reviewed.structureId, {
      document: reviewed.local || {}, documentVersion: reviewed.officeVersion,
      baseServerDocument: reviewed.office || null, editMode: reviewed.localEditMode,
      editGeneration: reviewed.conflictGeneration,
    });
    const spec = sketchUpdateMutation({
      revisionId: reviewed.revisionId, structureId: reviewed.structureId,
      document: reviewed.local || {}, documentVersion: reviewed.officeVersion, editMode: reviewed.localEditMode,
    });
    // Transition the EXACT conflict row into a fresh pending send: preserve identity/scope/local
    // geometry + local generation; advance mutation_generation as a NEW logical send (never regresses).
    const nextRow = {
      ...row,
      kind: spec.kind, method: spec.method, path: spec.path, body: spec.body,
      local_edit_generation: reviewed.conflictGeneration,
      mutation_generation: (Number(row.mutation_generation) || 1) + 1,
      state: "pending", serverValue: null, error: null, errorCode: null, attempts: 0,
    };
    return {
      action: "keep_local", clientId: reviewed.clientId,
      conflictGeneration: reviewed.conflictGeneration, queueGeneration: reviewed.queueGeneration,
      nextDraft, nextRow, casFloorVersion: reviewed.officeVersion,
      editor: { documentVersion: reviewed.officeVersion, baseServerDocument: reviewed.office || null },
    };
  }
  return { action: "noop" };
}

// Thrown to abort + roll back the resolution transaction as a STALE (no-op) outcome (distinct from a
// real SQL error, which also rolls back but propagates). Carries `__stale` so the caller maps it back to
// { action: "stale" } only AFTER the transaction has rolled everything back.
function _stale(reason) { const e = new Error("stale:" + reason); e.__stale = reason; return e; }

// The transactional resolution body. Runs against a small executor interface so production can back it
// with a REAL SQLite transaction (expo-sqlite withTransactionAsync) while the contracts drive it with an
// in-memory snapshot/rollback executor + an injected failpoint. Every read, the invariant decision, and
// every durable write happen here: throwing anywhere (stale, a guarded DELETE/UPDATE that did not affect
// exactly one row, an injected failure, or a real SQL error) aborts the whole transaction so NOTHING is
// committed. `failpoint(name)` is a no-op in production.
//   tx interface:
//     readConflictRow(clientId) -> live row (any state) | null
//     readDraft(draftKey)       -> live draft | null
//     writeCache(key, value)    -> void   (value === null retires the draft)
//     deleteConflictRow(clientId, queueGen)               -> affected row count
//     transitionConflictToPending(clientId, queueGen, row) -> affected row count
async function applyResolutionInTx(tx, choice, reviewed, failpoint = () => {}) {
  const liveRow = await tx.readConflictRow(reviewed.clientId);
  const liveDraft = await tx.readDraft(reviewed.draftKey);
  const decision = decideSketchConflictResolution(choice, reviewed, { row: liveRow, draft: liveDraft });
  if (decision.action !== "use_office" && decision.action !== "keep_local") throw _stale(decision.reason || decision.action);

  if (decision.action === "use_office") {
    await tx.writeCache(reviewed.detailKey, decision.cacheDetail);   // cache authoritative Office sketch
    failpoint("use_office:after_cache");
    await tx.writeCache(reviewed.draftKey, null);                    // retire the exact local draft
    failpoint("use_office:after_draft");
    const affected = await tx.deleteConflictRow(reviewed.clientId, reviewed.queueGeneration);
    if (affected !== 1) throw _stale("delete_missed");               // guarded DELETE missed -> roll back
    return decision;
  }
  // keep_local
  await tx.writeCache(reviewed.draftKey, decision.nextDraft);        // rebase draft to Office version/base
  failpoint("keep_local:after_draft");
  const affected = await tx.transitionConflictToPending(reviewed.clientId, reviewed.queueGeneration, decision.nextRow);
  if (affected !== 1) throw _stale("update_missed");                 // guarded UPDATE missed -> roll back draft too
  return decision;
}

module.exports = { conflictReview, sketchSummary, buildReviewedContext, decideSketchConflictResolution, applyResolutionInTx };
