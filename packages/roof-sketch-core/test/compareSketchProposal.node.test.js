"use strict";
const assert = require("assert");
const { generateSketchGeometry, compareSketchProposal } = require("..");

let n = 0;
const ok = (name) => { n++; console.log("  \u2713 " + name); };

function gableInput(overrides) {
  const base = {
    structure: { id: "S1" },
    facets: [
      { id: "FA", structure_id: "S1", facet_label: "Front", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40, sort: 0 },
      { id: "FB", structure_id: "S1", facet_label: "Back", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40, sort: 1 },
    ],
    edges: [{ id: "RIDGE", edge_type: "ridge", length_ft: 40, facet_id: "FA", facet_id_secondary: "FB", sort: 0 }],
    penetrations: [],
  };
  return overrides ? overrides(base) : base;
}
const gable = () => generateSketchGeometry(gableInput());

// ---- IDENTICAL: current == the same proposal -> identical, no differences --------------------
let cur = gable().document;
let cmp = compareSketchProposal(cur, gable());
assert.strictEqual(cmp.identical, true); ok("identical: flagged identical");
assert.strictEqual(cmp.differences.length, 0); ok("identical: zero differences");

// ---- DIMENSIONAL DIFFERENCE: ridge length changed in the new measurements --------------------
const propDim = generateSketchGeometry(gableInput((b) => { b.edges[0].length_ft = 44; return b; }));
cmp = compareSketchProposal(cur, propDim);
assert.strictEqual(cmp.identical, false); ok("dimensional: not identical");
assert.ok(cmp.changed_lines.some((l) => l.measurement_edge_id === "RIDGE" && l.changes.includes("length"))); ok("dimensional: ridge length change detected");

// ---- TOPOLOGY DIFFERENCE: current is a single plane, proposal is a gable ----------------------
const single = generateSketchGeometry({ structure: { id: "S1" }, facets: [{ id: "FA", structure_id: "S1", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, facet_label: "FA", sort: 0 }], edges: [{ id: "E", edge_type: "eave", length_ft: 20, facet_id: "FA", sort: 0 }], penetrations: [] }).document;
cmp = compareSketchProposal(single, gable());
assert.strictEqual(cmp.identical, false); ok("topology: not identical");
assert.ok(cmp.changed_planes.some((p) => p.measurement_facet_id === "FA" && p.changes.includes("topology"))); ok("topology: FA topology change detected (single->gable plane)");

// ---- NEWLY ADDED ROOF PLANE: proposal has FB, current does not --------------------------------
cmp = compareSketchProposal(single, gable());
assert.deepStrictEqual(cmp.added_planes, ["FB"]); ok("added plane: FB flagged as added");
assert.ok(cmp.differences.some((d) => d.code === "plane_added" && d.target_id === "FB")); ok("added plane: difference entry present");

// ---- REMOVED ROOF PLANE: current has FB, proposal (single) does not ---------------------------
cmp = compareSketchProposal(cur, generateSketchGeometry({ structure: { id: "S1" }, facets: [{ id: "FA", structure_id: "S1", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, facet_label: "FA", sort: 0 }], edges: [{ id: "E", edge_type: "eave", length_ft: 20, facet_id: "FA", sort: 0 }], penetrations: [] }));
assert.ok(cmp.removed_planes.includes("FB")); ok("removed plane: FB flagged as removed");

// ---- AMBIGUOUS PROPOSAL: valley pair -> needs_review + unresolved surfaced --------------------
const valley = generateSketchGeometry({
  structure: { id: "V" },
  facets: [
    { id: "F1", structure_id: "V", facet_label: "F1", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, sort: 0 },
    { id: "F2", structure_id: "V", facet_label: "F2", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, sort: 1 },
  ],
  edges: [{ id: "VAL", edge_type: "valley", length_ft: 28, facet_id: "F1", facet_id_secondary: "F2", sort: 0 }],
  penetrations: [],
});
cmp = compareSketchProposal(cur, valley);
assert.strictEqual(cmp.readiness, "needs_review"); ok("ambiguous: readiness needs_review surfaced");
assert.strictEqual(cmp.proposal_has_geometry, false); ok("ambiguous: proposal has no geometry to adopt");
assert.ok(cmp.ambiguities.length >= 1 && cmp.differences.some((d) => d.code === "ambiguity_in_proposal")); ok("ambiguous: ambiguity surfaced in comparison");

// ---- MANUAL (unmapped) current geometry is flagged as at-risk on replace ----------------------
const manualDoc = { vertices: [], edges: [], facets: [{ id: "m1", label: "Manual" }], penetrations: [], scale: { resolved: false } };
cmp = compareSketchProposal(manualDoc, gable());
assert.strictEqual(cmp.unmapped_current_facets, 1); ok("manual: unmapped current facet counted");
assert.ok(cmp.differences.some((d) => d.code === "unmapped_current_geometry")); ok("manual: unmapped-current-geometry warning present");

console.log("\nCOMPARE SKETCH PROPOSAL: all " + n + " assertions passed");
