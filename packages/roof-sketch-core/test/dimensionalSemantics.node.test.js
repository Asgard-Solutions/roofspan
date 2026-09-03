"use strict";
// Dimensional-semantics correction: width_ft is the SLOPED eave->ridge distance, NOT the plan-view
// Y depth. Plan geometry must use plan_run = width_ft / sqrt(1+(rise/12)^2). The proposal engine's
// pitchAdjustedArea(planArea, rise) must then round-trip back to the sloped Measurement Area (~W*L).
const assert = require("assert");
const { generateSketchGeometry, planRunFromSlope, pitchAdjustedArea, polygonArea } = require("..");

let n = 0;
const ok = (name) => { n++; console.log("  \u2713 " + name); };

const facetPlanArea = (doc, f) => {
  const em = {}; doc.edges.forEach((e) => { em[e.id] = e; });
  const vm = {}; doc.vertices.forEach((v) => { vm[v.id] = v; });
  const edges = f.edgeIds.map((id) => em[id]);
  const last = edges[edges.length - 1];
  let cur = (last.v1 !== edges[0].v1 && last.v2 !== edges[0].v1) ? edges[0].v2 : edges[0].v1;
  const pts = [];
  for (const e of edges) { pts.push([vm[cur].x, vm[cur].y]); cur = e.v1 === cur ? e.v2 : e.v1; }
  return polygonArea(pts);
};
const single = (pitch) => generateSketchGeometry({
  structure: { id: "S" },
  facets: [{ id: "F1", structure_id: "S", facet_label: "F1", pitch_rise: pitch, area_sqft: 800, width_ft: 20, length_ft: 40, sort: 0 }],
  edges: [{ id: "EAVE", edge_type: "eave", length_ft: 40, facet_id: "F1", sort: 0 }],
  penetrations: [],
});

// ---- shared helper ----
assert.strictEqual(planRunFromSlope(20, 0), 20); ok("helper 0/12: plan_run == slope (20)");
assert.ok(Math.abs(planRunFromSlope(20, 6) - 17.8885) < 0.001); ok("helper 6/12: 20 -> 17.8885");
assert.ok(Math.abs(planRunFromSlope(20, 12) - 14.1421) < 0.001); ok("helper 12/12: 20 -> 14.1421");
assert.ok(Math.abs(planRunFromSlope(20, 7.5) - planRunFromSlope(20, 7.5)) === 0 && planRunFromSlope(20, 7.5) < 20); ok("helper custom decimal pitch handled");
assert.strictEqual(planRunFromSlope(20, null), null); ok("helper: null pitch -> null (never assumed)");
assert.strictEqual(planRunFromSlope(20, "abc"), null); ok("helper: invalid pitch -> null");

// ---- 0/12: plan_run = 20, plan area = 800, no deprojection ----
let r = single(0);
let f = r.document.facets[0];
assert.ok(Math.abs(facetPlanArea(r.document, f) - 800) < 1); ok("0/12: plan area = 800 (no change)");

// ---- 6/12: THE BUG CASE. plan area ~= 715.54; pitch-adjusted round-trips to ~800 (NOT ~894) ----
r = single(6); f = r.document.facets[0];
const plan6 = facetPlanArea(r.document, f);
assert.ok(Math.abs(plan6 - 715.54) < 1); ok("6/12: plan polygon area ~= 715.54 (deprojected)");
assert.ok(Math.abs(pitchAdjustedArea(plan6, 6) - 800) < 1); ok("6/12: pitch-adjusted plan area round-trips to ~800");
assert.ok(pitchAdjustedArea(plan6, 6) < 810); ok("6/12: NOT the old ~894 double-pitch bug");
assert.strictEqual(f.confirmed_area_sqft, 800); ok("6/12: confirmed Measurement Area preserved (800)");
assert.strictEqual(f.pitch_rise, 6); ok("6/12: pitch retained on facet");
assert.strictEqual(f.measurement_facet_id, "F1"); ok("6/12: Roof Plane id retained");

// ---- 12/12 round-trip ----
r = single(12); f = r.document.facets[0];
assert.ok(Math.abs(pitchAdjustedArea(facetPlanArea(r.document, f), 12) - 800) < 1); ok("12/12: round-trips to 800");
// ---- custom decimal pitch round-trip ----
r = single(7.5); f = r.document.facets[0];
assert.ok(Math.abs(pitchAdjustedArea(facetPlanArea(r.document, f), 7.5) - 800) < 1); ok("7.5/12: decimal pitch round-trips to 800");

