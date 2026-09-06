/* RoofSpan Field — three-way measurement merge for "Keep My Changes" (pure Node). */
const { threeWayMergeMeasurement } = require("../measurementRecovery");

let failures = 0;
function ok(c, m) { if (c) console.log("  \u2713", m); else { console.error("  \u2717 FAIL:", m); failures++; } }

const base = () => ({
  structures: [{ ref: "s1", name: "Main", structure_type: "main_house" }],
  facets: [{ ref: "f1", facet_label: "F1", pitch_rise: 6, area_sqft: 800 }],
  edges: [{ ref: "e1", edge_type: "hip", length_ft: 25, notes: "" }],
  pens: [{ ref: "p1", pen_type: "pipe_boot", quantity: 1, diameter_in: 12 }],
  summary: { existing_covering_type: "shingle", layers: 1 },
});

// Field changed a roof LINE; Office changed a roof PLANE (disjoint) → merge keeps BOTH.
let field = base(); field.edges = [{ ref: "e1", edge_type: "hip", length_ft: 25, notes: "FIELD NOTE" }];
let office = base(); office.facets = [{ ref: "f1", facet_label: "F1", pitch_rise: 6, area_sqft: 999 }];
let r = threeWayMergeMeasurement(base(), field, office);
ok(r.clean, "disjoint edits (Field roof-line + Office roof-plane) merge cleanly");
ok(r.merged.edges[0].notes === "FIELD NOTE", "Field-only roof-line change is applied");
ok(r.merged.facets[0].area_sqft === 999, "Office-only roof-plane change is preserved");

// Field-only summary change; Office untouched summary → Field wins, other office collections preserved.
field = base(); field.summary = { existing_covering_type: "metal", layers: 1 };
office = base(); office.structures = [{ ref: "s1", name: "Main", structure_type: "garage" }];
r = threeWayMergeMeasurement(base(), field, office);
ok(r.clean && r.merged.summary.existing_covering_type === "metal" && r.merged.structures[0].structure_type === "garage", "Field summary change + Office structure change both kept");

// BOTH sides changed the SAME collection differently → conflict, not silent overwrite.
field = base(); field.facets = [{ ref: "f1", facet_label: "F1", pitch_rise: 6, area_sqft: 700 }];
office = base(); office.facets = [{ ref: "f1", facet_label: "F1", pitch_rise: 6, area_sqft: 950 }];
r = threeWayMergeMeasurement(base(), field, office);
ok(!r.clean && r.conflicts.includes("facets"), "same roof-plane changed on both sides → conflict flagged (review, no silent overwrite)");

// BOTH changed the same summary key differently → conflict.
field = base(); field.summary = { existing_covering_type: "metal", layers: 1 };
office = base(); office.summary = { existing_covering_type: "tile", layers: 1 };
r = threeWayMergeMeasurement(base(), field, office);
ok(!r.clean && r.conflicts.includes("summary.existing_covering_type"), "same summary key changed on both sides → conflict flagged");

// No Field change at all → pure Office wins (nothing of the rep's to keep).
r = threeWayMergeMeasurement(base(), base(), (() => { const o = base(); o.pens = [{ ref: "p1", pen_type: "pipe_boot", quantity: 1, diameter_in: 20 }]; return o; })());
ok(r.clean && r.merged.pens[0].diameter_in === 20, "no Field change → Office penetration change adopted");

if (failures) { console.error(`\nTHREE-WAY MERGE: ${failures} failure(s)`); process.exit(1); }
console.log("\nTHREE-WAY MERGE: all passed");
