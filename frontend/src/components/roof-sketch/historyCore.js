// Thin compatibility wrapper (Phase B1B). Undo/redo logic is authoritative in
// @roofspan/roof-sketch-core. This file only maps the legacy Office names onto the shared exports so
// existing Office callers (history.js, tests) stay unchanged. No local history manipulation remains.
export { MAX_HISTORY, makeHistory } from "@roofspan/roof-sketch-core";
export {
  historyPush as push,
  historyPushFrom as pushFrom,
  historyUndo as undo,
  historyRedo as redo,
  historyCanUndo as canUndo,
  historyCanRedo as canRedo,
} from "@roofspan/roof-sketch-core";
