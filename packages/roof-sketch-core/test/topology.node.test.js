"use strict";
// Foundation hardening: edge-loop topology + gap/overlap/disconnected/duplicate validation.
const assert = require("assert");
const { createSketchDocument, validateSketch, edgeLoopVertices, sameCycle, facetComponents } = require("..");

let n = 0;
function ok(name) { n++; console.log("  \u2713 " + name); }
const codes = (list) => list.map((x) => x.code);
const has = (list, code) => codes(list).includes(code);

// --- a valid connected two-facet roof sharing a ridge edge ---
function connectedRoof() {
  const d = createSketchDocument({ structureId: "s1" });
  d.vertices = [
    { id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }, { id: "v3", x: 10, y: 8 },
    { id: "v4", x: 0, y: 8 }, { id: "v5", x: 0, y: 16 }, { id: "v6", x: 10, y: 16 },
  ];
  d.edges = [
    { id: "e1", v1: "v1", v2: "v2" }, { id: "e2", v1: "v2", v2: "v3" }, { id: "e3", v1: "v3", v2: "v4" },
    { id: "e4", v1: "v4", v2: "v1" }, { id: "e5", v1: "v4", v2: "v5" }, { id: "e6", v1: "v5", v2: "v6" },
    { id: "e7", v1: "v6", v2: "v3" },
  ];
  d.facets = [
    { id: "f1", edgeIds: ["e1", "e2", "e3", "e4"], vertexIds: ["v1", "v2", "v3", "v4"], pitch_rise: 6 },
    { id: "f2", edgeIds: ["e3", "e5", "e6", "e7"], vertexIds: ["v4", "v3", "v6", "v5"], pitch_rise: 6 },
  ];
  return d;
}

// --- edgeLoopVertices pure helper ---
assert.deepStrictEqual(
  edgeLoopVertices([{ v1: "v1", v2: "v2" }, { v1: "v2", v2: "v3" }, { v1: "v3", v2: "v4" }, { v1: "v4", v2: "v1" }]),
  ["v1", "v2", "v3", "v4"]); ok("edgeLoopVertices threads a closed square loop");
assert.strictEqual(edgeLoopVertices([{ v1: "a", v2: "b" }, { v1: "b", v2: "c" }, { v1: "c", v2: "d" }]), null);
ok("edgeLoopVertices rejects an open (non-closing) chain");
assert.strictEqual(edgeLoopVertices([{ v1: "a", v2: "b" }, { v1: "c", v2: "d" }, { v1: "d", v2: "a" }]), null);
ok("edgeLoopVertices rejects out-of-order / non-adjacent edges");

// --- sameCycle allows rotation + reflection ---
assert.ok(sameCycle(["v3", "v4", "v5", "v6"], ["v4", "v3", "v6", "v5"])); ok("sameCycle: reversal+rotation equal");
assert.ok(!sameCycle(["v1", "v2", "v3", "v4"], ["v1", "v3", "v2", "v4"])); ok("sameCycle: shuffled loop not equal");

// --- valid connected roof ---
let v = validateSketch(connectedRoof());
assert.strictEqual(v.valid, true); ok("connected two-facet roof is valid");
assert.strictEqual(facetComponents(connectedRoof()), 1); ok("shared ridge => single connected component");

// --- open facet loop (missing closing edge) ---
let d = connectedRoof();
d.facets[0].edgeIds = ["e1", "e2", "e3"]; // does not close
v = validateSketch(d);
assert.ok(has(v.errors, "open_facet_loop")); ok("non-closing edge list => open_facet_loop error");

// --- broken edge reference ---
d = connectedRoof();
d.facets[0].edgeIds = ["e1", "e2", "e3", "e404"];
v = validateSketch(d);
assert.ok(has(v.errors, "broken_edge_reference")); ok("edgeIds referencing a missing edge => broken_edge_reference");

// --- facet boundary mismatch (vertexIds contradict the authoritative edge loop) ---
d = connectedRoof();
d.facets[0].vertexIds = ["v1", "v3", "v2", "v4"]; // different cycle than e1..e4
v = validateSketch(d);
assert.ok(has(v.errors, "facet_boundary_mismatch")); ok("contradicting vertexIds => facet_boundary_mismatch");

