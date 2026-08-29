"use strict";
// B3A: stage committed Field Roof Sketch edits into the EXISTING durable mutation queue. This is NOT a
// new sync/retry engine — it only (1) requires local durability first, (2) freezes a snapshot of the
// committed document, (3) dedupes the same edit_generation, and (4) hands a deterministic sketch
// mutation to the existing queueMutation() (which coalesces by the shared clientId). Newest generation
// wins because we always stage the latest snapshot under the same mutation identity.
const { sketchUpdateMutation } = require("./sketchCache");
const casFloor = require("./roofSketchCasFloor");

const clone = (doc) => JSON.parse(JSON.stringify(doc || {}));
function deepFreeze(o) {
  if (o && typeof o === "object") { for (const k of Object.keys(o)) deepFreeze(o[k]); Object.freeze(o); }
  return o;
}

// queueMutation: the existing sync.queueMutation. buildMutation: injectable for tests (defaults to the
// shared sketchUpdateMutation so the deterministic identity/body are reused).
function createSketchSyncCoordinator({ queueMutation, buildMutation = sketchUpdateMutation } = {}) {
  const lastStaged = {};
  const serverFloor = {};
  const key = (r, s) => `${r}:${s}`;
  // Record an authoritative server version so later staging cannot regress the CAS version (§reverse race).
  // Also mirrored into the shared module-scope floor so a late ack processed in sync.js (a DIFFERENT
  // module, with no reference to this coordinator) still floors this open screen's next staging.
  function noteServerVersion(revisionId, structureId, version) {
    const k = key(revisionId, structureId);
    serverFloor[k] = Math.max(serverFloor[k] || 0, Number(version) || 0);
    casFloor.noteVersion(revisionId, structureId, version);
  }

  async function stage({ revisionId, structureId, document, documentVersion, editMode, editGeneration, durable }) {
    // 1. local durability MUST precede queueing
    if (!durable) return { staged: false, reason: "not_durable" };
    const k = key(revisionId, structureId);
    const gen = Number(editGeneration) || 0;
    // 4. dedupe: never re-stage an already-staged (or older) generation
    if (lastStaged[k] != null && gen <= lastStaged[k]) return { staged: false, reason: "deduped", generation: lastStaged[k] };
    // reverse-race guard: never stage below a known authoritative server version (this coordinator's own
    // floor OR the shared cross-module floor fed by a late sync.js acknowledgement)
    const version = Math.max(Number(documentVersion) || 0, serverFloor[k] || 0, casFloor.floor(revisionId, structureId));
    // 3. freeze the snapshot so later Field edits can't mutate staged work in memory
    const snapshot = deepFreeze(clone(document));
    const spec = buildMutation({ revisionId, structureId, document: snapshot, documentVersion: version, editMode });
    // 5. reuse the existing queue; local_edit_generation is queue-only metadata (NOT in the request body)
    const stored = await queueMutation({ ...spec, label: "Roof sketch", localEditGeneration: gen });
    lastStaged[k] = gen;
    return { staged: true, generation: gen, mutation: stored, snapshot, expectedVersion: version };
  }

  return { stage, noteServerVersion, lastStagedGeneration: (r, s) => (lastStaged[key(r, s)] == null ? null : lastStaged[key(r, s)]) };
}

module.exports = { createSketchSyncCoordinator, deepFreeze };
