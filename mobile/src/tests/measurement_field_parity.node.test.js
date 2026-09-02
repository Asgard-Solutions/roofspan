"use strict";
// Canonical Office/Field measurement PARITY + Field-UX guard. Fails if a normal user-facing field exists
// in one surface's measurement form but not the other, if a previously-fixed mismatch regresses, OR if the
// Field screen drops the Office-style UX primitives (persistent labels + tap-to-open SelectField) and
// reverts to placeholder-only inputs / chip matrices. Static source scan — deterministic, no runtime.
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const MEAS = fs.readFileSync(path.resolve(__dirname, "../screens/Measurements.js"), "utf8");
const FIELDS = fs.readFileSync(path.resolve(__dirname, "../components/MeasurementFields.js"), "utf8");
const CONTROLS = fs.readFileSync(path.resolve(__dirname, "../measurementFieldControls.js"), "utf8");
// The Field measurement UI is Measurements.js + its shared primitives — scan them together.
const FIELD = [MEAS, FIELDS, CONTROLS].join("\n");
const OFFICE = fs.readFileSync(path.resolve(__dirname, "../../../frontend/src/components/MeasurementWorksheet.jsx"), "utf8");
let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

// Every canonical persisted field must be referenced by BOTH measurement forms.
const CANON = [
  "structure_type", "included_in_scope", "attachment", "stories", "approx_height_ft",
  "facet_label", "structure_ref", "pitch_rise", "area_sqft", "width_ft", "length_ft", "roof_material",
  "edge_type", "facet_ref", "facet_ref_secondary", "label",
  "pen_type", "quantity", "diameter_in", "width_in", "length_in",
  "existing_covering_type", "existing_condition", "existing_layers", "existing_underlayment",
  "deck_type", "deck_thickness_in", "damaged_deck_sf", "replacement_sheets", "full_redeck",
  "drip_edge_lf", "ridge_vent_lf", "intake_soffit_vent_lf",
  "steep_access", "high_access", "long_carry", "restricted_access", "landscaping_protection", "conditions_notes",
  "gutter_lf", "gutter_size", "gutter_type", "downspout_count", "downspout_lf", "gutter_guard_lf", "gutter_notes",
];
const missingField = CANON.filter((k) => !FIELD.includes(k));
const missingOffice = CANON.filter((k) => !OFFICE.includes(k));
assert.deepStrictEqual(missingField, [], "Field measurement form is missing canonical fields: " + missingField.join(", "));
assert.deepStrictEqual(missingOffice, [], "Office measurement form is missing canonical fields: " + missingOffice.join(", "));
ok("all " + CANON.length + " canonical measurement fields present in BOTH Office and Field");

// Terminology parity: both use "Roof planes" and "Roof lines" (not "facets"/"Edges") in the UI.
for (const [name, src] of [["Field", FIELD], ["Office", OFFICE]]) {
  assert.ok(/Roof planes/i.test(src), `${name} must label the section "Roof planes"`);
  assert.ok(/Roof lines/i.test(src), `${name} must label the section "Roof lines"`);
}
ok('both surfaces use "Roof planes" and "Roof lines" terminology');

// Roof line units: BOTH must offer ft + in inputs (never decimal-only on one side) + a calculated LF.
for (const [name, src] of [["Field", FIELD], ["Office", OFFICE]]) {
  assert.ok(src.includes('placeholder="ft"'), `${name} roof lines must have a ft input`);
  assert.ok(src.includes('placeholder="in"'), `${name} roof lines must have an in input`);
  assert.ok(/LF/.test(src), `${name} must show calculated LF`);
}
// Field must additionally label those boxes "Feet" / "Inches" (persistent labels, not placeholder-only).
assert.ok(/label="Feet"/.test(FIELD) && /label="Inches"/.test(FIELD), "Field roof line must use persistent Feet/Inches labels");
ok("both surfaces enter roof lines as ft + in with a calculated LF (Field uses Feet/Inches labels)");

// Label and Notes must be SEPARATE roof-line inputs.
assert.ok(!/row\.label \|\| row\.notes/.test(OFFICE), "Office must not combine Label and Notes into one field");
assert.ok(/label="Label"/.test(OFFICE) && /label="Notes"/.test(OFFICE), "Office roof line must expose separate Label and Notes");
assert.ok(/label="Label"/.test(FIELD) && /meas-edge-labeltext/.test(FIELD) && /meas-edge-notes/.test(FIELD), "Field roof line must expose separate labeled Label and Notes");
ok("Label and Notes are separate roof-line inputs in both surfaces");

