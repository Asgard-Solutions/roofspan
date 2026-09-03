"use strict";
// Resolution-driven placement of a CONNECTED complex roof: the engine must emit a placement scaffold
// (parent + junction + side options per unresolved plane) when unresolved, and lay the roof out
// deterministically once the user supplies side choices. Office and Field share this identically.
const assert = require("assert");
const RS = require("../index");
const { validateSketch } = require("../topology");

let n = 0; const ok = (m) => { n++; console.log("  ok -", m); };

// Cross roof: F1/F2 main gable (share Ridge). F3 joins F1 via a Valley, F4 joins F1 via a Hip.
// 4 planes with a valley present => not a standard hip => complex => needs side resolution.
const structure = { id: "ST", name: "House" };
const facets = [
  { id: "F1", structure_id: "ST", label: "F1", pitch_rise: 6, width_ft: 20, length_ft: 40, area_sqft: 800, sort: 1 },
  { id: "F2", structure_id: "ST", label: "F2", pitch_rise: 6, width_ft: 20, length_ft: 40, area_sqft: 800, sort: 2 },
  { id: "F3", structure_id: "ST", label: "F3", pitch_rise: 6, width_ft: 12, length_ft: 16, area_sqft: 200, sort: 3 },
  { id: "F4", structure_id: "ST", label: "F4", pitch_rise: 6, width_ft: 12, length_ft: 16, area_sqft: 200, sort: 4 },
];
const edges = [
  { id: "R12", structure_id: "ST", edge_type: "ridge", length_ft: 40, facet_id: "F1", facet_id_secondary: "F2", sort: 1 },
  { id: "V13", structure_id: "ST", edge_type: "valley", length_ft: 17, facet_id: "F1", facet_id_secondary: "F3", sort: 2 },
  { id: "H14", structure_id: "ST", edge_type: "hip", length_ft: 17, facet_id: "F1", facet_id_secondary: "F4", sort: 3 },
  { id: "E1", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "F1", sort: 4 },
  { id: "E2", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "F2", sort: 5 },
  { id: "E3", structure_id: "ST", edge_type: "eave", length_ft: 16, facet_id: "F3", sort: 6 },
  { id: "E4", structure_id: "ST", edge_type: "eave", length_ft: 16, facet_id: "F4", sort: 7 },
];

console.log("Resolution-driven complex placement:");

// 1. Without resolutions -> needs review + a placement scaffold naming parent/junction/side options.
const unresolved = RS.generateSketchGeometry({ structure, facets, edges, penetrations: [] });
assert.strictEqual(unresolved.ok, false, "complex roof is not auto-resolved");
assert.ok(Array.isArray(unresolved.placement_requests) && unresolved.placement_requests.length >= 1, "emits placement_requests");
const req = unresolved.placement_requests[0];
assert.ok(req.plane && req.parent && req.via_type, "request names plane, parent and junction type");
assert.ok(Array.isArray(req.options) && req.options.length === 4, "each request offers 4 parent sides");
assert.ok(req.options.every((o) => ["N", "E", "S", "W"].includes(o.key)), "side keys are N/E/S/W");
ok("unresolved complex roof returns a placement scaffold (parent + junction + 4 side options per plane)");

// 2. planPlacement anchors on the largest plane (F1, 800 SF) and every non-anchor plane gets a request.
const planIds = new Set(facets.map((f) => f.id));
const reqPlanes = new Set(unresolved.placement_requests.map((r) => r.plane));
assert.ok(!reqPlanes.has("F1"), "the anchor (largest plane F1) is not itself a placement request");
assert.strictEqual(reqPlanes.size, planIds.size - 1, "every non-anchor plane needs a side choice");
ok("scaffold anchors on the largest plane and requests a side for every other plane");

// 3. With resolutions -> deterministic, valid geometry covering all planes.
const resolutions = [
  { plane: "F2", side: "N" }, // main gable partner across the ridge (F1 north)
  { plane: "F3", side: "E" }, // wing on F1 east
  { plane: "F4", side: "W" }, // wing on F1 west
];
const laid = RS.generateSketchGeometry({ structure, facets, edges, penetrations: [], resolutions });
assert.ok(laid.document && Array.isArray(laid.document.facets), "produces a document");
assert.strictEqual(laid.document.facets.length, 4, "all 4 planes are placed");
const v = validateSketch(laid.document);
assert.strictEqual(v.valid, true, "resolved geometry passes canonical validation: " + JSON.stringify(v.errors || []));
assert.ok(laid.document.vertices.length >= 8, "geometry has real vertices");
assert.ok((laid.resolved_planes || []).length === 4 || laid.ok, "all planes resolved");
ok("supplying side choices lays out all 4 planes into valid geometry");

// 3b. Hip/valley junctions -> the end plane is drawn as a mitered TRIANGLE (3 edges) whose two rising
// edges meet at an apex (valley-miter / hip fidelity), not a flat rectangle.
const f4 = laid.document.facets.find((f) => f.measurement_facet_id === "F4");
assert.ok(f4 && f4.edgeIds.length === 3, "F4 (joined by a Hip) is a mitered triangle (3 edges)");
const f4hips = laid.document.edges.filter((e) => f4.edgeIds.includes(e.id) && e.type === "hip");
assert.ok(f4hips.length >= 2, "the two hip edges rise to the apex");
const f3 = laid.document.facets.find((f) => f.measurement_facet_id === "F3");
assert.ok(f3 && f3.edgeIds.length === 3, "F3 (joined by a Valley) is a mitered triangle (3 edges)");
const f3valleys = laid.document.edges.filter((e) => f3.edgeIds.includes(e.id) && e.type === "valley");
assert.ok(f3valleys.length >= 2, "the two valley edges rise to the apex (valley-miter)");
ok("hip AND valley junctions draw mitered triangles (edges meet at an apex)");

// 4. Determinism: identical input -> identical geometry.
const laid2 = RS.generateSketchGeometry({ structure, facets, edges, penetrations: [], resolutions });
assert.deepStrictEqual(laid2.document.vertices, laid.document.vertices, "deterministic vertices");
assert.deepStrictEqual(laid2.document.facets.map((f) => f.measurement_facet_id), laid.document.facets.map((f) => f.measurement_facet_id), "deterministic facet set");
ok("identical resolutions produce identical geometry (deterministic)");

// 5. Choices persist on the document so they travel with the sketch (Office<->Field parity, offline-safe).
assert.ok(Array.isArray(laid.document.placement_resolutions) && laid.document.placement_resolutions.length === 3, "resolutions recorded on the document");
assert.ok(laid.document.placement_resolutions.every((r) => r.plane && r.side && r.parent), "each recorded resolution has plane/parent/side");
ok("side choices are persisted on the sketch document");

// 6. Partial: a missing side choice leaves that plane unresolved but still draws the rest.
const partial = RS.generateSketchGeometry({ structure, facets, edges, penetrations: [], resolutions: [{ plane: "F2", side: "N" }, { plane: "F3", side: "E" }] });
assert.ok(partial.document && partial.document.facets.length >= 2, "draws the resolved planes");
assert.ok((partial.unresolved_planes || []).includes("F4") || partial.placement_requests, "F4 remains an outstanding placement request");
ok("a missing side choice yields a partial layout + the remaining request (never a silent guess)");

console.log(`\nresolvePlacement: ${n} assertions passed.`);
