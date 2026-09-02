"use strict";
// Component-level LOGIC contract for the Field measurement UI primitives (LabeledField / SelectField /
// PitchField). React Native can't render in-pod, so we test the pure functions that DRIVE what those
// components display: hydration of the selected value, custom-pitch detection, and canonical persistence.
// This proves a hydrated SelectField shows the right label and that reopening keeps the right selection.
const assert = require("assert");
const {
  PITCHES, CUSTOM_PITCH,
  selectedOptionLabel, hasSelection, isCustomPitch,
  pitchOptions, pitchSelectValue, pitchFromSelection, customRiseValue,
} = require("../measurementFieldControls");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

const STRUCTURE_TYPES = [["main_house", "Main House"], ["attached_garage", "Attached Garage"], ["detached_garage", "Detached Garage"], ["other", "Other"]];
const EDGE_TYPES = [["eave", "Eave"], ["rake", "Rake"], ["ridge", "Ridge"], ["hip", "Hip"], ["valley", "Valley"]];
const ATTACH_OPTS = [["", "None"], ["attached", "Attached"], ["detached", "Detached"]];

// --- SelectField hydration: a hydrated value renders its label (closed trigger text) ---
assert.strictEqual(selectedOptionLabel(STRUCTURE_TYPES, "main_house", "Select"), "Main House");
assert.strictEqual(selectedOptionLabel(STRUCTURE_TYPES, "detached_garage", "Select"), "Detached Garage");
assert.strictEqual(selectedOptionLabel(EDGE_TYPES, "valley", "Select"), "Valley");
assert.strictEqual(selectedOptionLabel(ATTACH_OPTS, "attached", "None"), "Attached");
ok("SelectField renders the hydrated selected label for structure type / edge type / attachment");

// Attachment stored as null (from server) still resolves to the "None" option when normalized value=""
assert.strictEqual(selectedOptionLabel(ATTACH_OPTS, (null || ""), "None"), "None");
assert.strictEqual(hasSelection(ATTACH_OPTS, ""), true);
ok('null attachment normalizes to the "None" option');

// Unknown / empty value falls back to placeholder and is NOT marked as a real selection.
assert.strictEqual(selectedOptionLabel(STRUCTURE_TYPES, "", "Select structure"), "Select structure");
assert.strictEqual(hasSelection(STRUCTURE_TYPES, ""), false);
assert.strictEqual(hasSelection(STRUCTURE_TYPES, "main_house"), true);
ok("empty value shows placeholder and is not a real selection");

// --- Roof-plane association hydration (dynamic option list built from refs) ---
const facetOptions = [["", "— None —"], ["rAAA", "F1"], ["rBBB", "F2"], ["rCCC", "F3"]];
assert.strictEqual(selectedOptionLabel(facetOptions, "rBBB", "—"), "F2");
assert.strictEqual(selectedOptionLabel(facetOptions, "", "—"), "— None —");
// After the associated plane is removed, a dangling ref resolves to the placeholder (no crash).
assert.strictEqual(selectedOptionLabel(facetOptions, "rZZZ_removed", "Pick plane"), "Pick plane");
ok("Primary/Secondary plane SelectField hydrates by ref and degrades safely when a plane is removed");

// Reopen stability: hydrating the SAME stored value twice yields the SAME label (controlled, no drift).
const firstOpen = selectedOptionLabel(facetOptions, "rCCC", "—");
const secondOpen = selectedOptionLabel(facetOptions, "rCCC", "—");
assert.strictEqual(firstOpen, secondOpen);
assert.strictEqual(firstOpen, "F3");
ok("SelectField selection is stable across reopen (same value → same rendered label)");

// --- Pitch selector + Custom ---
assert.deepStrictEqual(PITCHES, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
const popts = pitchOptions();
assert.strictEqual(popts.length, PITCHES.length + 1);
assert.deepStrictEqual(popts[0], ["2", "2/12"]);
assert.deepStrictEqual(popts[popts.length - 1], [CUSTOM_PITCH, "Custom…"]);
// Common pitch 6 → shows "6/12", not custom.
assert.strictEqual(isCustomPitch(6), false);
assert.strictEqual(pitchSelectValue(6), "6");
assert.strictEqual(selectedOptionLabel(popts, pitchSelectValue(6), "Pitch"), "6/12");
// 11/12 supported.
assert.strictEqual(isCustomPitch(11), false);
assert.strictEqual(selectedOptionLabel(popts, pitchSelectValue(11), "Pitch"), "11/12");
ok('common pitch 6 renders as "6/12" (and 11/12 supported)');

// Custom pitch 7.5 → custom mode + Custom… label; canonical value preserved.
assert.strictEqual(isCustomPitch(7.5), true);
assert.strictEqual(pitchSelectValue(7.5), CUSTOM_PITCH);
assert.strictEqual(selectedOptionLabel(popts, pitchSelectValue(7.5), "Pitch"), "Custom…");
ok('custom pitch 7.5 renders as "Custom…" and stays custom');

// Selecting Custom… stores the blank sentinel (keeps the Custom Rise input open); a number stores numerically.
assert.strictEqual(pitchFromSelection(CUSTOM_PITCH), "");
assert.strictEqual(isCustomPitch(pitchFromSelection(CUSTOM_PITCH)), true);
assert.strictEqual(pitchFromSelection("8"), 8);
assert.strictEqual(isCustomPitch(pitchFromSelection("8")), false);
ok("choosing Custom… opens the rise input; choosing a common pitch stores the integer");

// Typing a custom rise: blank stays "" (input open); a number is stored numerically; garbage collapses to "".
assert.strictEqual(customRiseValue(""), "");
assert.strictEqual(customRiseValue("7.5"), 7.5);
assert.strictEqual(customRiseValue("abc"), "");
ok("custom rise entry normalizes to canonical value (blank stays open, number persists)");

// null pitch (nothing chosen) is NOT custom and shows the placeholder.
assert.strictEqual(isCustomPitch(null), false);
assert.strictEqual(selectedOptionLabel(popts, pitchSelectValue(null), "Pitch"), "Pitch");
ok("un-set pitch shows the placeholder and is not treated as custom");

console.log("\nFIELD MEASUREMENT CONTROL LOGIC: all " + n + " checks passed");
