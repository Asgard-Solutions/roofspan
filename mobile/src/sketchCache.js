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
function makeSketchDraft(revisionId, structureId, { document, documentVersion = 0, baseServerDocument = null, editMode = "connected_graph", editGeneration = 1 } = {}) {
  return {
    kind: "sketch_draft",
    revision_id: revisionId,
    structure_id: structureId,
    edit_mode: editMode,
    document: document || {},
    document_version: documentVersion,          // optimistic token to send as expected_version
    base_server_document: baseServerDocument,   // for conflict review
    edit_generation: editGeneration,            // monotonic per-commit token for crash-safe autosave
    updated_at: new Date().toISOString(),
  };
}

function mergeSketchDraft(draft, patch) {
  return { ...draft, ...patch, updated_at: new Date().toISOString() };
}

// Crash-safe autosave ordering (spec §18): a persist may only advance the on-device draft — an older
// async write that resolves late must NEVER clobber a newer edit generation.
function shouldPersistDraft(existing, incoming) {
  if (!existing) return true;
  const a = Number(existing.edit_generation) || 0;
  const b = Number(incoming.edit_generation) || 0;
  return b >= a;
}

// Build the deterministic whole-document sketch PUT (spec §19). Same clientId every save so repeated
// offline saves of ONE structure coalesce into a single logical mutation carrying the latest document.
function sketchUpdateMutation({ revisionId, structureId, document, documentVersion, editMode = "connected_graph" }) {
  return {
    kind: "measurement_sketch_update",
    method: "put",
    path: sketchPath(revisionId, structureId),
    clientId: sketchUpdateMutationId(revisionId, structureId),
    body: { schema_version: 1, edit_mode: editMode, document, expected_version: documentVersion },
  };
}

module.exports = {
  sketchDetailKey, sketchDraftKey, sketchUpdateMutationId, sketchPath, makeSketchDraft, mergeSketchDraft,
  shouldPersistDraft, sketchUpdateMutation,
};
