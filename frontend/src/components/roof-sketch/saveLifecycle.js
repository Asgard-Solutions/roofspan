// Generation-based save/dirty tracking (pure, Node-testable). Dirty is derived from a monotonic edit
// generation vs the last generation actually persisted — NEVER from a "saved" string flag — so an edit
// made while a save request is in flight can never be masked by that in-flight save resolving.

export function initSaveState(serverVersion = null) {
  return {
    editGeneration: 0,
    lastPersistedGeneration: 0,
    serverVersion,          // canonical CAS version of the sketch row (null = not yet created)
    saving: false,
    inflight: null,         // { snapshotGeneration, expectedVersion } while a PUT is in flight
    phase: "saved",         // saved | unsaved | saving | conflict | validation | error
  };
}

// Any canonical sketch-document edit bumps the generation (geometry, mapping, proposal decision,
// penetration, calibration, lock, mode change, ...). This is the ONLY thing that creates dirtiness.
export function markEdited(state) {
  const editGeneration = state.editGeneration + 1;
  return { ...state, editGeneration, phase: state.saving ? "saving" : "unsaved" };
}

export function isDirty(state) {
  return state.editGeneration !== state.lastPersistedGeneration;
}

// Freeze the generation + CAS version the request will carry. The caller freezes the DOCUMENT snapshot
// alongside this so the request can never send a mutable ref that changes mid-flight.
export function beginSave(state) {
  const inflight = { snapshotGeneration: state.editGeneration, expectedVersion: state.serverVersion };
  return { next: { ...state, saving: true, inflight, phase: "saving" }, ...inflight };
}

// Save of `snapshotGeneration` succeeded; server advanced to `newServerVersion`.
export function resolveSaveSuccess(state, snapshotGeneration, newServerVersion) {
  const lastPersistedGeneration = Math.max(state.lastPersistedGeneration, snapshotGeneration);
  const next = {
    ...state,
    saving: false,
    inflight: null,
    serverVersion: newServerVersion,
    lastPersistedGeneration,
  };
  next.phase = isDirty(next) ? "unsaved" : "saved";
  return next;
}

// Save failed. Local document is untouched by the reducer; we stay dirty and expose the failure phase.
// kind: "conflict" (409) | "validation" (422) | "error" (network/500/generic).
export function resolveSaveFailure(state, kind) {
  const phase = kind === "conflict" ? "conflict" : kind === "validation" ? "validation" : "error";
  return { ...state, saving: false, inflight: null, phase };
}

// Adopt the server's document after an explicit "Reload Server Version" (destroys local edits).
export function adoptServerVersion(state, newServerVersion) {
  return { ...state, editGeneration: 0, lastPersistedGeneration: 0, serverVersion: newServerVersion, saving: false, inflight: null, phase: "saved" };
}
