"use strict";
// Roof Sketch measurements reference: the panel must show ONLY the measurements that belong to the
// structure being sketched (relational scoping), grouped and totaled correctly.
const assert = require("assert");
const { summarizeStructureMeasurements, summarizeScoped } = require("../sketchMeasurementsSummary");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

const detail = {
  structures: [{ id: "S1" }, { id: "S2" }],
  facets: [
    { id: "F1", structure_id: "S1", facet_label: "Front", pitch_rise: 6, area_sqft: 1250, width_ft: 25, length_ft: 50 },
    { id: "F2", structure_id: "S1", facet_label: "Back", pitch_rise: "", area_sqft: 310.5 },
    { id: "G1", structure_id: "S2", facet_label: "Garage", pitch_rise: 4, area_sqft: 400 },
  ],
  edges: [
    { id: "E1", facet_id: "F1", edge_type: "eave", length_ft: 25 },
    { id: "E2", facet_id: "F2", edge_type: "eave", length_ft: 17.5 },
    { id: "E3", facet_id: "F1", facet_id_secondary: "F2", edge_type: "valley", length_ft: 20 },
    { id: "E9", facet_id: "G1", edge_type: "ridge", length_ft: 30 },
  ],
  penetrations: [
    { id: "P1", facet_id: "F1", pen_type: "pipe_boot", quantity: 3 },
    { id: "P2", facet_id: "F1", pen_type: "pipe_boot", quantity: 2 },
    { id: "P3", facet_id: "F2", pen_type: "skylight", quantity: 1 },
    { id: "P9", facet_id: "G1", pen_type: "chimney", quantity: 1 },
  ],
};

const s1 = summarizeStructureMeasurements(detail, "S1");

// Only S1's planes appear (never the garage's).
assert.deepStrictEqual(s1.planes.map((p) => p.id), ["F1", "F2"]);
assert.strictEqual(s1.planes[0].label, "Front");
assert.strictEqual(s1.planes[0].pitch_rise, 6);
assert.strictEqual(s1.planes[0].width, 25);
assert.strictEqual(s1.planes[0].length, 50);
assert.strictEqual(s1.planes[1].pitch_rise, null);   // blank pitch → null (UI shows —)
assert.strictEqual(s1.planes[1].width, null);        // no dimensions
ok("planes are scoped to the structure with pitch/area/dimensions");

// Roof lines grouped by type with summed LF; eave = 25 + 17.5 = 42.5, valley = 20 (shared edge counted once).
const eave = s1.lines.find((l) => l.type === "eave");
const valley = s1.lines.find((l) => l.type === "valley");
assert.strictEqual(eave.lf, 42.5);
assert.strictEqual(valley.lf, 20);
assert.ok(!s1.lines.find((l) => l.type === "ridge"));  // ridge belongs to the garage — excluded
ok("roof lines grouped by type with total LF, scoped to the structure");

// Penetrations grouped by type with quantity; pipe_boot = 3 + 2 = 5, skylight = 1; chimney excluded (garage).
const boot = s1.pens.find((p) => p.type === "pipe_boot");
assert.strictEqual(boot.qty, 5);
assert.strictEqual(s1.pens.find((p) => p.type === "skylight").qty, 1);
assert.ok(!s1.pens.find((p) => p.type === "chimney"));
ok("penetrations grouped by type × qty, scoped to the structure");

// Totals: area = 1250 + 310.5 = 1560.5 SF → 15.605 sq, 2 planes.
assert.strictEqual(s1.totals.area, 1560.5);
assert.strictEqual(s1.totals.planeCount, 2);
assert.ok(Math.abs(s1.totals.squares - 15.6) < 0.02);
ok("structure totals (area / squares / plane count) computed from scoped planes");

// Garage (S2) shows only its own records.
const s2 = summarizeStructureMeasurements(detail, "S2");
assert.deepStrictEqual(s2.planes.map((p) => p.id), ["G1"]);
assert.strictEqual(s2.lines.length, 1);
assert.strictEqual(s2.pens[0].type, "chimney");
ok("a different structure shows only its own measurements");

// summarizeScoped works on already-scoped arrays (Office path) and drops zero-qty penetrations.
const scoped = summarizeScoped({ facets: [{ id: "F1", area_sqft: 100 }], edges: [], penetrations: [{ facet_id: "F1", pen_type: "vent", quantity: 0 }] });
assert.strictEqual(scoped.pens.length, 0);
assert.strictEqual(scoped.totals.area, 100);
ok("summarizeScoped totals already-scoped data and drops zero-quantity penetrations");

// Empty / missing detail is safe.
const empty = summarizeStructureMeasurements(null, "S1");
assert.deepStrictEqual(empty.planes, []);
assert.strictEqual(empty.totals.area, 0);
ok("missing/empty detail summarizes to an empty, zeroed reference");

console.log("\nSKETCH MEASUREMENTS REFERENCE: all " + n + " checks passed");
