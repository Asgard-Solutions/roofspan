"use strict";
// Pure Field Roof Sketch editor controller (Node-testable; NO React/RN/DOM). All geometry/topology/
// history/dimension math is delegated to @roofspan/roof-sketch-core — this file contains ZERO editor
// algorithms. It owns ONE commit path, ONE preview path, edit-generation bookkeeping, and a serialized
// local-draft persistence chain (persistence is INJECTED so this stays platform-neutral and testable).
const RS = require("@roofspan/roof-sketch-core");
const { makeSketchDraft } = require("./sketchCache");

// Decide the initial working document. Local draft is authoritative in B2A (never silently replaced by
// a server GET). Falls back to a normalized server/cached sketch, then to a fresh document.
function resolveInitialSketch({ draft, server, structureId } = {}) {
  if (draft && draft.document) {
    return {
      document: RS.normalizeSketchDocument(draft.document),
      editMode: draft.edit_mode || "connected_graph",
      documentVersion: draft.document_version || 0,
      editGeneration: draft.edit_generation || 1,
      baseServerDocument: draft.base_server_document || null,
      source: "local_draft",
    };
  }
  if (server && server.document) {
    const doc = RS.normalizeSketchDocument(server.document);
    return {
      document: doc,
      editMode: server.edit_mode || doc.edit_mode || "connected_graph",
      documentVersion: server.document_version || 0,
      editGeneration: 1,
      baseServerDocument: server.document,
      source: "server",
    };
  }
  const doc = RS.createSketchDocument({ structureId });
  return { document: doc, editMode: doc.edit_mode, documentVersion: 0, editGeneration: 1, baseServerDocument: null, source: "new" };
}

// persist: async (draft, generation) => void  (e.g. bound cache.saveSketchDraft). Injected so the
// controller never imports the SQLite/network cache directly.
function createFieldEditor({ revisionId, structureId, initial, persist } = {}) {
  const save = typeof persist === "function" ? persist : async () => {};
  let history = RS.makeHistory(initial.document);
  let working = initial.document;
  let editGeneration = Number(initial.editGeneration) || 1;
  let editMode = initial.editMode || "connected_graph";
  const documentVersion = initial.documentVersion || 0;
  const baseServerDocument = initial.baseServerDocument || null;

  // Serialized write chain: every committed state persists in strict edit-generation order; a later
  // commit can never resolve before an earlier one (no A-overwrites-B). A failed durable write is
  // recorded (never silently swallowed) but must NOT poison the chain — later writes still drain.
  let chain = Promise.resolve();
  let lastPersistedGeneration = 0;
  let lastScheduledGeneration = 0;
  let persistError = null;

  function buildDraft() {
    return makeSketchDraft(revisionId, structureId, {
      document: working, documentVersion, baseServerDocument, editMode, editGeneration,
    });
  }
  function schedulePersist() {
    const gen = editGeneration;
    lastScheduledGeneration = Math.max(lastScheduledGeneration, gen);
    const draft = buildDraft();
    chain = chain.then(async () => {
      try {
        await save(draft, gen);
        lastPersistedGeneration = Math.max(lastPersistedGeneration, gen);
        if (lastPersistedGeneration >= lastScheduledGeneration) persistError = null;
      } catch (e) {
        persistError = e || new Error("persist_failed");
      }
    });
    return chain;
  }
  function commitDoc(nextHistory, nextDoc) {
    history = nextHistory;
    working = nextDoc;
    editGeneration += 1;
    schedulePersist();
    return working;
  }

  return {
    get document() { return working; },
    get editGeneration() { return editGeneration; },
    get editMode() { return editMode; },
    get source() { return initial.source; },
    get lastPersistedGeneration() { return lastPersistedGeneration; },
    get persistError() { return persistError; },
    get documentVersion() { return documentVersion; },
    // Authoritative save snapshot for queue staging: the COMMITTED document (history.present, never a
    // live drag/gesture preview), the CAS documentVersion, editMode, and the committed editGeneration.
    authoritativeSnapshot() { return { document: history.present, documentVersion, editMode, editGeneration }; },
    // A specific committed generation is durable when there is no persist error AND it has drained.
    isGenerationDurable(gen) { return persistError === null && lastPersistedGeneration >= (Number(gen) || 0); },
    canUndo: () => RS.historyCanUndo(history),
    canRedo: () => RS.historyCanRedo(history),

    // PREVIEW: visual-only. No history, no generation bump, no persistence.
    preview(nextDoc) { working = nextDoc; return working; },
    // Discard an in-flight preview and return to the last committed state.
    restore() { working = history.present; return working; },

    // COMMIT: exactly one history state + one generation + one serialized persist.
    commit(nextDoc) { return commitDoc(RS.historyPush(history, nextDoc), nextDoc); },
    // Commit a gesture whose "before" is explicit (drag previewed without history).
    commitFrom(prevDoc, nextDoc) { return commitDoc(RS.historyPushFrom(history, prevDoc, nextDoc), nextDoc); },

    undo() { const h = RS.historyUndo(history); return commitDocReplace(h); },
    redo() { const h = RS.historyRedo(history); return commitDocReplace(h); },

    setEditMode(mode) { const next = RS.setEditMode(working, mode); editMode = next.edit_mode; return this.commit(next); },
    validate() { return RS.validateSketch(working); },
    buildDraft,
    // Truthful drain: resolves to a status object. ok = NO persistence error (durability). pending =
    // a newer generation is still draining (not yet the final durable state). Callers must treat
    // (ok && pending) as "still saving", not "saved" — see WIRE.localSaveStatus.
    async flush() {
      await chain;
      // ok reflects DURABILITY ONLY: a newer generation still pending (no error) is not a failure.
      const pending = lastPersistedGeneration < lastScheduledGeneration;
      return { ok: persistError === null, pending, lastPersistedGeneration, lastScheduledGeneration, error: persistError };
    },
    // Re-attempt persisting the CURRENT working document at the current generation (no history/gen bump).
    retry() { schedulePersist(); return this.flush(); },
  };

  // undo/redo replace the present from history without pushing a new state, but still bump the
  // generation + persist so a reopen restores the post-undo document.
  function commitDocReplace(nextHistory) {
    history = nextHistory;
    working = history.present;
    editGeneration += 1;
    schedulePersist();
    return working;
  }
}

module.exports = { resolveInitialSketch, createFieldEditor };
