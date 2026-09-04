"use strict";
// position_offset_ft (pin a cross-gable wing) + combineStructuresSitePlan (unified multi-structure plan).
// Run: node packages/roof-sketch-core/test/combineStructures.node.test.js
const assert = require("assert");
const { generateProposedSketch } = require("../generateSketch");
const { frameRoof } = require("../frameRoof");
const { combineStructuresSitePlan } = require("../combineStructures");
const { validateSketch } = require("../topology");

let n = 0; const ok = (m) => { n++; console.log("  ok -", m); };
const build = (fx) => frameRoof(generateProposedSketch(fx), fx.edges, null);
console.log("COMBINE + OFFSET:");

// ---- (1) position_offset_ft pins a projecting cross-gable wing along the host wall ----------------
const ST = { id: "ST", name: "House" };
function crossGable(offset) {
  return {
    structure: ST,
    facets: [
      { id: "M1", structure_id: "ST", label: "M1", pitch_rise: 6, width_ft: 11.18, length_ft: 48, area_sqft: 500, sort: 1 },
      { id: "M2", structure_id: "ST", label: "M2", pitch_rise: 6, width_ft: 11.18, length_ft: 48, area_sqft: 500, sort: 2 },
      { id: "G1", structure_id: "ST", label: "G1", pitch_rise: 6, width_ft: 10.06, length_ft: 16, area_sqft: 160, sort: 3, position_offset_ft: offset },
      { id: "G2", structure_id: "ST", label: "G2", pitch_rise: 6, width_ft: 10.06, length_ft: 16, area_sqft: 160, sort: 4 },
    ],
    edges: [
      { id: "RM", structure_id: "ST", edge_type: "ridge", length_ft: 48, facet_id: "M1", facet_id_secondary: "M2", sort: 1 },
      { id: "RG", structure_id: "ST", edge_type: "ridge", length_ft: 16, facet_id: "G1", facet_id_secondary: "G2", sort: 2 },
      { id: "VL", structure_id: "ST", edge_type: "valley", length_ft: 13, facet_id: "M1", facet_id_secondary: "G1", sort: 3 },
      { id: "VR", structure_id: "ST", edge_type: "valley", length_ft: 13, facet_id: "M1", facet_id_secondary: "G2", sort: 4 },
      { id: "EM1", structure_id: "ST", edge_type: "eave", length_ft: 48, facet_id: "M1", sort: 5 },
      { id: "EM2", structure_id: "ST", edge_type: "eave", length_ft: 48, facet_id: "M2", sort: 6 },
      { id: "EG1", structure_id: "ST", edge_type: "eave", length_ft: 16, facet_id: "G1", sort: 7 },
      { id: "EG2", structure_id: "ST", edge_type: "eave", length_ft: 16, facet_id: "G2", sort: 8 },
    ],
    penetrations: [],
  };
}
// The wing apex on the host slope sits at (cx, hg=~9). Default (no offset) centres at cx=24; a
// position_offset_ft=14 must move the apex to x≈14.
const def = build(crossGable(null));
const pin = build(crossGable(14));
assert.strictEqual(pin.method, "cross_gable", "offset: still solved as a cross-gable");
const apex = (doc) => doc.vertices.filter((v) => Math.abs(v.y - 9) < 1.2).map((v) => v.x).sort((a, b) => a - b);
const defApex = apex(def.doc), pinApex = apex(pin.doc);
assert.ok(defApex.some((x) => Math.abs(x - 24) < 1.0), `offset: default wing centred (apex x≈24, got ${defApex})`);
assert.ok(pinApex.some((x) => Math.abs(x - 14) < 1.0), `offset: pinned wing apex x≈14 (got ${pinApex})`);
// Pinning removes the "position approximate" warning for that wing.
assert.ok(!(pin.approximations || []).some((a) => a.code === "approx_wing_position"), "offset: pinned wing is not flagged approximate");
assert.ok((def.approximations || []).some((a) => a.code === "approx_wing_position"), "offset: unpinned wing IS flagged approximate");
ok("position_offset_ft pins a cross-gable wing exactly along the host wall (and clears the approximate flag)");

