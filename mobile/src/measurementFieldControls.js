"use strict";
// Pure, testable logic behind the Field measurement UI primitives (LabeledField / SelectField /
// PitchField). Kept framework-free (CommonJS) so it runs under Node contracts AND is imported by the
// React Native components — the component visuals are a thin shell over these functions.

const PITCHES = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
const CUSTOM_PITCH = "__custom__";

// The label shown in a closed SelectField for the currently hydrated value (falls back to placeholder).
function selectedOptionLabel(options, value, placeholder) {
  const found = (options || []).find((o) => String(o[0]) === String(value));
  return found ? found[1] : (placeholder || "");
}

// Whether a SelectField currently holds one of its options (used to style value vs placeholder).
function hasSelection(options, value) {
  return (options || []).some((o) => String(o[0]) === String(value));
}

// A pitch is "custom" when it is the blank sentinel ("") or a numeric rise not in the common list.
// null/undefined = nothing chosen yet (NOT custom).
function isCustomPitch(value) {
  if (value === "") return true;
  if (value == null) return false;
  return !PITCHES.includes(Number(value));
}

// Option rows for the pitch selector: 2/12 … 12/12 then a Custom… row.
function pitchOptions() {
  return PITCHES.map((p) => [String(p), `${p}/12`]).concat([[CUSTOM_PITCH, "Custom…"]]);
}

// The value the pitch SelectField shows while closed (a common pitch key, or the Custom sentinel).
function pitchSelectValue(value) {
  return isCustomPitch(value) ? CUSTOM_PITCH : String(Number(value));
}

// Translate a pitch selection back into the canonical stored value the app persists.
// A common pitch → integer; Custom… → "" (blank sentinel that keeps the custom-rise input open).
function pitchFromSelection(selected) {
  if (selected === CUSTOM_PITCH) return "";
  return Number(selected);
}

// Normalize a typed custom-rise string into the stored value. Blank stays "" (custom input remains open);
// a valid number is stored numerically; garbage collapses to "".
function customRiseValue(text) {
  if (text === "" || text == null) return "";
  return Number.isFinite(Number(text)) ? Number(text) : "";
}

module.exports = {
  PITCHES,
  CUSTOM_PITCH,
  selectedOptionLabel,
  hasSelection,
  isCustomPitch,
  pitchOptions,
  pitchSelectValue,
  pitchFromSelection,
  customRiseValue,
};
