"use strict";
// Pure undo/redo stack logic (no React, CommonJS) so it can be unit-tested deterministically and be
// consumed by both Office and Field. Ported verbatim from the approved Office historyCore.js.
const MAX_HISTORY = 100;

function makeHistory(present) {
  return { past: [], present, future: [] };
}

// Discrete edit: current becomes past, redo branch cleared.
function push(h, next) {
  const past = [...h.past, h.present];
  if (past.length > MAX_HISTORY) past.shift();
  return { past, present: next, future: [] };
}

// Edit whose "before" state is explicit (used for drags previewed without history).
function pushFrom(h, prev, next) {
  const past = [...h.past, prev];
  if (past.length > MAX_HISTORY) past.shift();
  return { past, present: next, future: [] };
}

function undo(h) {
  if (!h.past.length) return h;
  const past = h.past.slice(0, -1);
  const present = h.past[h.past.length - 1];
  const future = [h.present, ...h.future];
  if (future.length > MAX_HISTORY) future.pop();
  return { past, present, future };
}

function redo(h) {
  if (!h.future.length) return h;
  const [present, ...future] = h.future;
  const past = [...h.past, h.present];
  if (past.length > MAX_HISTORY) past.shift();
  return { past, present, future };
}

const canUndo = (h) => h.past.length > 0;
const canRedo = (h) => h.future.length > 0;

module.exports = { MAX_HISTORY, makeHistory, push, pushFrom, undo, redo, canUndo, canRedo };
