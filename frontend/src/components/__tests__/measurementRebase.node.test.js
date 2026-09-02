"use strict";
// Office "Keep My Version" hidden-metadata rebase regression (Node, no React).
//
// Reproduces the exact data-safety gap the review flagged: on a stale-version conflict, Keep My Version
// must rebase onto the NEWER authoritative server revision (V2) so that Office-editable values win but
// ALL non-editable/system data (top-level report metadata, Roof Plane orientation/geometry, hidden summary
// keys) keeps its latest V2 value — never reverting to the stale V1 form.

const assert = require("assert");
const path = require("path");
const Module = require("module");
const babel = require("@babel/core");

function load(rel) {
  const file = path.resolve(__dirname, rel);
  const { code } = babel.transformFileSync(file, { plugins: ["@babel/plugin-transform-modules-commonjs"] });
  const m = new Module(file, module);
  m.filename = file; m.paths = Module._nodeModulePaths(path.dirname(file));
  m._compile(code, file);
  return m.exports;
}

const R = load("../measurementRebase.js");
let n = 0;
const ok = (msg) => { n++; console.log("  \u2713 " + msg); };

// V1: what the Office user loaded and started editing (their working form `ed`, keyed by ref=server id).
const edV1 = {
  reported_area_sqft: 2000,               // report metadata (V1)
  structures: [{ ref: "S1", name: "Main House", structure_type: "main_house", included_in_scope: true }],
  facets: [
    // MF1 exists on the server; MFL is a locally-created plane (no server row yet).
    { ref: "MF1", structure_ref: "S1", facet_label: "F1", pitch_rise: 6, area_sqft: 480, orientation_azimuth: 180, geometry: { poly: [[0, 0], [10, 0]] }, roof_material: "shingle" },
    { ref: "MFL", structure_ref: "S1", facet_label: "F-local", pitch_rise: 5, area_sqft: 120 },
  ],
  edges: [{ ref: "E1", edge_type: "eave", length_ft: 20, facet_ref: "MF1" }],
  penetrations: [{ ref: "P1", pen_type: "pipe_boot", quantity: 3, facet_ref: "MF1" }],
  // Summary carries BOTH editable keys (V1 values) and hidden keys (stale V1 values).
  summary: {
    deck_type: "OSB", gutter_lf: 100, full_redeck: true,       // editable (V1)
    ventilation_notes: "V1 vent note", tearoff_notes: "V1 tearoff", stories: 1,   // hidden (stale V1)
  },
};

// The user's Office edit on V1: change a visible measurement value (facet F1 area 480 -> 555) and an
// editable summary value (gutter_lf 100 -> 175). These must WIN.
edV1.facets[0].area_sqft = 555;
edV1.summary.gutter_lf = 175;

// V2: a newer authoritative server revision (e.g. a synced Field save) that changed BOTH visible and
// hidden values. All hidden/system V2 values must survive Keep My Version.
const serverV2 = {
  id: "REV1", updated_at: "2026-06-02T10:00:00Z",
  source: "field", provider: "eagleview", report_id: "EV-2222", notes: "field-crew note",
  reported_area_sqft: 3125.7,             // report metadata (V2) — must win over V1's 2000
  structures: [{ id: "S1", name: "Main House", structure_type: "main_house", included_in_scope: true }],
  facets: [
    { id: "MF1", structure_id: "S1", facet_label: "F1", pitch_rise: 6, area_sqft: 999, orientation_azimuth: 275, geometry: { poly: [[9, 9], [1, 1]] }, roof_material: "shingle" },
  ],
  edges: [{ id: "E1", edge_type: "eave", length_ft: 20, facet_id: "MF1" }],
  penetrations: [{ id: "P1", pen_type: "pipe_boot", quantity: 3, facet_id: "MF1" }],
  summary: {
    deck_type: "OSB", gutter_lf: 40, full_redeck: false,                // editable (V2)
    ventilation_notes: "V2 vent note", tearoff_notes: "V2 tearoff", stories: 2, gutter_notes: "V2 gutter",  // hidden (V2)
  },
};

const scope = { leadId: "L1" };

// ---- Keep My Version rebase ----
const p = R.buildRebasePayload(edV1, serverV2, scope);

