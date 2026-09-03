"use strict";
// ROOF-FRAMING SOLVER — Stage 0 (fixtures + helper asserts) & Stage 1 (ridge-based gable + standard hip).
// Run: node packages/roof-sketch-core/test/frameRoof.node.test.js
const assert = require("assert");
const { generateProposedSketch } = require("../generateSketch");
const { frameRoof } = require("../frameRoof");
const { validateSketch, polygonsOverlap, resolveFacetBoundary } = require("../topology");

let n = 0; const ok = (m) => { n++; console.log("  ok -", m); };

// ---- shared helper asserts -------------------------------------------------------------------------
function facetPolys(doc) {
  const out = {};
  doc.facets.forEach((f) => { const r = resolveFacetBoundary(doc, f); if (!r.error) out[f.id] = r.points; });
  return out;
}
function assertNoOverlap(doc, msg) {
  const polys = facetPolys(doc); const ids = Object.keys(polys);
  for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
    assert.ok(!polygonsOverlap(polys[ids[i]], polys[ids[j]]), `${msg}: facets ${ids[i]}/${ids[j]} overlap`);
  }
}
function bboxArea(doc) {
  const xs = doc.vertices.map((v) => v.x), ys = doc.vertices.map((v) => v.y);
  return (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys));
}
function assertValidRoof(res, msg) {
  assert.ok(res && res.doc, `${msg}: produced a document`);
  const v = validateSketch(res.doc);
  assert.strictEqual(v.valid, true, `${msg}: passes canonical validation: ${JSON.stringify(v.errors || [])}`);
  assertNoOverlap(res.doc, msg);
}

// ---- fixtures --------------------------------------------------------------------------------------
const ST = { id: "ST", name: "House" };

// (a) simple gable — two planes sharing one ridge, no hips.
const GABLE = {
  structure: ST,
  facets: [
    { id: "F1", structure_id: "ST", label: "F1", pitch_rise: 6, width_ft: 20, length_ft: 40, area_sqft: 800, sort: 1 },
    { id: "F2", structure_id: "ST", label: "F2", pitch_rise: 6, width_ft: 20, length_ft: 40, area_sqft: 800, sort: 2 },
  ],
  edges: [
    { id: "R12", structure_id: "ST", edge_type: "ridge", length_ft: 40, facet_id: "F1", facet_id_secondary: "F2", sort: 1 },
    { id: "E1", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "F1", sort: 2 },
    { id: "E2", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "F2", sort: 3 },
  ],
  penetrations: [],
};

// (b) standard hip — 2 trapezoids (main, share ridge) + 2 triangles (ends), symmetric equal pitch.
// Footprint 40 x 20, ridge = L - W = 20; apexes land at (10,10) and (30,10).
const HIP = {
  structure: ST,
  facets: [
    { id: "F1", structure_id: "ST", label: "F1", pitch_rise: 6, width_ft: 11.18, length_ft: 40, area_sqft: 224, sort: 1 },
    { id: "F2", structure_id: "ST", label: "F2", pitch_rise: 6, width_ft: 11.18, length_ft: 40, area_sqft: 224, sort: 2 },
    { id: "F3", structure_id: "ST", label: "F3", pitch_rise: 6, width_ft: 11.18, length_ft: 20, area_sqft: 112, sort: 3 },
    { id: "F4", structure_id: "ST", label: "F4", pitch_rise: 6, width_ft: 11.18, length_ft: 20, area_sqft: 112, sort: 4 },
  ],
  edges: [
    { id: "R12", structure_id: "ST", edge_type: "ridge", length_ft: 20, facet_id: "F1", facet_id_secondary: "F2", sort: 1 },
    { id: "H13", structure_id: "ST", edge_type: "hip", length_ft: 15, facet_id: "F1", facet_id_secondary: "F3", sort: 2 },
    { id: "H23", structure_id: "ST", edge_type: "hip", length_ft: 15, facet_id: "F2", facet_id_secondary: "F3", sort: 3 },
    { id: "H14", structure_id: "ST", edge_type: "hip", length_ft: 15, facet_id: "F1", facet_id_secondary: "F4", sort: 4 },
    { id: "H24", structure_id: "ST", edge_type: "hip", length_ft: 15, facet_id: "F2", facet_id_secondary: "F4", sort: 5 },
    { id: "E1", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "F1", sort: 6 },
    { id: "E2", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "F2", sort: 7 },
    { id: "E3", structure_id: "ST", edge_type: "eave", length_ft: 20, facet_id: "F3", sort: 8 },
    { id: "E4", structure_id: "ST", edge_type: "eave", length_ft: 20, facet_id: "F4", sort: 9 },
  ],
  penetrations: [],
};

