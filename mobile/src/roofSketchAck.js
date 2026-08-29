"use strict";
// B3B1: generation-safe processing of a SUCCESSFUL sketch acknowledgement. Pure decision layer — the
// caller performs the durable IO. It never deletes/overwrites newer local work and never regresses the
// authoritative CAS version.
const { mergeSketchDraft } = require("./sketchCache");
const maxV = (a, b) => Math.max(Number(a) || 0, Number(b) || 0);

// draft: current local draft (or null). ackGeneration: the local_edit_generation that was acknowledged.
// serverValue: Office response { document_version, document, edit_mode }.
function applySketchAck({ draft, ackGeneration, serverValue } = {}) {
  const serverVersion = serverValue ? (Number(serverValue.document_version) || 0) : 0;
  const cacheServer = serverValue || null;
  const ack = Number(ackGeneration) || 0;
  if (!draft) return { case: "no_draft", retireDraft: false, cacheServer, nextDraft: null, requeue: null };
  const draftGen = Number(draft.edit_generation) || 0;
  if (draftGen === ack) {
    // Case 1 — acknowledged generation is still the newest local work: retire that exact draft.
    return { case: "matched", retireDraft: true, cacheServer, nextDraft: null, requeue: null };
  }
  if (draftGen > ack) {
    // Case 2 — newer local work B exists: preserve B's document + generation, advance ONLY its
    // authoritative base/version to the acknowledged server version, and leave B pending.
    const nextVersion = maxV(draft.document_version, serverVersion);
    const nextDraft = mergeSketchDraft(draft, {
      document_version: nextVersion,
      base_server_document: serverValue ? serverValue.document : draft.base_server_document,
    });
    return { case: "superseded", retireDraft: false, cacheServer, nextDraft, requeue: { expected_version: nextVersion } };
  }
  // draftGen < ack should not occur; treat as a stale ack and change nothing about the draft.
  return { case: "stale_ack", retireDraft: false, cacheServer, nextDraft: draft, requeue: null };
}

// Reverse race: once a server version is known, later staging/draft writes must preserve at least it.
function guardVersionFloor(proposedVersion, knownServerVersion) {
  return maxV(proposedVersion, knownServerVersion);
}

// Generation-safe draft write: monotonic edit_generation AND a version floor (never regress CAS).
function reconcileDraftWrite(existing, incoming, knownServerVersion = 0) {
  const ok = !existing || (Number(incoming.edit_generation) || 0) >= (Number(existing.edit_generation) || 0);
  if (!ok) return { write: false, draft: existing };
  return { write: true, draft: { ...incoming, document_version: maxV(incoming.document_version, knownServerVersion) } };
}

module.exports = { applySketchAck, guardVersionFloor, reconcileDraftWrite };
