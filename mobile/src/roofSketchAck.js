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
// `knownServer` (optional) is the authoritative cached server sketch { document_version, document }.
// When it (or an existing durable draft) raises the CAS version above incoming's own base, the matching
// authoritative server DOCUMENT is adopted as base_server_document so the CAS version and its base stay
// together for conflict review. Never fabricates a base (only adopts a real document) and never regresses
// a newer existing/incoming base.
function reconcileDraftWrite(existing, incoming, knownServerVersion = 0, knownServer = null) {
  const ok = !existing || (Number(incoming.edit_generation) || 0) >= (Number(existing.edit_generation) || 0);
  if (!ok) return { write: false, draft: existing };
  const nextVersion = maxV(incoming.document_version, knownServerVersion);
  const candidates = [
    { v: Number(incoming && incoming.document_version) || 0, doc: incoming ? incoming.base_server_document : null },
    { v: Number(existing && existing.document_version) || 0, doc: existing ? existing.base_server_document : null },
    { v: Number(knownServer && knownServer.document_version) || 0, doc: knownServer ? knownServer.document : null },
  ].filter((c) => c.doc != null);
  let base = incoming ? incoming.base_server_document : null;
  if (candidates.length) { candidates.sort((a, b) => b.v - a.v); base = candidates[0].doc; }
  return { write: true, draft: { ...incoming, document_version: nextVersion, base_server_document: base } };
}

// Atomic acknowledgement plan (pure): given the current draft AND the current pending mutation row,
// decide the durable writes. Generation-guarded so a newer draft/mutation (C) written concurrently is
// never overwritten and the CAS version never regresses. Consumed verbatim by the storage boundary.
function reconcileAckPlan({ draft, currentMutation, ackGeneration, serverValue } = {}) {
  const d = applySketchAck({ draft, ackGeneration, serverValue });
  const serverVersion = serverValue ? (Number(serverValue.document_version) || 0) : 0;
  let mutationUpdate = null;
  if (currentMutation && currentMutation.state === "pending") {
    const floored = Math.max(Number((currentMutation.body || {}).expected_version) || 0, serverVersion);
    // update ONLY expected_version; preserve C's document + mutation_generation (write guarded by gen)
    mutationUpdate = { client_id: currentMutation.client_id, mutation_generation: currentMutation.mutation_generation, body: { ...(currentMutation.body || {}), expected_version: floored } };
  }
  return { cacheDetail: d.cacheServer || null, retireDraft: d.retireDraft, nextDraft: d.nextDraft, mutationUpdate, case: d.case };
}

// Pure plan for the DURABLE expected_version floor (consumed verbatim by
// storage.floorPendingSketchExpectedVersion). Operates on a full pending mutation row: preserves the
// row's document, local_edit_generation and mutation_generation; only ever RAISES expected_version to
// the known server version (monotonic, never regresses). A non-pending row is left untouched.
function planExpectedVersionFloor(mutation, serverVersion) {
  if (!mutation || mutation.state !== "pending") return { updated: false };
  const cur = Number((mutation.body || {}).expected_version) || 0;
  const floored = Math.max(cur, Number(serverVersion) || 0);
  if (floored === cur) return { updated: false, expected_version: cur };
  return {
    updated: true,
    expected_version: floored,
    next: { ...mutation, body: { ...(mutation.body || {}), expected_version: floored } },
  };
}

module.exports = { applySketchAck, guardVersionFloor, reconcileDraftWrite, reconcileAckPlan, planExpectedVersionFloor };