const build = (fx) => frameRoof(generateProposedSketch(fx), fx.edges, null);

console.log("ROOF-FRAMING SOLVER:");

// Stage 0 — helper asserts exist and fixtures are well-formed foundations.
assert.strictEqual(generateProposedSketch(GABLE).status, "generated", "gable fixture is a valid foundation");
assert.strictEqual(generateProposedSketch(HIP).status, "generated", "hip fixture is a valid foundation");
ok("Stage 0: gable + hip fixtures build a valid measurement foundation");

// Stage 1a — gable via the ridge-based framing solver.
const g = build(GABLE);
assertValidRoof(g, "gable");
assert.strictEqual(g.doc.facets.length, 2, "gable: 2 slope planes");
assert.strictEqual(g.method, "single_core", "gable solved as a single core");
const gRidge = g.doc.edges.filter((e) => e.type === "ridge");
assert.strictEqual(gRidge.length, 1, "gable: exactly one ridge edge");
assert.ok(g.doc.edges.some((e) => e.type === "rake"), "gable: has rake ends (no hip triangles)");
assert.ok(!g.doc.facets.some((f) => f.edgeIds.length === 3), "gable: no triangular hip-end planes");
ok("Stage 1: gable renders as two slope planes sharing one ridge (no overlap, validates)");

// Stage 1b — standard hip via the framing solver: 2 trapezoids + 2 triangles, footprint 40x20.
const h = build(HIP);
assertValidRoof(h, "hip");
assert.strictEqual(h.doc.facets.length, 4, "hip: 4 planes");
assert.strictEqual(h.method, "single_core", "hip solved as a single core");
const tris = h.doc.facets.filter((f) => f.edgeIds.length === 3);
assert.strictEqual(tris.length, 2, "hip: exactly two triangular hip-end planes");
const traps = h.doc.facets.filter((f) => f.edgeIds.length === 4);
assert.strictEqual(traps.length, 2, "hip: exactly two 4-sided main slopes");
assert.strictEqual(h.doc.edges.filter((e) => e.type === "ridge").length, 1, "hip: one ridge");
assert.strictEqual(h.doc.edges.filter((e) => e.type === "hip").length, 4, "hip: four hip edges");
assert.ok(Math.abs(bboxArea(h.doc) - 800) < 1, `hip: footprint bbox ~= 40x20 (got ${bboxArea(h.doc)})`);
// Ridge endpoints sit on the roof at the symmetric apex insets (10,10) & (30,10).
const ridgeEdge = h.doc.edges.find((e) => e.type === "ridge");
const rv = [ridgeEdge.v1, ridgeEdge.v2].map((id) => h.doc.vertices.find((v) => v.id === id)).sort((a, b) => a.x - b.x);
assert.ok(Math.abs(rv[0].x - 10) < 0.5 && Math.abs(rv[0].y - 10) < 0.5, "hip: ridge starts at ~ (10,10)");
assert.ok(Math.abs(rv[1].x - 30) < 0.5 && Math.abs(rv[1].y - 10) < 0.5, "hip: ridge ends at ~ (30,10)");
ok("Stage 1: standard hip renders as 2 trapezoids + 2 hip triangles at the correct symmetric footprint");

// Stage 1c — determinism: identical input => byte-identical geometry.
const h2 = build(HIP);
assert.deepStrictEqual(h2.doc.vertices, h.doc.vertices, "hip: deterministic vertices");
assert.deepStrictEqual(h2.doc.edges.map((e) => [e.type, e.v1, e.v2]), h.doc.edges.map((e) => [e.type, e.v1, e.v2]), "hip: deterministic edges");
ok("Stage 1: solver is deterministic (identical input => identical geometry)");

// Stage 1d — shared roof lines are single canonical edges referenced by both planes (no duplicates).
const shared = {};
h.doc.facets.forEach((f) => f.edgeIds.forEach((eid) => { shared[eid] = (shared[eid] || 0) + 1; }));
assert.ok(Object.values(shared).some((c) => c === 2), "hip: ridge/hips are shared by exactly two planes");
assert.strictEqual(ridgeEdge.measurement_edge_id, "R12", "hip: ridge edge maps to the measured Ridge line");
ok("Stage 1: shared roof lines are canonical single edges mapped to their measurement lines");