// ---- simple gable: both sides round-trip their Areas ----
r = generateSketchGeometry({
  structure: { id: "G" },
  facets: [
    { id: "FA", structure_id: "G", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40, facet_label: "FA", sort: 0 },
    { id: "FB", structure_id: "G", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40, facet_label: "FB", sort: 1 },
  ],
  edges: [{ id: "RIDGE", edge_type: "ridge", length_ft: 40, facet_id: "FA", facet_id_secondary: "FB", sort: 0 }],
  penetrations: [],
});
assert.strictEqual(r.ok, true); ok("gable: generated");
r.document.facets.forEach((ff) => assert.ok(Math.abs(pitchAdjustedArea(facetPlanArea(r.document, ff), 6) - 720) < 1));
ok("gable: both planes round-trip to sloped Area 720");

// ---- different gable pitches: each plane deprojects with its OWN pitch ----
r = generateSketchGeometry({
  structure: { id: "G2" },
  facets: [
    { id: "FA", structure_id: "G2", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40, facet_label: "FA", sort: 0 },
    { id: "FB", structure_id: "G2", pitch_rise: 12, area_sqft: 800, width_ft: 20, length_ft: 40, facet_label: "FB", sort: 1 },
  ],
  edges: [{ id: "RIDGE", edge_type: "ridge", length_ft: 40, facet_id: "FA", facet_id_secondary: "FB", sort: 0 }],
  penetrations: [],
});
assert.strictEqual(r.ok, true); ok("diff-pitch gable: generated");
const fA = r.document.facets.find((x) => x.measurement_facet_id === "FA");
const fB = r.document.facets.find((x) => x.measurement_facet_id === "FB");
assert.ok(Math.abs(pitchAdjustedArea(facetPlanArea(r.document, fA), 6) - 720) < 1); ok("diff-pitch: FA round-trips @6/12 -> 720");
assert.ok(Math.abs(pitchAdjustedArea(facetPlanArea(r.document, fB), 12) - 800) < 1); ok("diff-pitch: FB round-trips @12/12 -> 800 (own pitch)");

// ---- standard hip: footprint from PLAN eave lengths (no double-count of slope) ----
r = generateSketchGeometry({
  structure: { id: "H" },
  facets: [
    { id: "T1", structure_id: "H", pitch_rise: 6, area_sqft: 800, facet_label: "T1", sort: 0 },
    { id: "T2", structure_id: "H", pitch_rise: 6, area_sqft: 800, facet_label: "T2", sort: 1 },
    { id: "P3", structure_id: "H", pitch_rise: 6, area_sqft: 300, facet_label: "P3", sort: 2 },
    { id: "P4", structure_id: "H", pitch_rise: 6, area_sqft: 300, facet_label: "P4", sort: 3 },
  ],
  edges: [
    { id: "RIDGE", edge_type: "ridge", length_ft: 16, facet_id: "T1", facet_id_secondary: "T2", sort: 0 },
    { id: "HFL", edge_type: "hip", length_ft: 23, facet_id: "T1", facet_id_secondary: "P3", sort: 1 },
    { id: "HFR", edge_type: "hip", length_ft: 23, facet_id: "T1", facet_id_secondary: "P4", sort: 2 },
    { id: "HBL", edge_type: "hip", length_ft: 23, facet_id: "T2", facet_id_secondary: "P3", sort: 3 },
    { id: "HBR", edge_type: "hip", length_ft: 23, facet_id: "T2", facet_id_secondary: "P4", sort: 4 },
    { id: "ET1", edge_type: "eave", length_ft: 48, facet_id: "T1", sort: 5 },
    { id: "ET2", edge_type: "eave", length_ft: 48, facet_id: "T2", sort: 6 },
    { id: "EP3", edge_type: "eave", length_ft: 32, facet_id: "P3", sort: 7 },
    { id: "EP4", edge_type: "eave", length_ft: 32, facet_id: "P4", sort: 8 },
  ],
  penetrations: [],
});
assert.strictEqual(r.ok, true); ok("hip: generated");
// total hip PLAN footprint == 48 x 32 = 1536 (eaves are plan dimensions; not double-projected)
const totalPlan = r.document.facets.reduce((s, ff) => s + Math.abs(facetPlanArea(r.document, ff)), 0);
assert.ok(Math.abs(totalPlan - 1536) < 2); ok("hip: total plan footprint = 48x32 = 1536 (no slope double-count)");