// ---- (2) combineStructuresSitePlan: side-by-side, largest first, offsets adjustable --------------
const HOUSE_F = [
  { id: "F1", structure_id: "H", label: "F1", pitch_rise: 6, width_ft: 20, length_ft: 40, area_sqft: 800, sort: 1 },
  { id: "F2", structure_id: "H", label: "F2", pitch_rise: 6, width_ft: 20, length_ft: 40, area_sqft: 800, sort: 2 },
];
const HOUSE_E = [
  { id: "RH", structure_id: "H", edge_type: "ridge", length_ft: 40, facet_id: "F1", facet_id_secondary: "F2", sort: 1 },
  { id: "EH1", structure_id: "H", edge_type: "eave", length_ft: 40, facet_id: "F1", sort: 2 },
  { id: "EH2", structure_id: "H", edge_type: "eave", length_ft: 40, facet_id: "F2", sort: 3 },
];
const GAR_F = [
  { id: "G1", structure_id: "G", label: "G1", pitch_rise: 6, width_ft: 10, length_ft: 24, area_sqft: 240, sort: 1 },
  { id: "G2", structure_id: "G", label: "G2", pitch_rise: 6, width_ft: 10, length_ft: 24, area_sqft: 240, sort: 2 },
];
const GAR_E = [
  { id: "RG2", structure_id: "G", edge_type: "ridge", length_ft: 24, facet_id: "G1", facet_id_secondary: "G2", sort: 1 },
  { id: "EG1x", structure_id: "G", edge_type: "eave", length_ft: 24, facet_id: "G1", sort: 2 },
  { id: "EG2x", structure_id: "G", edge_type: "eave", length_ft: 24, facet_id: "G2", sort: 3 },
];
const combineInput = (offsets) => ({
  structures: [
    { id: "G", name: "Garage", structure_type: "attached_garage", included_in_scope: true, sort: 1 },
    { id: "H", name: "House", structure_type: "main_house", included_in_scope: true, sort: 0 },
    { id: "X", name: "Shed", structure_type: "shed", included_in_scope: false, sort: 2 },
  ],
  facets: [...HOUSE_F, ...GAR_F, { id: "X1", structure_id: "X", label: "X1", pitch_rise: 6, width_ft: 8, length_ft: 10, area_sqft: 80, sort: 1 }],
  edges: [...HOUSE_E, ...GAR_E],
  penetrations: [],
  offsets: offsets || {},
});

const res = combineStructuresSitePlan(combineInput());
assert.strictEqual(res.ok, true, "combine: produced a plan");
assert.strictEqual(res.placed_count, 2, "combine: exactly the two in-scope structures placed (shed excluded)");
assert.strictEqual(res.placements[0].label, "House", "combine: largest structure (House) placed first");
assert.strictEqual(res.placements[1].label, "Garage", "combine: garage placed second");
// Attached structures snap flush (garage type = attached_garage) and share a common bottom baseline.
const h = res.placements[0], g = res.placements[1];
assert.ok(g.attached === true, "combine: garage recognised as an attached structure");
assert.ok(Math.abs(g.bbox.x - (h.bbox.x + h.bbox.width)) < 0.5, `combine: attached garage sits FLUSH against the house wall (h.right=${h.bbox.x + h.bbox.width}, g.x=${g.bbox.x})`);
assert.ok(Math.abs((h.bbox.y + h.bbox.height) - (g.bbox.y + g.bbox.height)) < 0.5, "combine: structures share a common bottom/eave baseline");
// Every combined facet carries its structure id; no out-of-scope structure appears.
assert.ok(res.document.facets.every((f) => f.structure_id === "H" || f.structure_id === "G"), "combine: every facet tagged to an in-scope structure");
assert.ok(!res.document.facets.some((f) => f.structure_id === "X"), "combine: out-of-scope shed excluded");
// Vertex ids are globally unique across the merged structures.
const vids = res.document.vertices.map((v) => v.id);
assert.strictEqual(new Set(vids).size, vids.length, "combine: vertex ids are unique across structures");
ok("combineStructuresSitePlan lays in-scope structures largest-first, attached ones flush + bottom-aligned, uniquely-ided");