// --- disconnected components (connected mode) ---
function twoSeparateSquares(mode) {
  const dd = createSketchDocument({ structureId: "s1", editMode: mode });
  dd.vertices = [
    { id: "a1", x: 0, y: 0 }, { id: "a2", x: 4, y: 0 }, { id: "a3", x: 4, y: 4 }, { id: "a4", x: 0, y: 4 },
    { id: "b1", x: 20, y: 0 }, { id: "b2", x: 24, y: 0 }, { id: "b3", x: 24, y: 4 }, { id: "b4", x: 20, y: 4 },
  ];
  dd.edges = [
    { id: "ea1", v1: "a1", v2: "a2" }, { id: "ea2", v1: "a2", v2: "a3" }, { id: "ea3", v1: "a3", v2: "a4" }, { id: "ea4", v1: "a4", v2: "a1" },
    { id: "eb1", v1: "b1", v2: "b2" }, { id: "eb2", v1: "b2", v2: "b3" }, { id: "eb3", v1: "b3", v2: "b4" }, { id: "eb4", v1: "b4", v2: "b1" },
  ];
  dd.facets = [
    { id: "fa", edgeIds: ["ea1", "ea2", "ea3", "ea4"], vertexIds: ["a1", "a2", "a3", "a4"] },
    { id: "fb", edgeIds: ["eb1", "eb2", "eb3", "eb4"], vertexIds: ["b1", "b2", "b3", "b4"] },
  ];
  return dd;
}
v = validateSketch(twoSeparateSquares("connected_graph"));
assert.ok(has(v.errors, "disconnected_component")); ok("connected mode + no shared edge => disconnected_component error");
assert.strictEqual(v.valid, false); ok("disconnected connected-graph is invalid");

// --- manual polygon: disconnected polygons are allowed ---
v = validateSketch(twoSeparateSquares("manual_polygon"));
assert.ok(!has(v.errors, "disconnected_component")); ok("manual mode: separate polygons are NOT a disconnected error");
assert.strictEqual(v.valid, true); ok("manual mode two separate squares is valid");

// --- duplicate facet ---
d = createSketchDocument({ structureId: "s1", editMode: "manual_polygon" });
d.vertices = [{ id: "p1", x: 0, y: 0 }, { id: "p2", x: 6, y: 0 }, { id: "p3", x: 6, y: 6 }, { id: "p4", x: 0, y: 6 }];
d.facets = [
  { id: "fx", vertexIds: ["p1", "p2", "p3", "p4"] },
  { id: "fy", vertexIds: ["p1", "p2", "p3", "p4"] },
];
v = validateSketch(d);
assert.ok(has(v.errors, "duplicate_facet")); ok("two facets with the same polygon => duplicate_facet");

// --- non-positive (degenerate/collinear) area ---
d = createSketchDocument({ structureId: "s1", editMode: "manual_polygon" });
d.vertices = [{ id: "c1", x: 0, y: 0 }, { id: "c2", x: 5, y: 0 }, { id: "c3", x: 10, y: 0 }];
d.facets = [{ id: "fc", vertexIds: ["c1", "c2", "c3"] }];
v = validateSketch(d);
assert.ok(has(v.errors, "non_positive_area")); ok("collinear facet => non_positive_area error");

// --- overlap warning (recoverable, not a block) ---
d = createSketchDocument({ structureId: "s1", editMode: "manual_polygon" });
d.vertices = [
  { id: "o1", x: 0, y: 0 }, { id: "o2", x: 10, y: 0 }, { id: "o3", x: 10, y: 10 }, { id: "o4", x: 0, y: 10 },
  { id: "p1", x: 5, y: 5 }, { id: "p2", x: 15, y: 5 }, { id: "p3", x: 15, y: 15 }, { id: "p4", x: 5, y: 15 },
];
d.facets = [
  { id: "fo", vertexIds: ["o1", "o2", "o3", "o4"] },
  { id: "fp", vertexIds: ["p1", "p2", "p3", "p4"] },
];
v = validateSketch(d);
assert.ok(has(v.warnings, "possible_overlap")); ok("overlapping facets => possible_overlap warning");
assert.strictEqual(v.errors.length, 0); ok("overlap alone is recoverable (no hard error)");
assert.strictEqual(v.valid, true); ok("overlap warning does not invalidate");

// --- possible_gap seam co-occurs with disconnected error in connected mode ---
function seamRoof() {
  const dd = createSketchDocument({ structureId: "s1", editMode: "connected_graph" });
  dd.vertices = [
    { id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }, { id: "v3", x: 10, y: 10 }, { id: "v4", x: 0, y: 10 },
    { id: "v5", x: 20, y: 0 }, { id: "v6", x: 20, y: 10 },
  ];
  dd.edges = [
    { id: "e1", v1: "v1", v2: "v2" }, { id: "e2", v1: "v2", v2: "v3" }, { id: "e3", v1: "v3", v2: "v4" }, { id: "e4", v1: "v4", v2: "v1" },
    { id: "e5", v1: "v2", v2: "v5" }, { id: "e6", v1: "v5", v2: "v6" }, { id: "e7", v1: "v6", v2: "v3" }, { id: "e8", v1: "v3", v2: "v2" },
  ];
  dd.facets = [
    { id: "f1", edgeIds: ["e1", "e2", "e3", "e4"] },
    { id: "f2", edgeIds: ["e5", "e6", "e7", "e8"] }, // e8 duplicates the geometry of e2 but is a different edge id
  ];
  return dd;
}
v = validateSketch(seamRoof());
assert.ok(has(v.warnings, "possible_gap")); ok("collinear touching facets without a shared edge => possible_gap warning");
assert.ok(has(v.errors, "disconnected_component")); ok("unstitched seam is also a hard disconnected_component error");