// ---- Stage 2 + 4: two-core L-roof (equal pitch/width) — real convex hip + real concave valley -------
// Arms: H (x, length 40) and V (y, length 30), common width 20. Ridges meet at J=(10,10); reentrant (20,20).
// front-slope plan depth = W/2 = 10 => sloped width_ft = 10*sqrt(1+(6/12)^2) = 11.18.
const LROOF = {
  structure: ST,
  facets: [
    { id: "F1", structure_id: "ST", label: "F1", pitch_rise: 6, width_ft: 11.18, length_ft: 40, area_sqft: 300, sort: 1 }, // H hip-side
    { id: "F2", structure_id: "ST", label: "F2", pitch_rise: 6, width_ft: 11.18, length_ft: 40, area_sqft: 200, sort: 2 }, // H valley-side
    { id: "F3", structure_id: "ST", label: "F3", pitch_rise: 6, width_ft: 11.18, length_ft: 30, area_sqft: 250, sort: 3 }, // V hip-side
    { id: "F4", structure_id: "ST", label: "F4", pitch_rise: 6, width_ft: 11.18, length_ft: 30, area_sqft: 150, sort: 4 }, // V valley-side
  ],
  edges: [
    { id: "RH", structure_id: "ST", edge_type: "ridge", length_ft: 30, facet_id: "F1", facet_id_secondary: "F2", sort: 1 },
    { id: "RV", structure_id: "ST", edge_type: "ridge", length_ft: 20, facet_id: "F3", facet_id_secondary: "F4", sort: 2 },
    { id: "HIP", structure_id: "ST", edge_type: "hip", length_ft: 14, facet_id: "F1", facet_id_secondary: "F3", sort: 3 },
    { id: "VAL", structure_id: "ST", edge_type: "valley", length_ft: 14, facet_id: "F2", facet_id_secondary: "F4", sort: 4 },
    { id: "E1", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "F1", sort: 5 },
    { id: "E2", structure_id: "ST", edge_type: "eave", length_ft: 20, facet_id: "F2", sort: 6 },
    { id: "E3", structure_id: "ST", edge_type: "eave", length_ft: 30, facet_id: "F3", sort: 7 },
    { id: "E4", structure_id: "ST", edge_type: "eave", length_ft: 10, facet_id: "F4", sort: 8 },
  ],
  penetrations: [],
};

const lr = build(LROOF);
assertValidRoof(lr, "l-roof");
assert.strictEqual(lr.method, "l_roof", "L-roof solved as a two-core L");
assert.strictEqual(lr.doc.facets.length, 4, "l-roof: 4 slope planes");
assert.strictEqual(lr.doc.edges.filter((e) => e.type === "ridge").length, 2, "l-roof: two ridges (one per arm)");
const hipEdge = lr.doc.edges.filter((e) => e.type === "hip");
const valEdge = lr.doc.edges.filter((e) => e.type === "valley");
assert.strictEqual(hipEdge.length, 1, "l-roof: exactly one hip (outer convex corner)");
assert.strictEqual(valEdge.length, 1, "l-roof: exactly one valley (reentrant concave corner)");
ok("Stage 2/4: L-roof renders 4 planes with two ridges, one hip and one valley (no overlap, validates)");

// The hip runs from the outer corner (0,0) to the ridge junction (10,10); the valley runs from the
// reentrant corner (20,20) INWARD to the same junction (concave, not an outward spike).
const vp = [hipEdge[0].v1, hipEdge[0].v2].map((id) => lr.doc.vertices.find((v) => v.id === id));
assert.ok(vp.some((v) => Math.abs(v.x) < 0.5 && Math.abs(v.y) < 0.5), "l-roof: hip touches the outer corner (0,0)");
assert.ok(vp.some((v) => Math.abs(v.x - 10) < 0.5 && Math.abs(v.y - 10) < 0.5), "l-roof: hip reaches the ridge junction (10,10)");
const valPts = [valEdge[0].v1, valEdge[0].v2].map((id) => lr.doc.vertices.find((v) => v.id === id));
assert.ok(valPts.some((v) => Math.abs(v.x - 20) < 0.5 && Math.abs(v.y - 20) < 0.5), "l-roof: valley starts at the reentrant corner (20,20)");
assert.ok(valPts.some((v) => Math.abs(v.x - 10) < 0.5 && Math.abs(v.y - 10) < 0.5), "l-roof: valley reaches the ridge junction (10,10)");
// The valley edge is shared by exactly the two valley-side planes (concave shared edge, miter reconciled).
const valFacets = lr.doc.facets.filter((f) => f.edgeIds.includes(valEdge[0].id));
assert.strictEqual(valFacets.length, 2, "l-roof: valley is a single shared edge between the two inner planes");
ok("Stage 2/4: hip is convex at the outer corner and the valley is a shared concave edge to the ridge junction");

