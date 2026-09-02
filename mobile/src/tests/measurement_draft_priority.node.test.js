"use strict";
// Regression: an empty/orphaned Field working draft must NOT shadow the authoritative Office measurement.
// Only a draft with genuine in-progress content may win (show "Saved on device"); otherwise the Field must
// fall through and display exactly what Office has.
const assert = require("assert");
const { workingDraftHasContent } = require("../measurementDraftPriority");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

// Empty / orphaned drafts → NO content → must not shadow Office.
assert.strictEqual(workingDraftHasContent(null), false);
assert.strictEqual(workingDraftHasContent({ working: true }), false);
assert.strictEqual(workingDraftHasContent({ working: true, structures: [], facets: [], edges: [], pens: [], summary: {} }), false);
assert.strictEqual(workingDraftHasContent({ working: true, pens: [{ pen_type: "pipe_boot", quantity: 0 }], summary: {} }), false);
assert.strictEqual(workingDraftHasContent({ working: true, summary: { existing_covering_type: "", full_redeck: false, existing_layers: null } }), false);
ok("empty/orphaned working draft is treated as NO content (Office wins)");

// Real in-progress edits → content → draft wins (preserved, never lost).
assert.strictEqual(workingDraftHasContent({ working: true, structures: [{ ref: "r1", name: "Main" }] }), true);
assert.strictEqual(workingDraftHasContent({ working: true, facets: [{ ref: "f1" }] }), true);
assert.strictEqual(workingDraftHasContent({ working: true, edges: [{ _k: "e1", edge_type: "eave" }] }), true);
assert.strictEqual(workingDraftHasContent({ working: true, pens: [{ pen_type: "pipe_boot", quantity: 2 }] }), true);
assert.strictEqual(workingDraftHasContent({ working: true, summary: { existing_covering_type: "shingle" } }), true);
assert.strictEqual(workingDraftHasContent({ working: true, summary: { drip_edge_lf: 40 } }), true);
ok("a working draft with real edits (structures/facets/edges/pen qty/summary values) still wins");

console.log("\nMEASUREMENT DRAFT PRIORITY: all " + n + " checks passed");
