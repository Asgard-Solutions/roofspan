"use strict";
// Canonical Office/Field measurement PARITY guard. Fails if a normal user-facing field exists in one
// surface's measurement form but not the other, or if a previously-fixed mismatch regresses. Static
// source scan (both are JSX) — deterministic, no runtime.
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const FIELD = fs.readFileSync(path.resolve(__dirname, "../screens/Measurements.js"), "utf8");
const OFFICE = fs.readFileSync(path.resolve(__dirname, "../../../frontend/src/components/MeasurementWorksheet.jsx"), "utf8");
let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

// Every canonical persisted field must be referenced by BOTH measurement forms.
const CANON = [
  // Structure
  "structure_type", "included_in_scope", "attachment", "stories", "approx_height_ft",
  // Roof planes
  "facet_label", "structure_ref", "pitch_rise", "area_sqft", "width_ft", "length_ft", "roof_material",
  // Roof lines
  "edge_type", "facet_ref", "facet_ref_secondary", "label",
  // Penetrations
  "pen_type", "quantity", "diameter_in", "width_in", "length_in",
  // Existing roof & deck
  "existing_covering_type", "existing_condition", "existing_layers", "existing_underlayment",
  "deck_type", "deck_thickness_in", "damaged_deck_sf", "replacement_sheets", "full_redeck",
  // Ventilation
  "drip_edge_lf", "ridge_vent_lf", "intake_soffit_vent_lf",
  // Access / conditions
  "steep_access", "high_access", "long_carry", "restricted_access", "landscaping_protection", "conditions_notes",
  // Gutters (optional but supported in both)
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

// Roof line units: BOTH must offer ft + in inputs (never decimal-only on one side).
for (const [name, src] of [["Field", FIELD], ["Office", OFFICE]]) {
  assert.ok(src.includes('placeholder="ft"'), `${name} roof lines must have a ft input`);
  assert.ok(src.includes('placeholder="in"'), `${name} roof lines must have an in input`);
  assert.ok(/LF/.test(src), `${name} must show calculated LF`);
}
ok("both surfaces enter roof lines as ft + in with a calculated LF (no manual decimal conversion)");

// Label and Notes must be SEPARATE (the old Office bug combined them into one ambiguous value).
assert.ok(!/row\.label \|\| row\.notes/.test(OFFICE), "Office must not combine Label and Notes into one field");
assert.ok(OFFICE.includes('placeholder="Label"') && OFFICE.includes('placeholder="Notes"'), "Office roof line must expose separate Label and Notes");
assert.ok(FIELD.includes("Label (optional)") && FIELD.includes("Line notes (optional)"), "Field roof line must expose separate Label and Notes");
ok("Label and Notes are separate roof-line inputs in both surfaces");

// Both surfaces expose Primary AND Secondary plane association for roof lines.
for (const [name, src] of [["Field", FIELD], ["Office", OFFICE]]) {
  assert.ok(/[Ss]econdary/.test(src) && src.includes("facet_ref_secondary"), `${name} must expose a Secondary roof plane association`);
  assert.ok(/[Pp]rimary/.test(src), `${name} must label the Primary roof plane association`);
}
ok("Primary + Secondary roof-plane associations exposed in both surfaces");

// --- UI-parity increment ---

// Full Structure Type labels in BOTH (Field previously abbreviated Main / Att. Garage / Det. Garage).
for (const [name, src] of [["Field", FIELD], ["Office", OFFICE]]) {
  for (const lbl of ["Main House", "Attached Garage", "Detached Garage"]) {
    assert.ok(src.includes(lbl), `${name} must use the full Structure Type label "${lbl}"`);
  }
  assert.ok(!/"Att\. Garage"|"Det\. Garage"/.test(src), `${name} must not abbreviate Structure Types`);
}
ok("both surfaces use full Structure Type labels (Main House / Attached Garage / Detached Garage)");

// No user-facing "facet"/"Facet" wording in DISPLAYED text (headings, JSX/RN text nodes, placeholder/title/
// label attribute values). Internal identifiers (facet_id, facet_ref, facet_label, facets, measurement_facet,
// test IDs, API/record types) are allowed because they are NOT user-visible. We build a corpus of only the
// user-visible strings, then whole-word match facet/facets case-insensitively.
function userVisibleText(src) {
  const parts = [];
  for (const m of src.matchAll(/>([^<>{}]+)</g)) parts.push(m[1]);              // JSX / RN static text nodes
  for (const m of src.matchAll(/\b(?:placeholder|title|label)="([^"]*)"/g)) parts.push(m[1]);  // user-facing attrs
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

// Three separate sections + Gutters (Optional) in BOTH.
for (const [name, src] of [["Field", FIELD], ["Office", OFFICE]]) {
  assert.ok(/Existing Roof & Deck/.test(src), `${name} needs a separate "Existing Roof & Deck" section`);
  assert.ok(/Ventilation/.test(src), `${name} needs a separate "Ventilation" section`);
  assert.ok(/Access \/ Conditions/.test(src), `${name} needs a separate "Access / Conditions" section`);
  assert.ok(/Gutters \(Optional\)/.test(src), `${name} needs a "Gutters (Optional)" section`);
  assert.ok(/Measurement Photos/.test(src), `${name} needs a "Measurement Photos" section`);
}
ok('canonical sections (Existing Roof & Deck / Ventilation / Access / Conditions / Gutters (Optional) / Measurement Photos) present in both');

// Report metadata removed from the normal Office manual entry.
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

console.log("\nOFFICE/FIELD MEASUREMENT FIELD PARITY: all " + n + " checks passed");
