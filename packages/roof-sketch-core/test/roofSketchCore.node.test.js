"use strict";
const assert = require("assert");
const {
  createSketchDocument, normalizeSketchDocument, distance, calibrateScale,
  polygonArea, pitchAdjustedArea, validateSketch, deriveProposals, compareProposal,
  findSharedEdges,
} = require("..");

let n = 0;
function ok(name) { n++; console.log("  \u2713 " + name); }

// --- geometry math with exact known results ---
assert.strictEqual(polygonArea([[0, 0], [10, 0], [10, 8], [0, 8]]), 80); ok("polygon area shoelace = 80");
assert.strictEqual(Math.round(pitchAdjustedArea(80, 6) * 1000) / 1000, 89.443); ok("pitch-adjusted area 6/12 = 89.443");
assert.strictEqual(pitchAdjustedArea(100, 0), 100); ok("flat pitch = plan area");
assert.strictEqual(distance([0, 0], [3, 4]), 5); ok("distance 3-4-5 = 5");

const scale = calibrateScale({ canvasDistance: 10, realFeet: 25 });
assert.strictEqual(scale.feetPerUnit, 2.5); ok("calibrateScale feetPerUnit = 2.5");
assert.strictEqual(scale.resolved, true); ok("calibrateScale resolved");

// --- canonical document ---
const doc = createSketchDocument({ structureId: "s1" });
assert.strictEqual(doc.schema_version, 1); ok("schema_version = 1");
assert.strictEqual(doc.edit_mode, "connected_graph"); ok("default edit_mode connected_graph");
assert.strictEqual(doc.structure_id, "s1"); ok("structure_id stored");
assert.deepStrictEqual(doc.vertices, []); ok("starts with no vertices");
assert.strictEqual(normalizeSketchDocument({}).schema_version, 1); ok("normalize fills schema_version");
assert.strictEqual(normalizeSketchDocument({ edit_mode: "manual_polygon" }).edit_mode, "manual_polygon"); ok("normalize keeps manual_polygon mode");

// --- build a small connected two-facet roof sharing a ridge edge ---
function build() {
  const d = createSketchDocument({ structureId: "s1" });
  d.vertices = [
    { id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 },
    { id: "v3", x: 10, y: 8 }, { id: "v4", x: 0, y: 8 },
    { id: "v5", x: 0, y: 16 }, { id: "v6", x: 10, y: 16 },
  ];
  d.edges = [
    { id: "e1", v1: "v1", v2: "v2", type: "eave" },
    { id: "e2", v1: "v2", v2: "v3", type: "rake" },
    { id: "e3", v1: "v3", v2: "v4", type: "ridge" },   // shared ridge
    { id: "e4", v1: "v4", v2: "v1", type: "rake" },
    { id: "e5", v1: "v4", v2: "v5", type: "rake" },
    { id: "e6", v1: "v5", v2: "v6", type: "eave" },
    { id: "e7", v1: "v6", v2: "v3", type: "rake" },
  ];
  d.facets = [
    { id: "f1", label: "F1", edgeIds: ["e1", "e2", "e3", "e4"], vertexIds: ["v1", "v2", "v3", "v4"], pitch_rise: 6 },
    { id: "f2", label: "F2", edgeIds: ["e3", "e5", "e6", "e7"], vertexIds: ["v4", "v3", "v6", "v5"], pitch_rise: 6 },
  ];
  return d;
}

const shared = findSharedEdges(build());
assert.deepStrictEqual(shared.map((s) => s.edgeId), ["e3"]); ok("shared ridge edge referenced by two facets detected");

// --- validation: valid connected graph ---
let v = validateSketch(build());
assert.strictEqual(v.valid, true); ok("connected two-facet graph is valid");

// --- zero-length edge blocked ---
const zl = build();
zl.vertices[1] = { id: "v2", x: 0, y: 0 }; // v2 coincides with v1 -> e1 zero length
v = validateSketch(zl);
assert.strictEqual(v.valid, false); ok("zero-length edge invalidates");
assert.ok(v.errors.some((e) => e.code === "zero_length_edge")); ok("zero-length edge error code present");

// --- self-intersection blocked (bowtie facet) ---
const si = createSketchDocument({ structureId: "s1" });
si.vertices = [{ id: "a", x: 0, y: 0 }, { id: "b", x: 10, y: 0 }, { id: "c", x: 0, y: 10 }, { id: "d", x: 10, y: 10 }];
si.edges = [
  { id: "e1", v1: "a", v2: "b", type: "eave" }, { id: "e2", v1: "b", v2: "c", type: "rake" },
  { id: "e3", v1: "c", v2: "d", type: "eave" }, { id: "e4", v1: "d", v2: "a", type: "rake" },
];
si.facets = [{ id: "f1", label: "F1", edgeIds: ["e1", "e2", "e3", "e4"], vertexIds: ["a", "b", "c", "d"], pitch_rise: 6 }];
v = validateSketch(si);
assert.strictEqual(v.valid, false); ok("self-intersecting facet invalidates");
assert.ok(v.errors.some((e) => e.code === "self_intersection")); ok("self-intersection error code present");

// --- unresolved scale suppresses dimensional proposals ---
const noScale = build(); // scale unresolved by default
const p0 = deriveProposals(noScale);
assert.strictEqual(p0.filter((p) => p.metric === "area_sqft" || p.metric === "length_ft").length, 0);
ok("unresolved scale produces no dimensional proposals");
assert.ok(p0.some((p) => p.code === "scale_unresolved")); ok("unresolved scale is reported");

// --- resolved scale produces area proposals ---
const scaled = build();
scaled.scale = { resolved: true, feetPerUnit: 1, feet_per_unit: 1, method: "structure_calibration" };
const p1 = deriveProposals(scaled);
const f1p = p1.find((p) => p.target_id === "f1" && p.metric === "area_sqft");
assert.ok(f1p, "expected area proposal for f1");
// plan area 80 * sqrt(1.25) = 89.4427...
assert.strictEqual(Math.round(f1p.proposed * 100) / 100, 89.44); ok("resolved scale proposes pitch-adjusted facet area");

// --- locked measured edge stays confirmed even when geometry disagrees ---
const locked = build();
locked.scale = { resolved: true, feetPerUnit: 1, feet_per_unit: 1, method: "structure_calibration" };
// e1 geometric length = 10 ft, but confirmed/locked at 42 ft
locked.edges[0].locked = true;
locked.edges[0].confirmed_length_ft = 42;
const p2 = deriveProposals(locked);
const e1prop = p2.find((p) => p.target_id === "e1" && p.metric === "length_ft" && p.decision !== "discrepancy");
assert.ok(!e1prop, "locked edge must NOT get an overwrite proposal"); ok("locked edge produces no overwrite proposal");
const disc = p2.find((p) => p.target_id === "e1" && p.decision === "discrepancy");
assert.ok(disc, "locked edge should report a discrepancy"); ok("locked edge reports discrepancy");
assert.strictEqual(disc.confirmed, 42); ok("locked confirmed value preserved (42)");

// --- compareProposal ---
const cmp = compareProposal(412, 428);
assert.strictEqual(cmp.difference, 16); ok("compareProposal difference = +16");
assert.strictEqual(cmp.confirmed, 412); ok("compareProposal keeps confirmed");

console.log("\nROOF SKETCH CORE: all " + n + " assertions passed");
