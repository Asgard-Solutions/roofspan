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

// USE OFFICE VERSION — discard the local unsynced work and adopt the authoritative Office document.
// Plan: cache the Office sketch as the authoritative detail, retire the local draft (guarded), remove the
// conflict mutation, and re-init the open editor to the Office document (fresh history) -> Synced to Office.
function planUseOffice(mutation, draft) {
  const review = conflictReview(mutation, draft);
  if (!review) return { action: "noop" };
  if (_isStale(draft, review.conflictGeneration)) {
    return { action: "stale", reason: "newer_local_work", conflictGeneration: review.conflictGeneration };
  }
  const cacheDetail = {
    ...(mutation.serverValue || {}),
    document: review.office || {},
    document_version: review.officeVersion,
    edit_mode: review.officeEditMode,
  };
  return {
    action: "use_office",
    revisionId: review.revisionId, structureId: review.structureId,
    removeClientId: mutation.client_id,
    conflictGeneration: review.conflictGeneration,
    cacheDetail,
    retireDraft: true,
    editor: { document: review.office || {}, documentVersion: review.officeVersion, editMode: review.officeEditMode },
  };
}

// KEEP LOCAL DRAFT — keep the local geometry as the desired NEXT version, rebased onto the Office base.
// Plan: advance the durable draft's CAS base/version to Office (keeping local document + generation), and
// re-stage the local document as a FRESH pending mutation with expected_version = Office document_version.
// It does NOT pretend the conflict is already synced — status stays pending until Office acknowledges.
function planKeepLocal(mutation, draft) {
  const review = conflictReview(mutation, draft);
  if (!review) return { action: "noop" };
  if (_isStale(draft, review.conflictGeneration)) {
    return { action: "stale", reason: "newer_local_work", conflictGeneration: review.conflictGeneration };
  }
  const nextDraft = makeSketchDraft(review.revisionId, review.structureId, {
    document: review.local || {},
    documentVersion: review.officeVersion,        // adopt the Office version as the new CAS base version
    baseServerDocument: review.office || null,    // adopt the Office document as base_server_document
    editMode: review.localEditMode,
    editGeneration: review.conflictGeneration,    // preserve the local generation (no new commit)
  });
  const spec = sketchUpdateMutation({
    revisionId: review.revisionId, structureId: review.structureId,
    document: review.local || {}, documentVersion: review.officeVersion, editMode: review.localEditMode,
  });
  return {
    action: "keep_local",
    revisionId: review.revisionId, structureId: review.structureId,
    conflictGeneration: review.conflictGeneration,
    nextDraft,
    // expected_version = Office document_version; local_edit_generation preserved for traceability.
    requeue: { ...spec, label: "Roof sketch", localEditGeneration: review.conflictGeneration },
    editor: { documentVersion: review.officeVersion, baseServerDocument: review.office || null },
  };
}

module.exports = { conflictReview, sketchSummary, planUseOffice, planKeepLocal };