// ---- rake authority: a sloped Rake's confirmed LF is preserved even though plan XY is shorter ----
r = single(6);
const rake = r.document.edges.find((e) => e.type === "rake" && e.measurement_edge_id == null) || r.document.edges.find((e) => e.type === "rake");
// (single fixture maps only an eave; rakes are derived) -> add a mapped rake fixture instead:
const rr = generateSketchGeometry({
  structure: { id: "S" },
  facets: [{ id: "F1", structure_id: "S", pitch_rise: 6, area_sqft: 800, width_ft: 20, length_ft: 40, facet_label: "F1", sort: 0 }],
  edges: [
    { id: "EAVE", edge_type: "eave", length_ft: 40, facet_id: "F1", sort: 0 },
    { id: "RAKE", edge_type: "rake", length_ft: 20, facet_id: "F1", sort: 1 },
  ],
  penetrations: [],
});
const mappedRake = rr.document.edges.find((e) => e.measurement_edge_id === "RAKE");
assert.strictEqual(mappedRake.confirmed_length_ft, 20); ok("rake authority: confirmed sloped LF preserved (20)");
assert.ok(Math.abs(mappedRake.drawn_length_ft - 17.8885) < 0.01); ok("rake authority: plan XY segment is shorter (~17.89) and NOT forced to equal 20");
assert.strictEqual(rr.ok, true); ok("rake authority: geometry still generated (no false rejection)");

// ---- area override preserved (Width*Length != confirmed Area) ----
const ov = generateSketchGeometry({
  structure: { id: "S" },
  facets: [{ id: "F1", structure_id: "S", pitch_rise: 6, area_sqft: 850, width_ft: 20, length_ft: 40, facet_label: "F1", sort: 0 }],
  edges: [{ id: "EAVE", edge_type: "eave", length_ft: 40, facet_id: "F1", sort: 0 }],
  penetrations: [],
});
// 20*40=800 slope area, but user overrode to 850; area override is within tolerance-of-difference handling:
// generation should NOT rewrite the Area and should still produce geometry (dims themselves are valid).
assert.strictEqual(ov.ok, true); ok("area override: generation still succeeds (override does not block)");
assert.strictEqual(ov.document.facets[0].confirmed_area_sqft, 850); ok("area override: confirmed Area preserved (850, not rewritten)");

// ---- gable axis-semantics guard: Length is ridge-parallel, Width is the sloped depth ----
// valid: Ridge 40 / Length 40 / Width 20 @ 6/12 still generates correctly.
const validGable = generateSketchGeometry({
  structure: { id: "GV" },
  facets: [
    { id: "FA", structure_id: "GV", pitch_rise: 6, area_sqft: 800, width_ft: 20, length_ft: 40, facet_label: "FA", sort: 0 },
    { id: "FB", structure_id: "GV", pitch_rise: 6, area_sqft: 800, width_ft: 20, length_ft: 40, facet_label: "FB", sort: 1 },
  ],
  edges: [{ id: "RIDGE", edge_type: "ridge", length_ft: 40, facet_id: "FA", facet_id_secondary: "FB", sort: 0 }],
  penetrations: [],
});
assert.strictEqual(validGable.ok, true); ok("axis guard: valid Ridge40/Length40/Width20 gable generates");
validGable.document.facets.forEach((ff) => assert.ok(Math.abs(pitchAdjustedArea(facetPlanArea(validGable.document, ff), 6) - 800) < 1));
ok("axis guard: valid gable planes round-trip to sloped Area 800");

// swapped axes: Width matches the Ridge (40) and Length is the sloped depth (20) — no longer allowed to
// silently swap. Must be Needs Review / contradictory_dimensions, never a generated geometry.
const swappedGable = generateSketchGeometry({
  structure: { id: "GS" },
  facets: [
    { id: "FA", structure_id: "GS", pitch_rise: 6, area_sqft: 800, width_ft: 40, length_ft: 20, facet_label: "FA", sort: 0 },
    { id: "FB", structure_id: "GS", pitch_rise: 6, area_sqft: 800, width_ft: 40, length_ft: 20, facet_label: "FB", sort: 1 },
  ],
  edges: [{ id: "RIDGE", edge_type: "ridge", length_ft: 40, facet_id: "FA", facet_id_secondary: "FB", sort: 0 }],
  penetrations: [],
});
assert.strictEqual(swappedGable.ok, false); ok("axis guard: swapped Width40/Length20 gable is NOT generated");
assert.strictEqual(swappedGable.status, "needs_review"); ok("axis guard: swapped-axis gable -> needs_review");
assert.ok(swappedGable.diagnostics.some((d) => d.code === "contradictory_dimensions"));
ok("axis guard: swapped-axis gable reports contradictory_dimensions (no silent axis swap)");

console.log("\nDIMENSIONAL SEMANTICS: all " + n + " assertions passed");
