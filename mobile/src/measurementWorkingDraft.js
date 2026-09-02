"use strict";
// Serialized working-draft persistence with a Save "seal" (root-cause race fix #2).
//
// The Field Measurements screen debounces an autosave of the in-progress working draft. When the rep
// presses Save, the measurement mutation is staged and the working draft is cleared. Without a hard
// guarantee, a late / in-flight autosave could land its write AFTER the Save cleared the draft and
// resurrect stale, already-superseded data — which would then reappear on reopen.
//
// This store makes that impossible deterministically, independent of enqueue ordering:
//   - all writes run on one serialized chain (mirrors cache.putCacheSerialized ordering);
//   - Save calls sealAndClear(): it flips `sealed` SYNCHRONOUSLY (so any autosave enqueued after this
//     point is a no-op) and then clears the slot on the same chain;
//   - persist() re-checks `sealed` INSIDE the serialized section, so even an autosave that was enqueued
//     BEFORE the seal cannot write once Save has sealed the scope.
//
// Pure + Node-testable; the RN screen wires its scope's serialized put/clear into `io`.

function createMeasurementWorkingDraftStore(io) {
  // io: { put(value) => Promise<boolean>, clear() => Promise<any> } — the serialized cache slot for ONE scope.
  let sealed = false; // set the instant Save stages the mutation; never reset for this scope/store instance
  let chain = Promise.resolve();
  const run = (task) => {
    const next = chain.then(task, task);
    // keep the chain alive even if a task rejects, so ordering is preserved
    chain = next.then(() => {}, () => {});
    return next;
  };

  return {
    // Autosave / background-flush path: persist ONLY when Save has not sealed this scope. The seal is
    // re-checked inside the serialized section, so a write that began before Save cannot land after it.
    persist(value) {
      return run(async () => {
        if (sealed) return false;
        return await io.put(value);
      });
    },
    // Save path: seal first (blocks every concurrent/late autosave), then clear the draft slot.
    sealAndClear() {
      sealed = true;
      return run(async () => {
        await io.clear();
        return true;
      });
    },
    // Revert-to-baseline path (NOT a Save): clear without sealing, because editing may resume and a
    // fresh working draft should be allowed again.
    clearUnsealed() {
      return run(async () => {
        await io.clear();
      });
    },
    isSealed() {
      return sealed;
    },
  };
}

module.exports = { createMeasurementWorkingDraftStore };
