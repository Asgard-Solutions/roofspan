// Pure keyboard-gate for the Roof Sketch Editor (Node-testable). While the unsaved-close confirmation is
// open it is a TRUE modal: nothing may mutate the sketch/history/selection behind it. Escape only
// dismisses the confirmation (and only when a Save & Close is not already running).
export function resolveKey({ closeConfirm, closing, ctrlOrMeta, key, shift } = {}) {
  const k = (key || "").toLowerCase();
  if (closeConfirm) {
    if (key === "Escape" && !closing) return "dismiss-modal";
    return "none"; // undo/redo/delete/backspace/etc. are all swallowed behind the modal
  }
  if (ctrlOrMeta && k === "z" && !shift) return "undo";
  if (ctrlOrMeta && (k === "y" || (k === "z" && shift))) return "redo";
  if (key === "Delete" || key === "Backspace") return "delete";
  if (key === "Escape") return "deselect";
  return "none";
}