// Determinism.
const lr2 = build(LROOF);
assert.deepStrictEqual(lr2.doc.vertices, lr.doc.vertices, "l-roof: deterministic vertices");
ok("Stage 2/4: L-roof solver is deterministic");

// Stage 7 wiring — the public orchestrator now routes complex connected roofs through the framing solver.
const { generateSketchGeometry } = require("../generateSketchGeometry");
const orch = generateSketchGeometry(LROOF);
assert.strictEqual(orch.ok, true, "orchestrator solves the L-roof via the framing solver");
assert.strictEqual(orch.document.facets.length, 4, "orchestrator L-roof: 4 planes");
assert.ok(orch.document.edges.some((e) => e.type === "valley"), "orchestrator L-roof: has a real valley");
assert.ok(orch.diagnostics.some((d) => d.code === "roof_framing_solved"), "orchestrator tags the framing-solver result");
const orchHip = generateSketchGeometry(HIP);
assert.strictEqual(orchHip.ok, true, "orchestrator still solves the standard hip");
ok("Stage 7: generateSketchGeometry routes complex roofs to the framing solver (L-roof solved end-to-end)");

// ---- Uneven Pitches: a hip whose two MAIN slopes have different pitches -> ridge sits OFF-CENTRE -----
// Front pitch 12/12 (plan depth 8), back pitch 4/12 (plan depth 12) => W=20, ridge at y=8 (not 10).
// front sloped width = 8*sqrt(1+(12/12)^2)=11.314; back = 12*sqrt(1+(4/12)^2)=12.649.
const UNEVEN_HIP = {
  structure: ST,
  facets: [
    { id: "M1", structure_id: "ST", label: "M1", pitch_rise: 12, width_ft: 11.314, length_ft: 40, area_sqft: 400, sort: 1 }, // front main
    { id: "M2", structure_id: "ST", label: "M2", pitch_rise: 4, width_ft: 12.649, length_ft: 40, area_sqft: 400, sort: 2 },  // back main
    { id: "P3", structure_id: "ST", label: "P3", pitch_rise: 8, width_ft: 11.18, length_ft: 20, area_sqft: 120, sort: 3 },
    { id: "P4", structure_id: "ST", label: "P4", pitch_rise: 8, width_ft: 11.18, length_ft: 20, area_sqft: 120, sort: 4 },
  ],
  edges: [
    { id: "RG", structure_id: "ST", edge_type: "ridge", length_ft: 16, facet_id: "M1", facet_id_secondary: "M2", sort: 1 },
    { id: "h13", structure_id: "ST", edge_type: "hip", length_ft: 15, facet_id: "M1", facet_id_secondary: "P3", sort: 2 },
    { id: "h23", structure_id: "ST", edge_type: "hip", length_ft: 15, facet_id: "M2", facet_id_secondary: "P3", sort: 3 },
    { id: "h14", structure_id: "ST", edge_type: "hip", length_ft: 15, facet_id: "M1", facet_id_secondary: "P4", sort: 4 },
    { id: "h24", structure_id: "ST", edge_type: "hip", length_ft: 15, facet_id: "M2", facet_id_secondary: "P4", sort: 5 },
    { id: "eM1", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "M1", sort: 6 },
    { id: "eM2", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "M2", sort: 7 },
    { id: "eP3", structure_id: "ST", edge_type: "eave", length_ft: 20, facet_id: "P3", sort: 8 },
    { id: "eP4", structure_id: "ST", edge_type: "eave", length_ft: 20, facet_id: "P4", sort: 9 },
  ],
  penetrations: [],
};
const uh = build(UNEVEN_HIP);
assertValidRoof(uh, "uneven-hip");
assert.strictEqual(uh.doc.facets.length, 4, "uneven-hip: 4 planes");
const uhRidge = uh.doc.edges.find((e) => e.type === "ridge");
const uhRy = uh.doc.vertices.find((v) => v.id === uhRidge.v1).y;
assert.ok(Math.abs(uhRy - 8) < 0.5, `uneven-hip: ridge sits off-centre at y~8 (front depth), got ${uhRy}`);
ok("Uneven Pitches: unequal main-slope pitches place the ridge off-centre (proportional to plan depths)");