// Deterministic: same input => byte-identical placements.
assert.deepStrictEqual(combineStructuresSitePlan(combineInput()).placements, res.placements, "combine: deterministic placements");

// Offsets nudge a structure and are honoured.
const shifted = combineStructuresSitePlan(combineInput({ G: { dx: 7, dy: -3 } }));
const g2 = shifted.placements.find((p) => p.label === "Garage");
assert.ok(Math.abs((g2.tx - g.tx) - 7) < 0.01, "combine: dx offset shifts the garage by +7 ft");
assert.ok(Math.abs((g2.ty - g.ty) - (-3)) < 0.01, "combine: dy offset shifts the garage by -3 ft");
ok("combineStructuresSitePlan honours per-structure drag offsets deterministically");

console.log(`\nCOMBINE + OFFSET: ${n} assertions passed.`);

// ---- (2b) overlap guard: a big drag that would overlap a neighbour gets nudged apart --------------
const overlapInput = {
  structures: [
    { id: "H", name: "House", structure_type: "main_house", included_in_scope: true, sort: 0 },
    { id: "D", name: "Detached Shop", structure_type: "detached_garage", included_in_scope: true, sort: 1 },
  ],
  facets: [...HOUSE_F, ...GAR_F.map((f) => ({ ...f, structure_id: "D" }))],
  edges: [...HOUSE_E, ...GAR_E.map((e) => ({ ...e, structure_id: "D" }))],
  penetrations: [],
  // Drag the shop far LEFT so it would sit on top of the house.
  offsets: { D: { dx: -60, dy: 0 } },
};
const guarded = combineStructuresSitePlan(overlapInput);
const H = guarded.placements.find((p) => p.label === "House");
const D = guarded.placements.find((p) => p.label === "Detached Shop");
const overlapX = Math.min(H.bbox.x + H.bbox.width, D.bbox.x + D.bbox.width) - Math.max(H.bbox.x, D.bbox.x);
const overlapY = Math.min(H.bbox.y + H.bbox.height, D.bbox.y + D.bbox.height) - Math.max(H.bbox.y, D.bbox.y);
assert.ok(!(overlapX > 0.1 && overlapY > 0.1), `guard: structures do not interior-overlap after a colliding drag (ox=${overlapX.toFixed(1)}, oy=${overlapY.toFixed(1)})`);
assert.deepStrictEqual(combineStructuresSitePlan(overlapInput).placements, guarded.placements, "guard: overlap resolution is deterministic");
n++; console.log("  ok - overlap guard nudges a colliding structure apart (deterministically)");

// A SMALL structure dragged fully INSIDE a large one must be pushed completely clear (not just by the
// overlap width). Porch (20x8) dragged onto the middle of the House (50x40).
const insideInput = {
  structures: [
    { id: "H", name: "House", structure_type: "main_house", included_in_scope: true, sort: 0 },
    { id: "P", name: "Porch", structure_type: "detached_garage", included_in_scope: true, sort: 1 },
  ],
  facets: [...HOUSE_F, { id: "P1", structure_id: "P", label: "P1", pitch_rise: 4, area_sqft: 160, width_ft: 8, length_ft: 20, sort: 0 }],
  edges: [...HOUSE_E, { id: "EP", structure_id: "P", edge_type: "eave", length_ft: 20, facet_id: "P1", sort: 1 }],
  penetrations: [],
  offsets: { P: { dx: -40, dy: -18 } }, // shove the small porch deep into the house
};
const ig = combineStructuresSitePlan(insideInput);
const IH = ig.placements.find((p) => p.label === "House"), IP = ig.placements.find((p) => p.label === "Porch");
const ox2 = Math.min(IH.bbox.x + IH.bbox.width, IP.bbox.x + IP.bbox.width) - Math.max(IH.bbox.x, IP.bbox.x);
const oy2 = Math.min(IH.bbox.y + IH.bbox.height, IP.bbox.y + IP.bbox.height) - Math.max(IH.bbox.y, IP.bbox.y);
assert.ok(!(ox2 > 0.1 && oy2 > 0.1), `guard: a small structure dragged INSIDE a large one is pushed fully clear (ox=${ox2.toFixed(1)}, oy=${oy2.toFixed(1)})`);
n++; console.log("  ok - overlap guard fully clears a small structure dragged inside a large one");