// --- self-intersection + zero-length still enforced ---
d = createSketchDocument({ structureId: "s1", editMode: "manual_polygon" });
d.vertices = [{ id: "a", x: 0, y: 0 }, { id: "b", x: 10, y: 0 }, { id: "c", x: 0, y: 10 }, { id: "d", x: 10, y: 10 }];
d.facets = [{ id: "f1", vertexIds: ["a", "b", "c", "d"] }];
v = validateSketch(d);
assert.ok(has(v.errors, "self_intersection")); ok("bowtie facet => self_intersection error");

// --- duplicate detection via CANONICAL resolved geometry (not vertex-id sets) ---
// (a) identical CONNECTED edge-loop facets with NO vertexIds
{
  const d = createSketchDocument({ structureId: "s1" }); // connected_graph
  d.vertices = [{ id: "v1", x: 0, y: 0 }, { id: "v2", x: 8, y: 0 }, { id: "v3", x: 8, y: 8 }, { id: "v4", x: 0, y: 8 }];
  d.edges = [{ id: "e1", v1: "v1", v2: "v2" }, { id: "e2", v1: "v2", v2: "v3" }, { id: "e3", v1: "v3", v2: "v4" }, { id: "e4", v1: "v4", v2: "v1" }];
  d.facets = [{ id: "fa", edgeIds: ["e1", "e2", "e3", "e4"] }, { id: "fb", edgeIds: ["e1", "e2", "e3", "e4"] }];
  const v = validateSketch(d);
  assert.ok(has(v.errors, "duplicate_facet")); ok("identical connected edge-loop facets (no vertexIds) => duplicate_facet");
}
// (b) identical MANUAL polygons from DIFFERENT vertex ids but the SAME coordinates
{
  const d = createSketchDocument({ structureId: "s1", editMode: "manual_polygon" });
  d.vertices = [
    { id: "a1", x: 0, y: 0 }, { id: "a2", x: 6, y: 0 }, { id: "a3", x: 6, y: 6 }, { id: "a4", x: 0, y: 6 },
    { id: "b1", x: 0, y: 0 }, { id: "b2", x: 6, y: 0 }, { id: "b3", x: 6, y: 6 }, { id: "b4", x: 0, y: 6 }];
  d.facets = [{ id: "fa", vertexIds: ["a1", "a2", "a3", "a4"] }, { id: "fb", vertexIds: ["b1", "b2", "b3", "b4"] }];
  const v = validateSketch(d);
  assert.ok(has(v.errors, "duplicate_facet")); ok("identical manual polygons via different vertex ids/same coords => duplicate_facet");
}

// --- polygon-cycle normalization for duplicate detection (rotation/reversal, incl. concave) ---
{
  const key = require("..").polygonCycleKey;
  const L = [[0, 0], [4, 0], [4, 4], [2, 1], [0, 4]]; // concave (arrow/notch) polygon
  const rotated = [[4, 4], [2, 1], [0, 4], [0, 0], [4, 0]]; // same cycle, different start
  const reversed = L.slice().reverse();                      // same cycle, opposite winding
  assert.strictEqual(key(L), key(rotated)); ok("concave polygon: rotation is duplicate-equivalent");
  assert.strictEqual(key(L), key(reversed)); ok("concave polygon: reversal is duplicate-equivalent");
  // same coordinate SET, genuinely different boundary order (swap two vertices) => different shape
  const reordered = [[0, 0], [4, 4], [4, 0], [2, 1], [0, 4]];
  assert.notStrictEqual(key(L), key(reordered)); ok("same coords, different boundary order => NOT duplicate");
}
// two concave manual facets that are rotation/reversal equivalent => duplicate_facet
{
  const d = createSketchDocument({ structureId: "s1", editMode: "manual_polygon" });
  d.vertices = [
    { id: "a1", x: 0, y: 0 }, { id: "a2", x: 4, y: 0 }, { id: "a3", x: 4, y: 4 }, { id: "a4", x: 2, y: 1 }, { id: "a5", x: 0, y: 4 },
    { id: "b1", x: 4, y: 4 }, { id: "b2", x: 2, y: 1 }, { id: "b3", x: 0, y: 4 }, { id: "b4", x: 0, y: 0 }, { id: "b5", x: 4, y: 0 }];
  d.facets = [
    { id: "fa", vertexIds: ["a1", "a2", "a3", "a4", "a5"] },
    { id: "fb", vertexIds: ["b1", "b2", "b3", "b4", "b5"] }]; // rotation of fa, different ids
  assert.ok(has(validateSketch(d).errors, "duplicate_facet")); ok("rotation-equivalent concave manual facets => duplicate_facet");
}

console.log("\nTOPOLOGY HARDENING: all " + n + " assertions passed");