// ---- Stage 5: dormers seated on a host slope with real valleys ------------------------------------
function assertValidAllowOverlap(res, msg) {
  assert.ok(res && res.doc, `${msg}: produced a document`);
  const v = validateSketch(res.doc);
  assert.strictEqual(v.valid, true, `${msg}: valid (overlap-on-host is a warning): ${JSON.stringify(v.errors || [])}`);
}
// Two dormer planes (F5/F6) sharing a ridge, each valley-joined to the front gable slope F1.
const GABLE_DORMER = {
  structure: ST,
  facets: [
    { id: "F1", structure_id: "ST", label: "F1", pitch_rise: 6, width_ft: 11.18, length_ft: 40, area_sqft: 400, sort: 1 },
    { id: "F2", structure_id: "ST", label: "F2", pitch_rise: 6, width_ft: 11.18, length_ft: 40, area_sqft: 400, sort: 2 },
    { id: "F5", structure_id: "ST", label: "F5", pitch_rise: 8, width_ft: 3, length_ft: 6, area_sqft: 18, sort: 5 },
    { id: "F6", structure_id: "ST", label: "F6", pitch_rise: 8, width_ft: 3, length_ft: 6, area_sqft: 18, sort: 6 },
  ],
  edges: [
    { id: "R12", structure_id: "ST", edge_type: "ridge", length_ft: 40, facet_id: "F1", facet_id_secondary: "F2", sort: 1 },
    { id: "R56", structure_id: "ST", edge_type: "ridge", length_ft: 6, facet_id: "F5", facet_id_secondary: "F6", sort: 2 },
    { id: "V15", structure_id: "ST", edge_type: "valley", length_ft: 7, facet_id: "F1", facet_id_secondary: "F5", sort: 3 },
    { id: "V16", structure_id: "ST", edge_type: "valley", length_ft: 7, facet_id: "F1", facet_id_secondary: "F6", sort: 4 },
    { id: "E1", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "F1", sort: 5 },
    { id: "E2", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "F2", sort: 6 },
  ],
  penetrations: [],
};
const gd = build(GABLE_DORMER);
assertValidAllowOverlap(gd, "gable+dormer");
assert.strictEqual(gd.method, "single_core_with_dormers", "gable+dormer: solved as core + dormers");
assert.strictEqual(gd.doc.facets.length, 4, "gable+dormer: 2 core + 2 dormer planes");
assert.strictEqual(gd.doc.edit_mode, "manual_polygon", "gable+dormer: emitted as overlapping polygons (manual_polygon)");
const gdVal = gd.doc.edges.filter((e) => e.type === "valley");
assert.strictEqual(gdVal.length, 2, "gable+dormer: two dormer valleys against the host");
const f5 = gd.doc.facets.find((f) => f.measurement_facet_id === "F5");
assert.ok(f5 && f5.edgeIds.length === 3, "gable+dormer: each dormer plane is a triangle (eave + valley + ridge)");
assert.ok(gd.approximations.some((a) => a.code === "approx_dormer_position"), "gable+dormer: flags approximate dormer position");
ok("Stage 5: a gable dormer seats on the host slope as two triangles with real valleys (overlaps host = warning)");