// ---- (3) topology inference: a structure with planes but NO roof lines still auto-draws -----------
const { inferTopologyEdges } = require("../inferTopology");
const { generateSketchGeometry } = require("../generateSketchGeometry");
console.log("TOPOLOGY INFERENCE:");
// Real garage from lead d0df5baa: G1/G2 = 20x21 gable pair, G3 = 14x16 (hip end). No edges entered.
const garage = [
  { id: "G1", structure_id: "GR", label: "G1", pitch_rise: 6, area_sqft: 420, width_ft: 20, length_ft: 21, sort: 0 },
  { id: "G2", structure_id: "GR", label: "G2", pitch_rise: 6, area_sqft: 420, width_ft: 20, length_ft: 21, sort: 1 },
  { id: "G3", structure_id: "GR", label: "G3", pitch_rise: 6, area_sqft: 224, width_ft: 14, length_ft: 16, sort: 2 },
];
const inf = inferTopologyEdges(garage);
assert.ok(inf.inferred, "infer: produced a topology for the edgeless garage");
assert.deepStrictEqual(inf.mains.slice().sort(), ["G1", "G2"], "infer: G1/G2 chosen as the main gable pair");
assert.deepStrictEqual(inf.ends, ["G3"], "infer: G3 chosen as the hip end");
assert.ok(inf.edges.some((e) => e.edge_type === "ridge"), "infer: a ridge was synthesized");
assert.strictEqual(inf.edges.filter((e) => e.edge_type === "hip").length, 2, "infer: two hips synthesized for the hip end");
const gr = generateSketchGeometry({ structure: { id: "GR" }, facets: garage, edges: [], penetrations: [] });
assert.strictEqual(gr.ok, true, "infer: edgeless garage now solves");
assert.ok((gr.document.vertices || []).length >= 6, "infer: garage produced geometry");
assert.strictEqual(gr.document.facets.length, 3, "infer: all three garage planes drawn (gable + hip end)");
// Smarter garage: depth comes from the two main 20-ft slopes (2*planRun(20,6)=35.8), the hip-end
// footprint matches G3's measured area (224), NOT a wrong depth from the end eave.
{
  const { resolveFacetBoundary } = require("../index");
  const { polygonArea } = require("../geometry");
  const xs = gr.document.vertices.map((v) => v.x), ys = gr.document.vertices.map((v) => v.y);
  const depth = Math.max(...ys) - Math.min(...ys);
  assert.ok(Math.abs(depth - 35.8) < 1.5, `infer: roof depth from the main slopes (~35.8, got ${depth.toFixed(1)})`);
  const endFacet = gr.document.facets.find((f) => f.measurement_facet_id === "G3");
  const endArea = Math.abs(polygonArea(resolveFacetBoundary(gr.document, endFacet).points));
  assert.ok(Math.abs(endArea - 224) < 8, `infer: hip-end plan footprint matches G3's measured area 224 (got ${endArea.toFixed(0)})`);
}
assert.ok(gr.inferred_topology === true, "infer: result flagged as auto-inferred (refine hint)");
assert.ok((gr.diagnostics || []).some((d) => d.code === "inferred_topology"), "infer: a refine-hint diagnostic is present");
n++; console.log("  ok - edgeless 3-plane garage auto-infers a gable-with-hip-end and draws (flagged for refine)");

// Real edges must DISABLE inference (measured roof lines always win).
const withEdge = generateSketchGeometry({ structure: { id: "GR" }, facets: garage.slice(0, 2), edges: [{ id: "R", structure_id: "GR", edge_type: "ridge", length_ft: 21, facet_id: "G1", facet_id_secondary: "G2", sort: 1 }], penetrations: [] });
assert.ok(!withEdge.inferred_topology, "infer: inference disabled when real edges exist");
n++; console.log("  ok - real edges disable inference");

console.log(`\nTOTAL: ${n} assertions passed.`);

