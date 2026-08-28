"use strict";
// Deterministic offline identity for roof sketches (Plan 1 Task 5).
// One structure sketch is keyed by (revisionId, structureId). Repeated offline edits to the same
// structure MUST coalesce into a single pending whole-document mutation.

function sketchDetailKey(revisionId, structureId) {
  return `sketch:${revisionId}:${structureId}`;
}

function sketchDraftKey(revisionId, structureId) {
  return `sketch-draft:${revisionId}:${structureId}`;
}

function sketchUpdateMutationId(revisionId, structureId) {
  return `measurement-sketch-update:${revisionId}:${structureId}`;
}

function sketchPath(revisionId, structureId) {
  return `/mobile/measurements/${revisionId}/sketches/${structureId}`;
}

// A local draft keeps everything needed to (a) restore work after crash and (b) explain a conflict:
// the local document, the optimistic token, and the base server document it was edited from.
function makeSketchDraft(revisionId, structureId, { document, documentVersion = 0, baseServerDocument = null, editMode = "connected_graph" } = {}) {
  return {
    kind: "sketch_draft",
    revision_id: revisionId,
    structure_id: structureId,
    edit_mode: editMode,
    document: document || {},
    document_version: documentVersion,          // optimistic token to send as expected_version
    base_server_document: baseServerDocument,   // for conflict review
    updated_at: new Date().toISOString(),
  };
}

function mergeSketchDraft(draft, patch) {
  return { ...draft, ...patch, updated_at: new Date().toISOString() };
}

module.exports = {
  sketchDetailKey, sketchDraftKey, sketchUpdateMutationId, sketchPath, makeSketchDraft, mergeSketchDraft,
};
