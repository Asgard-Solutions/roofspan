"use strict";
// B3A: stage committed Field Roof Sketch edits into the EXISTING durable mutation queue. This is NOT a
// new sync/retry engine — it only (1) requires local durability first, (2) freezes a snapshot of the
// committed document, (3) dedupes the same edit_generation, and (4) hands a deterministic sketch
// mutation to the existing queueMutation() (which coalesces by the shared clientId). Newest generation
// wins because we always stage the latest snapshot under the same mutation identity.
const { sketchUpdateMutation } = require("./sketchCache");

const clone = (doc) => JSON.parse(JSON.stringify(doc || {}));
function deepFreeze(o) {
  if (o && typeof o === "object") { for (const k of Object.keys(o)) deepFreeze(o[k]); Object.freeze(o); }
  return o;
}

// queueMutation: the existing sync.queueMutation. buildMutation: injectable for tests (defaults to the
// shared sketchUpdateMutation so the deterministic identity/body are reused).
function createSketchSyncCoordinator({ queueMutation, buildMutation = sketchUpdateMutation } = {}) {
  const lastStaged = {};
  const key = (r, s) => `${r}:${s}`;

  async function stage({ revisionId, structureId, document, documentVersion, editMode, editGeneration, durable }) {
    // 1. local durability MUST precede queueing
    if (!durable) return { staged: false, reason: "not_durable" };
    const k = key(revisionId, structureId);
    const gen = Number(editGeneration) || 0;
    // 4. dedupe: never re-stage an already-staged (or older) generation
    if (lastStaged[k] != null && gen <= lastStaged[k]) return { staged: false, reason: "deduped", generation: lastStaged[k] };
    // 3. freeze the snapshot so later Field edits can't mutate staged work in memory
    const snapshot = deepFreeze(clone(document));
    const spec = buildMutation({ revisionId, structureId, document: snapshot, documentVersion, editMode });
    // 5. reuse the existing queue; local_edit_generation is queue-only metadata (NOT in the request body)
    const stored = await queueMutation({ ...spec, label: "Roof sketch", localEditGeneration: gen });
    lastStaged[k] = gen;
    return { staged: true, generation: gen, mutation: stored, snapshot };
  }

  return { stage, lastStagedGeneration: (r, s) => (lastStaged[key(r, s)] == null ? null : lastStaged[key(r, s)]) };
}

module.exports = { createSketchSyncCoordinator, deepFreeze };