// 1. Office-editable value wins: the user's facet area (555), not V1's 480 and not V2's 999.
{
  const f1 = p.facets.find((f) => f.ref === "MF1");
  assert.strictEqual(f1.area_sqft, 555, "user's edited plane area must win");
  ok("Office-editable Roof Plane value wins (area 555, not stale 480 nor server 999)");
}

// 2. Roof Plane technical fields (orientation, geometry) preserved from V2 by stable ref — NOT stale V1.
{
  const f1 = p.facets.find((f) => f.ref === "MF1");
  assert.strictEqual(f1.orientation_azimuth, 275, "orientation must be the latest server value");
  assert.deepStrictEqual(f1.geometry, { poly: [[9, 9], [1, 1]] }, "geometry must be the latest server value");
  ok("Roof Plane orientation + geometry preserved from V2 (not reverted to stale V1)");
}

// 3. Top-level report/system metadata preserved from V2.
{
  assert.strictEqual(p.reported_area_sqft, 3125.7, "reported area must be latest server value");
  assert.strictEqual(p.provider, "eagleview");
  assert.strictEqual(p.report_id, "EV-2222");
  assert.strictEqual(p.notes, "field-crew note");
  assert.strictEqual(p.source, "field");
  ok("top-level report metadata (reported_area/provider/report_id/notes/source) preserved from V2");
}

// 4. Summary: editable keys win (user's gutter_lf 175); hidden keys preserved from V2 (not stale V1).
{
  assert.strictEqual(p.summary.gutter_lf, 175, "user's editable summary value wins");
  assert.strictEqual(p.summary.ventilation_notes, "V2 vent note", "hidden summary field preserved from V2");
  assert.strictEqual(p.summary.tearoff_notes, "V2 tearoff", "hidden summary field preserved from V2");
  assert.strictEqual(p.summary.stories, 2, "hidden summary field preserved from V2");
  assert.strictEqual(p.summary.gutter_notes, "V2 gutter", "hidden summary key only on V2 is preserved");
  assert.notStrictEqual(p.summary.ventilation_notes, "V1 vent note", "must NOT revert hidden summary to V1");
  ok("summary editable keys win; hidden summary keys preserved from V2 (no stale-V1 revert)");
}

// 5. Locally-created plane (no server row) is kept as-is — nothing invented.
{
  const local = p.facets.find((f) => f.ref === "MFL");
  assert.ok(local, "locally-created plane survives");
  assert.strictEqual(local.area_sqft, 120);
  assert.strictEqual(local.orientation_azimuth, null, "no server orientation to preserve for a new local plane");
  assert.strictEqual(local.geometry, null, "no server geometry invented for a new local plane");
  ok("locally-created Roof Plane kept as-is (no invented server metadata)");
}

// 6. Stable identity only: rebase matches planes by id/ref, never by area/pitch/label similarity.
{
  // A server plane with a DIFFERENT id but identical area/pitch/label must NOT be matched to MF1.
  const decoy = { ...serverV2, facets: [{ id: "OTHER", facet_label: "F1", pitch_rise: 6, area_sqft: 555, orientation_azimuth: 42, geometry: { x: 1 } }] };
  const p2 = R.buildRebasePayload(edV1, decoy, scope);
  const f1 = p2.facets.find((f) => f.ref === "MF1");
  assert.notStrictEqual(f1.orientation_azimuth, 42, "MF1 must NOT absorb technical data from a different-id plane");
  assert.notDeepStrictEqual(f1.geometry, { x: 1 }, "MF1 must NOT absorb geometry from a different-id plane");
  assert.strictEqual(f1.orientation_azimuth, 180, "with no id match, MF1 keeps its own (local) technical value");
  ok("plane matching is by stable id/ref only — never fuzzy by area/pitch/label");
}

// 7. Normal (non-conflict) editable payload is unchanged: the local form is authoritative end-to-end.
{
  const np = R.buildEditablePayload(edV1, serverV2, scope);
  assert.strictEqual(np.reported_area_sqft, 2000, "normal save uses the form's reported area");
  assert.strictEqual(np.facets[0].orientation_azimuth, 180, "normal save uses the form's orientation");
  assert.strictEqual(np.summary.ventilation_notes, "V1 vent note", "normal save sends the form summary as-is");
  ok("buildEditablePayload (normal save) unchanged — form is authoritative when there is no conflict");
}

console.log("\nOFFICE KEEP-MY-VERSION HIDDEN-METADATA REBASE: all " + n + " assertions passed");