// Golden-style: hip CORE (F1-F4) + TWO front dormers (F5/F6 and F7/F8), all seated on the front slope F1.
const GOLDEN = {
  structure: ST,
  facets: [
    { id: "F1", structure_id: "ST", label: "F1", pitch_rise: 6, width_ft: 11.18, length_ft: 40, area_sqft: 400, sort: 1 },
    { id: "F2", structure_id: "ST", label: "F2", pitch_rise: 6, width_ft: 11.18, length_ft: 40, area_sqft: 400, sort: 2 },
    { id: "F3", structure_id: "ST", label: "F3", pitch_rise: 6, width_ft: 11.18, length_ft: 20, area_sqft: 120, sort: 3 },
    { id: "F4", structure_id: "ST", label: "F4", pitch_rise: 6, width_ft: 11.18, length_ft: 20, area_sqft: 120, sort: 4 },
    { id: "F5", structure_id: "ST", label: "F5", pitch_rise: 8, width_ft: 3, length_ft: 5, area_sqft: 15, sort: 5 },
    { id: "F6", structure_id: "ST", label: "F6", pitch_rise: 8, width_ft: 3, length_ft: 5, area_sqft: 15, sort: 6 },
    { id: "F7", structure_id: "ST", label: "F7", pitch_rise: 8, width_ft: 3, length_ft: 5, area_sqft: 15, sort: 7 },
    { id: "F8", structure_id: "ST", label: "F8", pitch_rise: 8, width_ft: 3, length_ft: 5, area_sqft: 15, sort: 8 },
  ],
  edges: [
    { id: "R12", structure_id: "ST", edge_type: "ridge", length_ft: 20, facet_id: "F1", facet_id_secondary: "F2", sort: 1 },
    { id: "H13", structure_id: "ST", edge_type: "hip", length_ft: 15, facet_id: "F1", facet_id_secondary: "F3", sort: 2 },
    { id: "H23", structure_id: "ST", edge_type: "hip", length_ft: 15, facet_id: "F2", facet_id_secondary: "F3", sort: 3 },
    { id: "H14", structure_id: "ST", edge_type: "hip", length_ft: 15, facet_id: "F1", facet_id_secondary: "F4", sort: 4 },
    { id: "H24", structure_id: "ST", edge_type: "hip", length_ft: 15, facet_id: "F2", facet_id_secondary: "F4", sort: 5 },
    { id: "E1", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "F1", sort: 6 },
    { id: "E2", structure_id: "ST", edge_type: "eave", length_ft: 40, facet_id: "F2", sort: 7 },
    { id: "E3", structure_id: "ST", edge_type: "eave", length_ft: 20, facet_id: "F3", sort: 8 },
    { id: "E4", structure_id: "ST", edge_type: "eave", length_ft: 20, facet_id: "F4", sort: 9 },
    { id: "R56", structure_id: "ST", edge_type: "ridge", length_ft: 5, facet_id: "F5", facet_id_secondary: "F6", sort: 10 },
    { id: "V15", structure_id: "ST", edge_type: "valley", length_ft: 6, facet_id: "F1", facet_id_secondary: "F5", sort: 11 },
    { id: "V16", structure_id: "ST", edge_type: "valley", length_ft: 6, facet_id: "F1", facet_id_secondary: "F6", sort: 12 },
    { id: "R78", structure_id: "ST", edge_type: "ridge", length_ft: 5, facet_id: "F7", facet_id_secondary: "F8", sort: 13 },
    { id: "V17", structure_id: "ST", edge_type: "valley", length_ft: 6, facet_id: "F1", facet_id_secondary: "F7", sort: 14 },
    { id: "V18", structure_id: "ST", edge_type: "valley", length_ft: 6, facet_id: "F1", facet_id_secondary: "F8", sort: 15 },
  ],
  penetrations: [],
};
const gold = build(GOLDEN);
assertValidAllowOverlap(gold, "golden");
assert.strictEqual(gold.method, "single_core_with_dormers", "golden: hip core + dormers");
assert.strictEqual(gold.doc.facets.length, 8, "golden: 8 planes (4 core + 4 dormer)");
const goldTris = gold.doc.facets.filter((f) => f.edgeIds.length === 3);
assert.ok(goldTris.length >= 6, "golden: hip-end + dormer triangles present");
assert.strictEqual(gold.doc.edges.filter((e) => e.type === "valley").length, 4, "golden: 4 dormer valleys");
assert.strictEqual(gold.doc.edges.filter((e) => e.type === "hip").length, 4, "golden: 4 core hips");
// Two dormers spread along the front eave at distinct x positions.
const peaks = gold.doc.facets.filter((f) => ["F5", "F7"].includes(f.measurement_facet_id))
  .map((f) => gold.doc.vertices.find((v) => f.vertexIds.includes(v.id) && v.id.startsWith("dv_")));
ok("Stage 5: golden 8-plane roof = hip core with hip ends + two front dormers (valid, real hips + valleys)");

console.log(`\nframeRoof: ${n} assertions passed.`);