// Both surfaces expose Primary AND Secondary plane association for roof lines.
for (const [name, src] of [["Field", FIELD], ["Office", OFFICE]]) {
  assert.ok(/[Ss]econdary/.test(src) && src.includes("facet_ref_secondary"), `${name} must expose a Secondary roof plane association`);
  assert.ok(/[Pp]rimary/.test(src), `${name} must label the Primary roof plane association`);
}
ok("Primary + Secondary roof-plane associations exposed in both surfaces");

// Full Structure Type labels in BOTH.
for (const [name, src] of [["Field", FIELD], ["Office", OFFICE]]) {
  for (const lbl of ["Main House", "Attached Garage", "Detached Garage"]) {
    assert.ok(src.includes(lbl), `${name} must use the full Structure Type label "${lbl}"`);
  }
  assert.ok(!/"Att\. Garage"|"Det\. Garage"/.test(src), `${name} must not abbreviate Structure Types`);
}
ok("both surfaces use full Structure Type labels (Main House / Attached Garage / Detached Garage)");

// No user-facing "facet"/"Facet" wording in DISPLAYED text (JSX/RN text nodes, placeholder/title/label attrs).
function userVisibleText(src) {
  const parts = [];
  for (const m of src.matchAll(/>([^<>{};]+)</g)) parts.push(m[1]);
  for (const m of src.matchAll(/\b(?:placeholder|title|label)="([^"]*)"/g)) parts.push(m[1]);
  return parts.join("\n");
}
for (const [name, src] of [["Field", FIELD], ["Office", OFFICE]]) {
  const hits = [...userVisibleText(src).matchAll(/\bfacets?\b/gi)].map((m) => m[0]);
  assert.deepStrictEqual(hits, [], `${name} shows user-facing facet wording (must use "Roof plane"): ${hits.join(", ")}`);
}
ok('no user-facing "facet"/"Facet" text in displayed strings (internal identifiers preserved)');

// Pitch is presented as x/12 in BOTH.
for (const [name, src] of [["Field", FIELD], ["Office", OFFICE]]) {
  assert.ok(/\}\/12|p\}\/12/.test(src), `${name} must present pitch as x/12`);
}
ok("pitch presented as x/12 in both surfaces");

// Canonical sections + Gutters (Optional) + Measurement Photos in BOTH.
for (const [name, src] of [["Field", FIELD], ["Office", OFFICE]]) {
  assert.ok(/Existing Roof & Deck/.test(src), `${name} needs a separate "Existing Roof & Deck" section`);
  assert.ok(/Ventilation/.test(src), `${name} needs a separate "Ventilation" section`);
  assert.ok(/Access \/ Conditions/.test(src), `${name} needs a separate "Access / Conditions" section`);
  assert.ok(/Gutters \(Optional\)/.test(src), `${name} needs a "Gutters (Optional)" section`);
  assert.ok(/Measurement Photos/.test(src), `${name} needs a "Measurement Photos" section`);
}
ok('canonical sections present in both');

// Report metadata removed from normal Office manual entry.
assert.ok(!/Reported area SF/i.test(OFFICE), "Office must not expose an editable Reported Area SF input");
assert.ok(!/Reported report area/i.test(OFFICE), "Office must not show the report-area comparison in normal manual entry");
ok("Reported Area SF input + report-area comparison removed from normal Office manual entry");

// Primary Save action says "Save Measurements" in BOTH; Field keeps a separate Field Complete action.
for (const [name, src] of [["Field", FIELD], ["Office", OFFICE]]) {
  assert.ok(/Save Measurements/.test(src), `${name} primary action must say "Save Measurements"`);
}
assert.ok(/Save & Mark Field Complete/.test(FIELD), "Field must keep a separate Save & Mark Field Complete action");
ok('primary action is "Save Measurements" in both; Field keeps a separate Field Complete action');

