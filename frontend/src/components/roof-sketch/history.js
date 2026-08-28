import { useCallback, useRef, useState } from "react";
import * as H from "./historyCore";

// In-memory undo/redo over canonical documents (thin React wrapper over the pure historyCore).
// Only the current document is ever persisted.
export function useSketchHistory(initialDoc) {
  const [h, setH] = useState(() => H.makeHistory(initialDoc));

  const reset = useCallback((next) => setH(H.makeHistory(next)), []);
  const commit = useCallback((next) => setH((cur) => H.push(cur, next)), []);
  const commitFrom = useCallback((prev, next) => setH((cur) => H.pushFrom(cur, prev, next)), []);
  const undo = useCallback(() => setH((cur) => H.undo(cur)), []);
  const redo = useCallback(() => setH((cur) => H.redo(cur)), []);
  const setDocDirect = useCallback((next) => setH((cur) => ({ ...cur, present: typeof next === "function" ? next(cur.present) : next })), []);

  return {
    doc: h.present,
    setDocDirect,
    commit,
    commitFrom,
    undo,
    redo,
    reset,
    canUndo: H.canUndo(h),
    canRedo: H.canRedo(h),
    historyDepth: h.past.length,
  };
}