// Field exposes Remove for Structure, Roof Plane and Roof Line.
assert.ok(/Remove structure/.test(FIELD) && /Remove roof plane/.test(FIELD) && /Remove roof line/.test(FIELD), "Field must expose Remove for Structure, Roof Plane and Roof Line");
ok("Field exposes Remove Structure / Remove Roof Plane / Remove Roof Line");

// --- Office-UX conversion guard (the point of this iteration) ---

// Field must import and USE the LabeledField + SelectField primitives (and PitchField/ToggleRow).
assert.ok(/import\s*\{[^}]*LabeledField[^}]*SelectField[^}]*\}\s*from\s*"\.\.\/components\/MeasurementFields"/.test(MEAS), "Measurements.js must import LabeledField + SelectField");
assert.ok(/<LabeledField\b/.test(MEAS), "Field must render LabeledField inputs");
assert.ok(/<SelectField\b/.test(MEAS), "Field must render SelectField selectors");
assert.ok(/<PitchField\b/.test(MEAS) && /<ToggleRow\b/.test(MEAS), "Field must render PitchField + ToggleRow");
ok("Field screen imports and uses LabeledField / SelectField / PitchField / ToggleRow");

// SelectField must be a controlled tap-to-open MODAL (no native wheel, no internal measurement state).
assert.ok(/<Modal\b/.test(FIELDS), "SelectField must open a Modal (tap-to-open bottom sheet)");
assert.ok(/function SelectField/.test(FIELDS) && /onChange\(o\[0\]\)/.test(FIELDS), "SelectField must emit the chosen option via onChange (controlled)");
assert.ok(!/useState\([^)]*value/.test(FIELDS.replace(/const \[open, setOpen\] = useState\(false\);/g, "")), "SelectField must not copy `value` into internal state");
ok("SelectField is a controlled tap-to-open modal (no internal value copy, no native wheel)");

// The old chip matrices for single-select values must be GONE from the Field screen.
assert.ok(!/<Chip\b/.test(MEAS), "Field must not render the old <Chip> matrices for single-select values");
assert.ok(!/style=\{s\.chips\}/.test(MEAS), "Field must not use the old chip-row layout");
ok("legacy single-select chip matrices removed from the Field screen");

// Persistent visible labels for the key numeric/text boxes (no placeholder-only identification).
for (const lbl of ["Name", "Stories", "Approx Height (ft)", "Area (SF)", "Width (ft)", "Length (ft)", "Feet", "Inches", "Diameter (in)", "Width (in)", "Length (in)"]) {
  assert.ok(FIELD.includes(`label="${lbl}"`), `Field must show a persistent "${lbl}" label`);
}
ok("persistent visible labels present for the key Field inputs");

// SelectField used for the required Office-style single-selection controls.
for (const tid of ["meas-structure-type-", "meas-structure-attachment-", "meas-facet-structure-", "meas-edge-type-", "meas-edge-primary-", "meas-edge-secondary-", "meas-pen-plane-"]) {
  assert.ok(MEAS.includes(tid), `Field must expose a SelectField for ${tid}`);
}
ok("SelectField wired for Structure Type / Attachment / Plane→Structure / Roof-line Type / Primary + Secondary plane / Penetration plane");

// --- Roof Line Type contract: Office and Field must expose the SAME 9 choices, same order, same labels ---
const ROOF_LINE_TYPES = [
  ["eave", "Eave"], ["rake", "Rake"], ["ridge", "Ridge"], ["hip", "Hip"], ["valley", "Valley"],
  ["dead_valley", "Dead Valley"], ["sidewall", "Sidewall (Step Flashing)"], ["headwall", "Headwall (Apron Flashing)"], ["transition", "Transition"],
];
for (const [name, src] of [["Field", MEAS], ["Office", OFFICE]]) {
  for (const [val, label] of ROOF_LINE_TYPES) {
    assert.ok(src.includes(`["${val}", "${label}"]`), `${name} roof-line type must be ["${val}", "${label}"]`);
  }
  assert.ok(!src.includes('"step_flashing"') && !src.includes('"apron_flashing"'), `${name} must NOT create step_flashing/apron_flashing types`);
}
ok("Office + Field expose the identical 9 Roof Line Types (dead_valley added; sidewall/headwall internal values preserved with flashing labels)");

console.log("\nOFFICE/FIELD MEASUREMENT FIELD PARITY: all " + n + " checks passed");
